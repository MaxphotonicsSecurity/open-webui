"""PostgreSQL diagnostics tests without external database connections."""

import contextlib
import importlib.util
import io
import json
import os
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location('diagnose_postgres', Path(__file__).parents[1] / 'diagnose_postgres.py')
diagnose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose)


class PostgresDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.params = {'host': 'db', 'port': '5000', 'dbname': 'app', 'password': 'DO-NOT-PRINT', 'sslmode': 'require'}

    def test_parameters_preserve_credentials_and_tls_and_enforce_read_only(self):
        url = (
            'postgresql+psycopg://reader:DO-NOT-PRINT@db:5000/app?sslmode=verify-full&options=-c%20search_path%3Dpublic'
        )
        with patch.dict(os.environ, DATABASE_URL=url):
            params = diagnose.connection_parameters()
        self.assertEqual(params['password'], 'DO-NOT-PRINT')
        self.assertEqual(params['sslmode'], 'verify-full')
        self.assertEqual(params['connect_timeout'], '8')
        self.assertIn('search_path=public', params['options'])
        self.assertIn('default_transaction_read_only=on', params['options'])
        self.assertIn('statement_timeout=5000', params['options'])

    def test_ssl_probe_recognizes_supported_unsupported_and_closed_responses(self):
        for response, status in (
            (b'S', 'tls_supported'),
            (b'N', 'tls_not_supported'),
            (b'', 'connection_closed'),
            (b'H', 'unexpected_response'),
        ):
            with self.subTest(response=response):
                connection = MagicMock()
                connection.__enter__.return_value = connection
                connection.recv.return_value = response
                with patch.object(diagnose.socket, 'create_connection', return_value=connection):
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        diagnose.probe_protocol(self.params)
                record = json.loads(output.getvalue())
                self.assertEqual(record['stage'], 'postgres_ssl_response')
                self.assertEqual(record['status'], status)
                connection.sendall.assert_called_once_with(struct.pack('!II', 8, 80877103))
                self.assertNotIn('DO-NOT-PRINT', output.getvalue())

    def test_protocol_timeout_is_distinguished_from_tcp_timeout(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.side_effect = TimeoutError('DO-NOT-PRINT: timed out')
        with patch.object(diagnose.socket, 'create_connection', return_value=connection):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                diagnose.probe_protocol(self.params)
        record = json.loads(output.getvalue())
        self.assertEqual(record['stage'], 'postgres_ssl_response')
        self.assertEqual(record['category'], 'timeout')
        self.assertNotIn('DO-NOT-PRINT', output.getvalue())

    def test_both_drivers_only_execute_select_and_close(self):
        for name in ('psycopg2', 'psycopg'):
            with self.subTest(driver=name):
                connection = MagicMock()
                cursor = connection.cursor.return_value.__enter__.return_value
                cursor.fetchone.return_value = (1,)
                driver = SimpleNamespace(
                    __version__='test',
                    pq=SimpleNamespace(version=lambda: 180000),
                    extensions=SimpleNamespace(libpq_version=lambda: 180000),
                    connect=MagicMock(return_value=connection),
                )
                with patch.object(diagnose.importlib, 'import_module', return_value=driver):
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        self.assertTrue(diagnose.probe_driver(name, self.params))
                cursor.execute.assert_called_once_with('SELECT 1')
                connection.commit.assert_not_called()
                connection.close.assert_called_once()
                driver.connect.assert_called_once_with(**self.params)
                self.assertNotIn('DO-NOT-PRINT', output.getvalue())

    def test_one_failed_driver_does_not_skip_the_other(self):
        with patch.object(diagnose, 'connection_parameters', return_value=self.params):
            with patch.object(diagnose, 'probe_protocol'):
                with patch.object(diagnose, 'probe_driver', side_effect=[False, True]) as probe:
                    self.assertEqual(diagnose.main(), 1)
        self.assertEqual([call.args[0] for call in probe.call_args_list], ['psycopg2', 'psycopg'])

    def test_query_failure_closes_connection_without_printing_raw_errors(self):
        driver = MagicMock(__version__='test')
        driver.extensions.libpq_version.return_value = 180000
        connection = driver.connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = TimeoutError('DO-NOT-PRINT: timeout')
        with patch.object(diagnose.importlib, 'import_module', return_value=driver):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertFalse(diagnose.probe_driver('psycopg2', self.params))
        record = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(record['stage'], 'read_only_query')
        self.assertEqual(record['category'], 'timeout')
        self.assertNotIn('DO-NOT-PRINT', output.getvalue())
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
