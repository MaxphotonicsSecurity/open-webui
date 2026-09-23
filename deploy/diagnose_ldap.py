"""Check one AD application-account bind inside the running production container.

Uses environment defaults plus the existing PostgreSQL config rows, matching the
application's persistent configuration. Does not import the app, run migrations,
search users, or print credentials/raw server messages. Run via stdin with
``docker compose ... exec -T open-webui python - < deploy/diagnose_ldap.py``.
"""

import argparse
import json
import os
import re
import ssl
import sys
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def enabled(value):
    return str(value).lower() == 'true'


def database_error(exc, stage):
    """Classify locally; never print a driver message, SQL, or connection string."""
    message = str(exc).lower()
    sqlstate = getattr(exc, 'sqlstate', None) or getattr(exc, 'pgcode', None)
    if not isinstance(sqlstate, str) or not re.fullmatch(r'[A-Z0-9]{5}', sqlstate):
        sqlstate = None
    rules = [
        ('client_libpq_too_old', ('scram authentication requires libpq version',), ()),
        ('database_access_rule', ('no pg_hba.conf entry', 'pg_hba.conf rejects'), ()),
        ('database_password_missing', ('no password supplied',), ()),
        ('database_authentication_failed', ('password authentication failed', 'authentication failed'), ('28P01', '28000')),
        ('database_connection_limit', ('too many clients', 'remaining connection slots', 'max_client_conn'), ('53300',)),
        ('database_dns_failed', ('could not translate host name', 'name or service not known', 'temporary failure in name resolution'), ()),
        ('database_connection_refused', ('connection refused',), ()),
        ('database_timeout', ('timeout expired', 'connection timed out', 'statement timeout'), ('57014',)),
        ('database_tls_failed', ('ssl error', 'certificate verify failed', 'root certificate', 'does not support ssl', 'sslmode'), ()),
        ('database_connection_closed', ('server closed the connection', 'connection reset by peer', 'ssl syscall error'), ()),
        ('database_not_found', (), ('3D000',)),
        ('config_table_not_found', (), ('42P01',)),
        ('database_permission_denied', ('permission denied',), ('42501',)),
    ]
    category = 'database_error_unclassified'
    for name, fragments, codes in rules:
        if sqlstate in codes or any(fragment in message for fragment in fragments):
            category = name
            break
    if isinstance(exc, ValueError):
        category = 'database_configuration_invalid'
    return {'stage': stage, 'error_type': type(exc).__name__, 'category': category, 'sqlstate': sqlstate}


class ConfigReadError(Exception):
    def __init__(self, exc, stage):
        super().__init__('Configuration read failed')
        self.details = database_error(exc, stage)


def database_parameters(db_driver='psycopg'):
    """Mirror the app's DATABASE_* override and SSL URL normalization."""
    if db_driver == 'psycopg':
        from psycopg.conninfo import conninfo_to_dict as parse_dsn
    else:
        from psycopg2.extensions import parse_dsn

    url = os.getenv('DATABASE_URL', '')
    source = 'DATABASE_URL'
    credentials = os.getenv('DATABASE_USER', '')
    if os.getenv('DATABASE_PASSWORD'):
        credentials += ':' + os.environ['DATABASE_PASSWORD']
    parts = [os.getenv(name) for name in ('DATABASE_TYPE', 'DATABASE_HOST', 'DATABASE_PORT', 'DATABASE_NAME')]
    if all(parts) and credentials:
        db_type, host, port, name = parts
        url = f'{db_type}://{credentials}@{host}:{port}/{name}'
        source = 'DATABASE_TYPE/USER/PASSWORD/HOST/PORT/NAME'
    for scheme in ('postgresql+psycopg2://', 'postgresql+psycopg://'):
        if url.startswith(scheme):
            url = 'postgresql://' + url[len(scheme):]
    if not url.startswith(('postgresql://', 'postgres://')) or '${' in url:
        raise ValueError('A resolved production PostgreSQL URL is required')
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = query.pop('sslmode', [None])[0] or query.pop('ssl', [None])[0]
    query.pop('ssl', None)
    if sslmode:
        query['sslmode'] = [sslmode]
    params = parse_dsn(urlunparse(parsed._replace(query=urlencode(query, doseq=True))))
    params['connect_timeout'] = '10'
    return params, source


def database_summary(params, source, db_driver='psycopg'):
    if db_driver == 'psycopg':
        from psycopg import pq
        build_version, runtime_version = pq.__build_version__, pq.version()
    else:
        import psycopg2
        from psycopg2.extensions import libpq_version
        build_version, runtime_version = psycopg2.__libpq_version__, libpq_version()

    def safe_value(value):
        value = str(value)
        # Defense in depth: do not echo a password even if misused as a host/name.
        for secret in (params.get('password'), os.getenv('DATABASE_PASSWORD')):
            if secret:
                value = value.replace(secret, '[redacted]')
        return value[:160]

    return {
        'stage': 'database_connect',
        'driver': db_driver,
        'configuration_source': source,
        'host': safe_value(params.get('host', '(libpq default)')),
        'port': safe_value(params.get('port', '5432')),
        'database': safe_value(params.get('dbname', '(libpq default)')),
        'sslmode': safe_value(params.get('sslmode', '(libpq default)')),
        'password_configured': bool(params.get('password')),
        'libpq_build_version': build_version,
        'libpq_runtime_version': runtime_version,
    }


