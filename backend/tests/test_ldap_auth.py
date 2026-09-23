"""LDAP login regression tests using an in-memory directory and SQLite database.

Run with backend dependencies installed, a temporary DATA_DIR, and migrations disabled:
    WEBUI_SECRET_KEY=ldap-regression-test-secret-at-least-32-bytes \
        ENABLE_DB_MIGRATIONS=false VECTOR_DB=none PYTHONPATH=backend \
        python -m unittest discover -s backend/tests -p 'test_ldap_auth.py'
"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request, Response
from ldap3 import MOCK_SYNC, NONE, Connection, Server
from open_webui.internal.db import Base
from open_webui.models.auths import Auth, Auths, LdapForm
from open_webui.models.users import User, Users
from open_webui.routers import auths
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class LdapAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, tables=[User.__table__, Auth.__table__])
        sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = sessions()
        self.addAsyncCleanup(self.engine.dispose)
        self.addAsyncCleanup(self.db.close)
        database = patch('open_webui.internal.db.AsyncSessionLocal', sessions)
        database.start()
        self.addCleanup(database.stop)
        await Auths.insert_new_auth('admin@example.com', 'unused', 'Admin', role='admin', db=self.db)

        self.server = Server('ldap.test', get_info=NONE)
        self.app_dn = 'cn=service,dc=example,dc=com'
        self.user_dn = 'cn=Alice,ou=People,dc=example,dc=com'
        self.directory = Connection(self.server, client_strategy=MOCK_SYNC)
        self.directory.strategy.add_entry(self.app_dn, {'userPassword': 'app-password'})
        self.add_directory_user(self.user_dn, 'alice')
        self.return_empty_attributes = True
        self.config = {
            'ldap.enable': True,
            'ldap.server.host': 'ldap.test',
            'ldap.server.port': 389,
            'ldap.server.attribute_for_mail': 'mail',
            'ldap.server.attribute_for_username': 'sAMAccountName',
            'ldap.server.users_dn': 'dc=example,dc=com',
            'ldap.server.search_filter': '',
            'ldap.server.app_dn': self.app_dn,
            'ldap.server.app_password': 'app-password',
            'ldap.server.use_tls': False,
            'ldap.server.ca_cert_file': None,
            'ldap.server.attribute_for_groups': 'memberOf',
            'ui.default_user_role': 'user',
            'auth.jwt_expiry': '1h',
        }
        self.groups = AsyncMock()
        for target, kwargs in (
            ('Config.get', {'new': AsyncMock(side_effect=lambda key: self.config.get(key))}),
            ('Server', {'return_value': self.server}),
            ('Connection', {'side_effect': self.connect}),
            ('ENABLE_PASSWORD_AUTH', {'new': True}),
            ('get_permissions', {'new': AsyncMock(return_value={})}),
            ('publish_event', {'new': AsyncMock()}),
            ('apply_default_group_assignment', {'new': AsyncMock()}),
            ('Groups', {'new': self.groups}),
        ):
            patcher = patch(f'open_webui.routers.auths.{target}', **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_directory_user(self, dn, username, mail=None):
        attributes = {'cn': username, 'sAMAccountName': username, 'userPassword': 'correct-password'}
        if mail is not None:
            attributes['mail'] = mail
        self.directory.strategy.add_entry(dn, attributes)

    def connect(self, server, user, password, **kwargs):
        return Connection(
            self.server,
            user,
            password,
            client_strategy=MOCK_SYNC,
            return_empty_attributes=self.return_empty_attributes,
            **kwargs,
        )

    async def login(self, username='alice', password='correct-password'):
        response = Response()
        result = await auths.ldap_auth(
            Request({'type': 'http', 'headers': []}),
            response,
            LdapForm(user=username, password=password),
            db=self.db,
        )
        self.assertIn('token=', response.headers['set-cookie'])
        self.assertTrue(result['token'])
        return result

    async def test_missing_mail_creates_and_reuses_account(self):
        first = await self.login()
        second = await self.login('ALICE')
        self.assertEqual(first['id'], second['id'])
        self.assertTrue(first['email'].endswith('@ldap.invalid'))
        self.assertEqual(first['role'], 'user')
        self.assertEqual(await Users.get_num_users(db=self.db), 2)

    async def test_omitted_attribute_is_supported(self):
        self.return_empty_attributes = False
        result = await self.login()
        self.assertTrue(result['email'].endswith('@ldap.invalid'))

    async def test_empty_mail_values_are_supported(self):
        for mail in ([], [''], ['   ']):
            with self.subTest(mail=mail):
                self.directory.strategy.entries[self.user_dn]['mail'] = [value.encode() for value in mail]
                result = await self.login()
                self.assertTrue(result['email'].endswith('@ldap.invalid'))

    async def test_real_mail_is_normalized_and_existing_account_is_linked(self):
        existing = await Auths.insert_new_auth('alice@example.com', 'unused', 'Existing', db=self.db)
        self.directory.strategy.entries[self.user_dn]['mail'] = [b' Alice@Example.COM ']
        result = await self.login()
        self.assertEqual(result['id'], existing.id)
        self.assertEqual(result['email'], 'alice@example.com')
        del self.directory.strategy.entries[self.user_dn]['mail']
        self.assertEqual((await self.login())['id'], existing.id)

    async def test_multi_valued_mail_skips_empty_values(self):
        self.directory.strategy.entries[self.user_dn]['mail'] = [b'', b'Alice@Example.COM', b'other@example.com']
        result = await self.login()
        self.assertEqual(result['email'], 'alice@example.com')

    async def test_adding_mail_later_keeps_account_and_history_identity(self):
        first = await self.login()
        self.directory.strategy.entries[self.user_dn]['mail'] = [b'alice@example.com']
        second = await self.login()
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['email'], second['email'])
        self.assertEqual(await Users.get_num_users(db=self.db), 2)

    async def test_different_directory_users_get_distinct_accounts(self):
        self.add_directory_user('cn=Bob,ou=People,dc=example,dc=com', 'bob')
        alice, bob = await self.login(), await self.login('bob')
        self.assertNotEqual(alice['email'], bob['email'])
        self.assertNotEqual(alice['id'], bob['id'])

    async def test_bad_credentials_never_create_an_account(self):
        for username, password in (
            ('alice', ''),
            ('alice', '   '),
            ('alice', 'wrong'),
            ('missing', 'correct-password'),
        ):
            with self.subTest(username=username, password=password):
                with self.assertRaises(HTTPException):
                    await self.login(username, password)
        self.assertEqual(await Users.get_num_users(db=self.db), 1)

    async def test_disabled_account_remains_disabled(self):
        first = await self.login()
        await self.db.execute(update(Auth).where(Auth.id == first['id']).values(active=False))
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await self.login()

    async def test_placeholder_collision_cannot_take_over_unlinked_account(self):
        first = await self.login()
        await self.db.execute(update(User).where(User.id == first['id']).values(oauth=None))
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await self.login()

    async def test_shared_mail_cannot_take_over_another_ldap_account(self):
        self.directory.strategy.entries[self.user_dn]['mail'] = [b'shared@example.com']
        await self.login()
        self.add_directory_user('cn=Bob,dc=example,dc=com', 'bob', 'shared@example.com')
        with self.assertRaises(HTTPException):
            await self.login('bob')

    async def test_no_mail_user_still_gets_ldap_groups(self):
        self.config['ldap.group.enable_management'] = True
        self.config['ldap.group.enable_creation'] = True
        self.directory.strategy.entries[self.user_dn]['memberOf'] = [b'cn=Engineering,dc=example,dc=com']
        result = await self.login()
        self.groups.create_groups_by_group_names.assert_awaited_once_with(result['id'], ['Engineering'], db=self.db)
        self.groups.sync_groups_by_group_names.assert_awaited_once_with(result['id'], ['Engineering'], db=self.db)


if __name__ == '__main__':
    unittest.main()
