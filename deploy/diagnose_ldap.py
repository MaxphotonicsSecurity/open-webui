"""Check one AD application-account bind inside the running production container.

Uses environment defaults plus the existing PostgreSQL config rows, matching the
application's persistent configuration. Does not import the app, run migrations,
search users, or print credentials/raw server messages. Run via stdin with
``docker compose ... exec -T open-webui python - < deploy/diagnose_ldap.py``.
"""

import json
import os
import re
import ssl
import sys


def enabled(value):
    return str(value).lower() == 'true'


def load_config():
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
        import psycopg2
        from psycopg2 import sql

        url = os.getenv('DATABASE_URL', '')
        for scheme in ('postgresql+psycopg2://', 'postgresql+psycopg://'):
            if url.startswith(scheme):
                url = 'postgresql://' + url[len(scheme):]
        if not url.startswith(('postgresql://', 'postgres://')):
            raise ValueError('This diagnostic requires the production PostgreSQL configuration')
        connection = psycopg2.connect(url, connect_timeout=10)
        try:
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
        finally:
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


def main():
    try:
        config = load_config()
    except Exception as exc:
        print(f'读取生效配置失败：{type(exc).__name__}（未输出连接串或凭据）。', file=sys.stderr)
        return 2
    try:
        return check_bind(config)
    except Exception as exc:
        print(f'LDAP 连接或 TLS 检查失败：{type(exc).__name__}（未输出原始异常或凭据）。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
