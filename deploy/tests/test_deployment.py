"""Deployment regression tests. Docker calls and database connections are mocked."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('deployment_bootstrap', ROOT / 'deploy/bootstrap.py')
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class DeploymentCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / 'repo with spaces'
        self.repo.mkdir()
        (self.repo / 'deploy').mkdir()
        shutil.copyfile(ROOT / 'deploy/deploy.sh', self.repo / 'deploy/deploy.sh')
        for environment in ('local', 'test', 'prod'):
            directory = self.repo / 'deploy' / environment
            directory.mkdir(parents=True)
            (directory / '.env').write_text(f'DEPLOYMENT_ENV={environment}\nWEBUI_SECRET_KEY=test-secret\n')
            shutil.copyfile(ROOT / 'deploy' / environment / 'docker-compose.yaml', directory / 'docker-compose.yaml')
            shutil.copyfile(ROOT / 'deploy' / environment / 'deploy.sh', directory / 'deploy.sh')
        shutil.copyfile(ROOT / 'deploy/bootstrap.py', self.repo / 'deploy/bootstrap.py')
        self.log = self.base / 'commands.jsonl'
        binary_dir = self.base / 'bin'
        binary_dir.mkdir()
        docker = binary_dir / 'docker'
        docker.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
record = {'args': args, 'env_file': os.getenv('OPEN_WEBUI_ENV_FILE')}
if 'run' in args:
    record['bootstrap'] = 'def ensure_database' in sys.stdin.read()
with open(os.environ['FAKE_DOCKER_LOG'], 'a') as file:
    file.write(json.dumps(record) + '\\n')
if os.getenv('FAKE_FAIL_STAGE') in args:
    sys.exit(42)
if '--images' in args:
    print('company/open-webui:test-fixture')
''')
        docker.chmod(0o755)
        self.env = dict(os.environ, PATH=f'{binary_dir}:{os.environ["PATH"]}', FAKE_DOCKER_LOG=str(self.log))
        # A caller's environment must not select another service env_file/project.
        self.env.update(OPEN_WEBUI_ENV_FILE='/wrong/.env', COMPOSE_PROJECT_NAME='wrong-project')

    def run_deploy(self, environment='prod', *options):
        return subprocess.run(
            ['bash', str(self.repo / 'deploy' / environment / 'deploy.sh'), *options],
            cwd=self.base,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def records(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_all_environments_work_outside_repository(self):
        for environment in ('local', 'test', 'prod'):
            with self.subTest(environment=environment):
                self.log.unlink(missing_ok=True)
                result = self.run_deploy(environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                commands = self.records()
                operations = [item for item in commands if '--project-name' in item['args']]
                for item in operations:
                    args = item['args']
                    self.assertEqual(args[args.index('--project-name') + 1], f'open-webui-{environment}')
                    self.assertEqual(item['env_file'], str(self.repo / 'deploy' / environment / '.env'))
                build = next(i for i, item in enumerate(commands) if 'build' in item['args'])
                initialize = next(i for i, item in enumerate(commands) if 'run' in item['args'])
                start = next(i for i, item in enumerate(commands) if 'up' in item['args'])
                self.assertLess(build, initialize)
                self.assertLess(initialize, start)
                self.assertTrue(commands[initialize]['bootstrap'])
                self.assertIn('--wait', commands[start]['args'])
                self.assertFalse(any('down' in item['args'] for item in commands))

    def test_check_does_not_build_initialize_or_start(self):
        result = self.run_deploy('prod', '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        for item in self.records():
            self.assertFalse(set(item['args']) & {'build', 'run', 'up', 'info'})

    def test_no_build_and_skip_database_creation(self):
        result = self.run_deploy('prod', '--no-build', '--skip-db-init', '--wait-timeout', '600')
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [item['args'] for item in self.records()]
        self.assertFalse(any('build' in args for args in commands))
        self.assertTrue(any('inspect' in args for args in commands))
        self.assertIn('--check-only', next(args for args in commands if 'run' in args))
        self.assertIn('600', next(args for args in commands if 'up' in args))

    def test_failures_stop_later_steps(self):
        for stage, forbidden in [('build', 'run'), ('run', 'up'), ('up', None)]:
            with self.subTest(stage=stage):
                self.log.unlink(missing_ok=True)
                self.env['FAKE_FAIL_STAGE'] = stage
                result = self.run_deploy()
                self.assertNotEqual(result.returncode, 0)
                if forbidden:
                    self.assertFalse(any(forbidden in item['args'] for item in self.records()))
                self.assertNotIn('[完成]', result.stdout)

    def test_missing_env_fails_without_creating_or_overwriting_it(self):
        path = self.repo / 'deploy/prod/.env'
        path.unlink()
        result = self.run_deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(path.exists())
        self.assertEqual(self.records(), [])

    def test_placeholders_are_reported_without_values(self):
        path = self.repo / 'deploy/prod/.env'
        path.write_text('DATABASE_URL=postgresql://u:secret-CHANGE_ME@host/db\n')
        result = self.run_deploy('prod', '--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DATABASE_URL', result.stderr)
        self.assertNotIn('secret-CHANGE_ME', result.stdout + result.stderr)
        self.assertEqual(self.records(), [])

    def test_env_is_never_executed_as_shell_code(self):
        marker = self.base / 'must-not-exist'
        (self.repo / 'deploy/prod/.env').write_text(f'EXAMPLE=$(touch "{marker}")\n')
        result = self.run_deploy('prod', '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())

    def test_invalid_options_fail_before_docker(self):
        for options in [('--wait-timeout',), ('--wait-timeout', '0'), ('--unknown',)]:
            with self.subTest(options=options):
                result = self.run_deploy('prod', *options)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.records(), [])


class DatabaseBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.params = bootstrap.database_parameters(
            'postgresql://app:%2Ftest%40secret@db:5000/business?sslmode=require'
        )

    def connection(self, *rows):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = rows
        return connection, cursor

    def test_url_decodes_password_and_preserves_tls(self):
        self.assertEqual(self.params['password'], '/test@secret')
        self.assertEqual(self.params['sslmode'], 'require')
        self.assertEqual(self.params['port'], '5000')
        self.assertEqual(self.params['connect_timeout'], '10')

    def test_rejects_missing_database_and_management_databases(self):
        for url in ('postgresql://u@host', 'postgresql://u@host/postgres', 'postgresql://u@host/template1'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                bootstrap.database_parameters(url)

    def test_creates_missing_database_with_quoted_identifiers(self):
        admin, cursor = self.connection(None)
        target, _ = self.connection((1,))
        params = dict(self.params, dbname='a "quoted" database', user='odd-role')
        with patch.object(bootstrap.psycopg2, 'connect', side_effect=[admin, target]) as connect:
            bootstrap.ensure_database(params)
        self.assertEqual(connect.call_args_list[0].kwargs['dbname'], 'postgres')
        self.assertEqual(connect.call_args_list[1].kwargs['dbname'], params['dbname'])
        self.assertTrue(admin.autocommit)
        create = cursor.execute.call_args_list[1].args[0]
        self.assertIn(sql.Identifier(params['dbname']), list(create))
        self.assertIn(sql.Identifier(params['user']), list(create))
        admin.close.assert_called_once()
        target.close.assert_called_once()

    def test_existing_database_is_not_recreated(self):
        admin, cursor = self.connection((1,))
        target, _ = self.connection((1,))
        with patch.object(bootstrap.psycopg2, 'connect', side_effect=[admin, target]):
            bootstrap.ensure_database(self.params)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_check_only_connects_directly_to_target_without_ddl(self):
        target, cursor = self.connection((1,))
        with patch.object(bootstrap.psycopg2, 'connect', return_value=target) as connect:
            bootstrap.ensure_database(self.params, check_only=True)
        connect.assert_called_once_with(**self.params)
        cursor.execute.assert_called_once_with('SELECT 1')

    def test_existing_vector_is_not_recreated(self):
        connection, cursor = self.connection(('0.8.6', 'public'))
        with patch.object(bootstrap.psycopg2, 'connect', return_value=connection):
            bootstrap.ensure_vector(self.params)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_installs_available_vector(self):
        connection, cursor = self.connection(None, (1,))
        with patch.object(bootstrap.psycopg2, 'connect', return_value=connection):
            bootstrap.ensure_vector(self.params)
        cursor.execute.assert_any_call('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')

    def test_missing_server_extension_fails(self):
        connection, cursor = self.connection(None, None)
        with patch.object(bootstrap.psycopg2, 'connect', return_value=connection), self.assertRaises(ValueError):
            bootstrap.ensure_vector(self.params)
        self.assertEqual(cursor.execute.call_count, 2)

    def test_check_only_missing_vector_does_not_create_it(self):
        connection, cursor = self.connection(None)
        with patch.object(bootstrap.psycopg2, 'connect', return_value=connection), self.assertRaises(ValueError):
            bootstrap.ensure_vector(self.params, check_only=True)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_wrong_environment_fails_before_database_access(self):
        with patch.dict(os.environ, {'DEPLOYMENT_ENV': 'local'}, clear=True):
            with patch.object(bootstrap.psycopg2, 'connect') as connect, self.assertRaises(ValueError):
                bootstrap.main(['prod'])
            connect.assert_not_called()

    def test_vector_connection_failure_reports_stage_without_credentials(self):
        error = psycopg2.OperationalError(
            'connection to postgresql://app:DO-NOT-PRINT@private-host/db failed: Connection timed out'
        )
        with patch.object(bootstrap.psycopg2, 'connect', side_effect=error):
            with self.assertRaises(bootstrap.DatabaseBootstrapError) as raised:
                bootstrap.ensure_vector(self.params, check_only=True)
        message = str(raised.exception)
        self.assertIn('pgvector 扩展连接与检查', message)
        self.assertIn('超时', message)
        self.assertIn('SQLSTATE=不可用', message)
        for secret in ('DO-NOT-PRINT', 'private-host', '/test@secret'):
            self.assertNotIn(secret, message)

    def test_extension_query_failure_reports_stage_and_closes_connection(self):
        connection, cursor = self.connection()
        cursor.execute.side_effect = psycopg2.OperationalError('server closed the connection unexpectedly')
        with patch.object(bootstrap.psycopg2, 'connect', return_value=connection):
            with self.assertRaises(bootstrap.DatabaseBootstrapError) as raised:
                bootstrap.ensure_vector(self.params)
        self.assertIn('pgvector', str(raised.exception))
        self.assertIn('断开连接', str(raised.exception))
        connection.close.assert_called_once()

    def test_admin_and_target_connection_failures_are_distinguished(self):
        error = psycopg2.OperationalError('connection refused')
        for check_only, expected in ((False, '管理库 postgres'), (True, '目标库连接验证')):
            with self.subTest(check_only=check_only):
                with patch.object(bootstrap.psycopg2, 'connect', side_effect=error):
                    with self.assertRaises(bootstrap.DatabaseBootstrapError) as raised:
                        bootstrap.ensure_database(self.params, check_only=check_only)
                self.assertIn(expected, str(raised.exception))
                self.assertIn('连接被拒绝', str(raised.exception))

    def test_database_errors_are_classified_without_printing_driver_text(self):
        examples = (
            ('password authentication failed', '密码认证失败'),
            ('no pg_hba.conf entry', '认证规则拒绝'),
            ('remaining connection slots are reserved', '连接数已达上限'),
            ('could not translate host name', '主机名解析失败'),
            ('certificate verify failed', '证书校验失败'),
            ('unknown failure', '未提供可识别'),
        )
        for detail, expected in examples:
            with self.subTest(detail=detail):
                error = psycopg2.OperationalError(f'{detail}; password=DO-NOT-PRINT')
                message = bootstrap.database_error_reason(error)
                self.assertIn(expected, message)
                self.assertNotIn('DO-NOT-PRINT', message)

    def test_check_only_still_validates_vector_after_business_connection(self):
        environment = {
            'DEPLOYMENT_ENV': 'prod',
            'DATABASE_URL': 'postgresql://app:secret@db/business',
            'PGVECTOR_DB_URL': 'postgresql://app:secret@db/business',
            'WEBUI_SECRET_KEY': 'test-only',
            'VECTOR_DB': 'pgvector',
        }
        target, cursor = self.connection((1,))
        error = psycopg2.OperationalError('connection reset by peer')
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(bootstrap.psycopg2, 'connect', side_effect=[target, error]) as connect:
                with self.assertRaises(bootstrap.DatabaseBootstrapError) as raised:
                    bootstrap.main(['prod', '--check-only'])
        self.assertEqual(connect.call_count, 2)
        self.assertTrue(all(call.kwargs['dbname'] == 'business' for call in connect.call_args_list))
        cursor.execute.assert_called_once_with('SELECT 1')
        self.assertIn('pgvector', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
