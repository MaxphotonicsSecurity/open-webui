"""Read-only PostgreSQL protocol and driver checks, runnable via container stdin.

No application imports, migrations, DDL, or retries. Preserve the configured TLS
policy and never print credentials, connection strings, or raw driver errors.
"""

import importlib
import json
import os
import re
import socket
import struct
import time


def emit(**record):
    print(json.dumps(record, ensure_ascii=False), flush=True)


def connection_parameters():
    from psycopg2.extensions import parse_dsn

    url = os.environ['DATABASE_URL']
    for prefix in ('postgresql+psycopg2://', 'postgresql+psycopg://'):
        if url.startswith(prefix):
            url = 'postgresql://' + url[len(prefix) :]
    if not url.startswith(('postgresql://', 'postgres://')) or '${' in url:
        raise ValueError('A resolved PostgreSQL URL is required')
    params = parse_dsn(url)
    if not params.get('host') or not params.get('dbname'):
        raise ValueError('An explicit host and database are required')
    params['connect_timeout'] = '8'
    params['options'] = (
        params.get('options', '') + ' -c statement_timeout=5000 -c default_transaction_read_only=on'
    ).strip()
    return params


def failure(exc):
    message = str(exc).lower()
    code = getattr(exc, 'sqlstate', None) or getattr(exc, 'pgcode', None)
    if not isinstance(code, str) or not re.fullmatch(r'[A-Z0-9]{5}', code):
        code = None
    rules = (
        ('timeout', ('timeout', 'timed out'), ('57014',)),
        (
            'authentication',
            ('password authentication failed', 'no password supplied', 'no pg_hba.conf entry'),
            ('28P01', '28000'),
        ),
        ('connection_limit', ('too many clients', 'remaining connection slots'), ('53300',)),
        ('client_libpq_too_old', ('scram authentication requires libpq version',), ()),
        ('tls', ('ssl', 'certificate'), ()),
        ('gssapi', ('gssapi', 'gssenc', 'kerberos'), ()),
        ('connection_closed', ('connection reset', 'closed the connection', 'eof'), ()),
        ('connection_refused', ('connection refused',), ()),
        ('dns', ('could not translate host name', 'name or service not known'), ()),
        ('database_not_found', (), ('3D000',)),
        ('permission', ('permission denied',), ('42501',)),
    )
    category = next(
        (name for name, fragments, codes in rules if code in codes or any(value in message for value in fragments)),
        'unclassified',
    )
    return {'error_type': type(exc).__name__, 'category': category, 'sqlstate': code}


def probe_protocol(params):
    # SSLRequest carries no username or password. 'S' and 'N' are both valid
    # PostgreSQL responses; neither proves a TLS handshake or login succeeded.
    host = params.get('hostaddr') or params['host']
    if ',' in host or host.startswith('/'):
        emit(stage='postgres_ssl_response', status='skipped_multi_host_or_unix_socket')
        return
    started = time.monotonic()
    stage = 'tcp_connect'
    try:
        with socket.create_connection((host, int(params.get('port', '5432'))), timeout=5) as connection:
            stage = 'postgres_ssl_response'
            connection.settimeout(5)
            connection.sendall(struct.pack('!II', 8, 80877103))
            response = connection.recv(1)
            status = {b'S': 'tls_supported', b'N': 'tls_not_supported', b'': 'connection_closed'}.get(
                response, 'unexpected_response'
            )
            emit(stage=stage, status=status, elapsed_seconds=round(time.monotonic() - started, 2))
    except Exception as exc:
        emit(stage=stage, status='failed', elapsed_seconds=round(time.monotonic() - started, 2), **failure(exc))


def probe_driver(name, params):
    started = time.monotonic()
    stage = 'driver_import'
    connection = None
    try:
        driver = importlib.import_module(name)
        libpq = driver.pq.version() if name == 'psycopg' else driver.extensions.libpq_version()
        emit(stage='driver_version', driver=name, version=driver.__version__, libpq=libpq)
        stage = 'database_connect'
        emit(stage=stage, driver=name, status='starting', sslmode=params.get('sslmode', 'prefer'), timeout_seconds=8)
        connection = driver.connect(**params)
        emit(stage=stage, driver=name, status='ok', elapsed_seconds=round(time.monotonic() - started, 2))
        stage = 'read_only_query'
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            if cursor.fetchone() != (1,):
                raise ValueError('Unexpected SELECT result')
        emit(stage=stage, driver=name, status='ok', elapsed_seconds=round(time.monotonic() - started, 2))
        return True
    except Exception as exc:
        emit(
            stage=stage,
            driver=name,
            status='failed',
            elapsed_seconds=round(time.monotonic() - started, 2),
            **failure(exc),
        )
        return False
    finally:
        if connection is not None:
            connection.close()


def main():
    try:
        params = connection_parameters()
    except Exception as exc:
        emit(stage='configuration', status='failed', **failure(exc))
        return 1
    probe_protocol(params)
    results = [probe_driver(name, params) for name in ('psycopg2', 'psycopg')]
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
