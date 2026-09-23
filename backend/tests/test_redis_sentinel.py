"""Sentinel authentication regression tests; no network connections are opened.

Run with the backend dependencies installed:
    WEBUI_SECRET_KEY=sentinel-test-only PYTHONPATH=backend \
        python -m unittest discover -s backend/tests -p 'test_redis_sentinel.py'
"""

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from open_webui.utils import redis as redis_utils


class RedisSentinelCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.multiple(
            redis_utils,
            REDIS_SENTINEL_PASSWORD='sentinel-secret',
            REDIS_SOCKET_CONNECT_TIMEOUT=5,
            REDIS_SOCKET_TIMEOUT=10,
            REDIS_SOCKET_KEEPALIVE=True,
            _CONNECTION_POOL={},
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_sync_and_async_clients_use_separate_credentials(self):
        for async_mode in (False, True):
            with self.subTest(async_mode=async_mode):
                proxy = redis_utils.get_redis_connection(
                    'redis://:data-secret@aigwmaster:6379/2',
                    redis_sentinels=[('sentinel-one', 26379), ('sentinel-two', 26379)],
                    async_mode=async_mode,
                )
                master = proxy._resolve_master()
                self.assertEqual(master.connection_pool.connection_kwargs['password'], 'data-secret')
                self.assertEqual(master.connection_pool.connection_kwargs['db'], 2)
                self.assertEqual(master.connection_pool.service_name, 'aigwmaster')
                for sentinel in proxy._sentinel.sentinels:
                    options = sentinel.connection_pool.connection_kwargs
                    self.assertEqual(options['password'], 'sentinel-secret')
                    self.assertEqual(options['socket_connect_timeout'], 5)
                    self.assertEqual(options['socket_timeout'], 10)
                    self.assertTrue(options['socket_keepalive'])

    def test_sentinel_without_auth_does_not_inherit_data_password(self):
        with patch.object(redis_utils, 'REDIS_SENTINEL_PASSWORD', ''):
            proxy = redis_utils.get_redis_connection(
                'redis://:data-secret@aigwmaster/0', redis_sentinels=[('sentinel', 26379)]
            )
        options = proxy._sentinel.sentinels[0].connection_pool.connection_kwargs
        self.assertIsNone(options.get('password'))
        self.assertEqual(options['socket_timeout'], 10)
        self.assertEqual(proxy._resolve_master().connection_pool.connection_kwargs['password'], 'data-secret')

    def test_standalone_redis_retains_its_own_password(self):
        client = redis_utils.get_redis_connection('redis://:standalone-secret@localhost/3')
        self.assertEqual(client.connection_pool.connection_kwargs['password'], 'standalone-secret')
        self.assertEqual(client.connection_pool.connection_kwargs['db'], 3)


class WebsocketSentinelSettingsTests(unittest.TestCase):
    def read_settings(self, **overrides):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(('REDIS_', 'WEBSOCKET_', 'SENTINEL_'))
        }
        env.update(overrides)
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'import json; from open_webui import env; '
                'print(json.dumps([env.REDIS_SENTINEL_PASSWORD, env.WEBSOCKET_REDIS_OPTIONS]))',
            ],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_password_alias_reaches_socketio_sentinel_client(self):
        password, options = self.read_settings(
            SENTINEL_PASSWORD='sentinel-secret',
            WEBSOCKET_SENTINEL_HOSTS='sentinel',
            REDIS_SOCKET_CONNECT_TIMEOUT='5',
            REDIS_SOCKET_TIMEOUT='10',
        )
        self.assertEqual(password, 'sentinel-secret')
        self.assertIsNone(options['socket_timeout'])  # Pub/Sub must remain blocking.
        from socketio import AsyncRedisManager

        manager = AsyncRedisManager(
            'redis+sentinel://:data-secret@sentinel:26379/0/aigwmaster', redis_options=options
        )
        manager._redis_connect()
        master_options = manager.redis.connection_pool.connection_kwargs
        self.assertEqual(master_options['password'], 'data-secret')
        self.assertIsNone(master_options['socket_timeout'])
        sentinel = manager.redis.connection_pool.sentinel_manager.sentinels[0]
        sentinel_options = sentinel.connection_pool.connection_kwargs
        self.assertEqual(sentinel_options['password'], 'sentinel-secret')
        self.assertEqual(sentinel_options['socket_connect_timeout'], 5)
        self.assertEqual(sentinel_options['socket_timeout'], 10)

    def test_explicit_settings_override_alias_and_socketio_defaults(self):
        password, options = self.read_settings(
            SENTINEL_PASSWORD='alias-secret',
            REDIS_SENTINEL_PASSWORD='explicit-secret',
            WEBSOCKET_SENTINEL_HOSTS='sentinel',
            REDIS_SOCKET_TIMEOUT='10',
            WEBSOCKET_REDIS_OPTIONS=json.dumps(
                {'sentinel_kwargs': {'password': 'websocket-secret', 'socket_timeout': 7}}
            ),
        )
        self.assertEqual(password, 'explicit-secret')
        self.assertEqual(options['sentinel_kwargs']['password'], 'websocket-secret')
        self.assertEqual(options['sentinel_kwargs']['socket_timeout'], 7)

    def test_standalone_websocket_does_not_get_sentinel_options(self):
        _, options = self.read_settings(SENTINEL_PASSWORD='sentinel-secret')
        self.assertNotIn('sentinel_kwargs', options)

    def test_unauthenticated_websocket_sentinel_remains_supported(self):
        password, options = self.read_settings(WEBSOCKET_SENTINEL_HOSTS='sentinel')
        self.assertEqual(password, '')
        self.assertNotIn('sentinel_kwargs', options)


if __name__ == '__main__':
    unittest.main()
