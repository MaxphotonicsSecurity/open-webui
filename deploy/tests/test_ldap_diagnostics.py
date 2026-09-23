"""Read-only diagnostics: no real PostgreSQL or AD connections."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location('diagnose_ldap', Path(__file__).parents[1] / 'diagnose_ldap.py')
diagnose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.secret = 'example/secret$'
        self.env = {
            'DATABASE_URL': 'postgresql+psycopg://reader:example%2Fsecret%24@db.internal:5000/webui?ssl=prefer',
            'ENABLE_PERSISTENT_CONFIG': 'true',
            'ENABLE_LDAP': 'true',
        }
        self.env_patch = patch.dict(os.environ, self.env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_url_credentials_and_ssl_options_survive_both_drivers(self):
        for driver in ('psycopg', 'psycopg2'):
            with self.subTest(driver=driver):
                params, source = diagnose.database_parameters(driver)
                self.assertEqual(source, 'DATABASE_URL')
                self.assertEqual(params['password'], self.secret)
                self.assertEqual(params['sslmode'], 'prefer')
                self.assertEqual(params['port'], '5000')
                self.assertNotIn('ssl', params)
                output = json.dumps(diagnose.database_summary(params, source, driver))
                self.assertNotIn(self.secret, output)
                self.assertNotIn('reader', output)

    def test_split_database_environment_overrides_stale_url_like_application(self):
        with patch.dict(os.environ, {
            'DATABASE_TYPE': 'postgresql', 'DATABASE_HOST': 'current-db.internal',
            'DATABASE_PORT': '5432', 'DATABASE_NAME': 'current',
            'DATABASE_USER': 'current-reader', 'DATABASE_PASSWORD': 'new-secret',
        }):
            params, source = diagnose.database_parameters()
        self.assertEqual(params['host'], 'current-db.internal')
        self.assertEqual(params['dbname'], 'current')
        self.assertEqual(params['password'], 'new-secret')
        self.assertNotEqual(source, 'DATABASE_URL')

    def test_explicit_sslmode_takes_precedence(self):
        with patch.dict(os.environ, DATABASE_URL=self.env['DATABASE_URL'] + '&sslmode=verify-full'):
            params, _ = diagnose.database_parameters()
        self.assertEqual(params['sslmode'], 'verify-full')
        self.assertNotIn('ssl', params)

    def test_persisted_configuration_wins_and_queries_are_read_only(self):
        for driver in ('psycopg', 'psycopg2'):
            with self.subTest(driver=driver):
                connection = MagicMock()
                cursor = connection.cursor.return_value.__enter__.return_value
                cursor.fetchall.return_value = [('ldap.server.app_password', self.secret)]
                with patch(f'{driver}.connect', return_value=connection), contextlib.redirect_stdout(io.StringIO()) as out:
                    config = diagnose.load_config(driver)
                self.assertEqual(config['ldap.server.app_password'], self.secret)
                if driver == 'psycopg':
                    self.assertIs(connection.read_only, True)
                else:
                    connection.set_session.assert_called_once_with(readonly=True)
                connection.commit.assert_not_called()
                connection.close.assert_called_once_with()
                self.assertNotIn(self.secret, out.getvalue())

    def test_classifies_connection_failures_without_printing_raw_error(self):
        import psycopg

        cases = [
            ('password authentication failed', 'database_authentication_failed'),
            ('could not translate host name', 'database_dns_failed'),
            ('Connection refused', 'database_connection_refused'),
            ('timeout expired', 'database_timeout'),
            ('SCRAM authentication requires libpq version 10', 'client_libpq_too_old'),
            ('no pg_hba.conf entry', 'database_access_rule'),
            ('SSL error: certificate verify failed', 'database_tls_failed'),
            ('remaining connection slots are reserved', 'database_connection_limit'),
        ]
        for message, category in cases:
            with self.subTest(category=category):
                exc = psycopg.OperationalError(f'{message}: {self.secret}')
                with patch('psycopg.connect', side_effect=exc), patch.object(diagnose, 'check_bind') as bind:
                    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                        result = diagnose.main(['--config-only'])
                self.assertEqual(result, 2)
                self.assertIn(category, err.getvalue())
                self.assertIn('database_connect', err.getvalue())
                self.assertNotIn(self.secret, out.getvalue() + err.getvalue())
                bind.assert_not_called()

    def test_query_failure_has_different_stage(self):
        import psycopg

        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = psycopg.errors.UndefinedTable('table does not exist ' + self.secret)
        with patch('psycopg.connect', return_value=connection), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(diagnose.ConfigReadError) as raised:
                diagnose.load_config()
        self.assertEqual(raised.exception.details['stage'], 'config_read')
        self.assertEqual(raised.exception.details['category'], 'config_table_not_found')
        self.assertNotIn(self.secret, str(raised.exception))
        connection.close.assert_called_once_with()

    def test_config_only_success_does_not_attempt_ad_bind(self):
        with patch.object(diagnose, 'load_config', return_value={'ldap.enable': True}), patch.object(diagnose, 'check_bind') as bind:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(diagnose.main(['--config-only']), 0)
        self.assertFalse(json.loads(out.getvalue())['ad_bind_attempted'])
        bind.assert_not_called()

    def test_disabled_persistence_does_not_connect_to_database(self):
        with patch.dict(os.environ, ENABLE_PERSISTENT_CONFIG='false'), patch('psycopg.connect') as connect:
            self.assertEqual(diagnose.load_config()['ldap.enable'], 'true')
        connect.assert_not_called()

    def test_ad_bind_is_single_attempt_and_codes_do_not_expose_message(self):
        with patch.dict(os.environ, {
            'ENABLE_PERSISTENT_CONFIG': 'false', 'LDAP_APP_DN': 'svc@example.test',
            'LDAP_APP_PASSWORD': self.secret, 'LDAP_SERVER_HOST': 'dc.example.test',
            'LDAP_SERVER_PORT': '636',
        }):
            config = diagnose.load_config()
        connection = MagicMock()
        connection.bind.return_value = False
        connection.result = {'result': 49, 'description': self.secret, 'message': 'error data 775, ' + self.secret}
        with patch('ldap3.Connection', return_value=connection), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(diagnose.check_bind(config), 1)
        connection.bind.assert_called_once_with()
        connection.search.assert_not_called()
        connection.unbind.assert_called_once_with()
        self.assertNotIn(self.secret, out.getvalue())
        self.assertNotIn('svc@example.test', out.getvalue())
        self.assertIn('invalidCredentials', out.getvalue())
        self.assertIn('775', out.getvalue())


if __name__ == '__main__':
    unittest.main()