def load_config(db_driver='psycopg'):
    fields = {
        'enable': ('ENABLE_LDAP', 'false'),
        'server.host': ('LDAP_SERVER_HOST', 'localhost'),
        'server.port': ('LDAP_SERVER_PORT', '389'),
        'server.app_dn': ('LDAP_APP_DN', ''),
        'server.app_password': ('LDAP_APP_PASSWORD', ''),
        'server.use_tls': ('LDAP_USE_TLS', 'true'),
        'server.validate_cert': ('LDAP_VALIDATE_CERT', 'true'),
        'server.ca_cert_file': ('LDAP_CA_CERT_FILE', ''),
        'server.ciphers': ('LDAP_CIPHERS', 'ALL'),
    }
    config = {f'ldap.{key}': os.getenv(name, default) for key, (name, default) in fields.items()}
    if enabled(os.getenv('ENABLE_PERSISTENT_CONFIG', 'true')):
        if db_driver == 'psycopg':
            import psycopg as driver
            from psycopg import sql
        else:
            import psycopg2 as driver
            from psycopg2 import sql

        stage = 'database_configuration'
        connection = None
        try:
            params, source = database_parameters(db_driver)
            print(json.dumps(database_summary(params, source, db_driver), ensure_ascii=False), flush=True)
            stage = 'database_connect'
            connection = driver.connect(**params)
            stage = 'config_read'
            if db_driver == 'psycopg':
                connection.read_only = True
            else:
                connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                cursor.execute('SET LOCAL statement_timeout = 10000')
                cursor.execute(
                    sql.SQL('SELECT key, value FROM {}.config WHERE key = ANY(%s)').format(
                        sql.Identifier(os.getenv('DATABASE_SCHEMA') or 'public')
                    ),
                    (list(config),),
                )
                config.update(cursor.fetchall())
        except Exception as exc:
            raise ConfigReadError(exc, stage) from None
        finally:
            if connection is not None:
                connection.close()
    return config


def bind_summary(result):
    """Extract diagnostic codes only; a server message can include account data."""
    from ldap3.core.results import RESULT_CODES

    result = result or {}
    ad_code = re.search(r'\bdata\s+([0-9a-f]{1,8})\b', str(result.get('message', '')), re.I)
    code = result.get('result')
    code = code if type(code) is int else None
    return {
        'ldap_result': code,
        'description': RESULT_CODES.get(code),
        'ad_subcode': ad_code.group(1).lower() if ad_code else None,
    }


def check_bind(config):
    from ldap3 import ANONYMOUS, NONE, SIMPLE, Connection, Server, Tls

    if not enabled(config['ldap.enable']):
        print('LDAP 未启用；没有尝试绑定。')
        return 2
    dn = config['ldap.server.app_dn'] or ''
    password = config['ldap.server.app_password'] or ''
    if not dn or not password:
        print(json.dumps({'application_dn_configured': bool(dn), 'application_password_configured': bool(password)}))
        print('AD 应用账号或密码未配置；没有尝试匿名或空密码绑定。')
        return 2

    tls = Tls(
        validate=ssl.CERT_REQUIRED if enabled(config['ldap.server.validate_cert']) else ssl.CERT_NONE,
        version=ssl.PROTOCOL_TLS,
        ca_certs_file=config['ldap.server.ca_cert_file'] or None,
        ciphers=config['ldap.server.ciphers'] or 'ALL',
    )
    server = Server(
        config['ldap.server.host'],
        port=int(config['ldap.server.port']) if config['ldap.server.port'] else None,
        use_ssl=enabled(config['ldap.server.use_tls']),
        tls=tls,
        get_info=NONE,
        connect_timeout=10,
    )
    dn_format = 'DN' if '=' in dn else 'UPN' if '@' in dn else 'DOMAIN\\user' if '\\' in dn else 'short_name'
    print(json.dumps({
        'host': server.host,
        'port': server.port,
        'ldaps': server.ssl,
        'validate_cert': enabled(config['ldap.server.validate_cert']),
        'application_dn_format': dn_format,
        'application_dn_outer_whitespace': dn != dn.strip(),
        'application_password_configured': True,
        'application_password_outer_whitespace': password != password.strip(),
    }, ensure_ascii=False), flush=True)
    connection = Connection(
        server, dn, password,
        authentication=SIMPLE if dn else ANONYMOUS,
        auto_bind='NONE',
        auto_referrals=False,
        read_only=True,
        receive_timeout=10,
    )
    try:
        ok = connection.bind()  # Exactly one attempt; no user search or automatic retries.
        print(json.dumps({'bind_ok': ok, **bind_summary(connection.result)}, ensure_ascii=False))
        return 0 if ok else 1
    finally:
        try:
            connection.unbind()
        except Exception:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-only', action='store_true', help='Read effective configuration without any AD bind')
    parser.add_argument('--db-driver', choices=('psycopg', 'psycopg2'), default='psycopg',
                        help='Default: the application runtime driver; psycopg2 is available for comparison')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.db_driver)
    except ConfigReadError as exc:
        print(json.dumps(exc.details, ensure_ascii=False), file=sys.stderr)
        print('读取生效配置失败；尚未连接 AD。未输出密码、连接串或原始异常。', file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps(database_error(exc, 'database_configuration'), ensure_ascii=False), file=sys.stderr)
        return 2
    if args.config_only:
        print(json.dumps({'configuration_read_ok': True, 'ldap_enabled': enabled(config['ldap.enable']), 'ad_bind_attempted': False}))
        return 0
    try:
        return check_bind(config)
    except Exception as exc:
        print(f'LDAP 连接或 TLS 检查失败：{type(exc).__name__}（未输出原始异常或凭据）。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
