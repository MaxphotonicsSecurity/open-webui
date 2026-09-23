"""Database bootstrap executed via stdin inside the source-built application image.

No application modules are imported: this script does not run app migrations or
start workers. Compose supplies the environment, including expanded credentials.
"""

import argparse
import os
import sys
from contextlib import closing, contextmanager

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn


class DatabaseBootstrapError(RuntimeError):
    """A database failure safe to display without credentials or raw driver text."""


def database_error_reason(exc):
    # Inspect driver details for classification, but never print them: they may
    # contain a DSN, password, or authentication details supplied by the server.
    message = str(exc).lower()
    code = exc.pgcode
    code_reason = {
        '42501': '当前操作权限不足；请 DBA 核对建库或扩展权限。',
        '3D000': '目标数据库不存在；请核对数据库名或由 DBA 创建。',
    }.get(code)
    if code_reason:
        return code_reason
    if code == '28P01' or 'password authentication failed' in message:
        return '数据库密码认证失败；核对当前环境的数据库凭据。'
    if code == '28000' or 'no pg_hba.conf entry' in message:
        return '连接认证规则拒绝访问；请 DBA 核对来源地址、用户及 TLS 要求。'
    if code == '53300' or 'too many clients' in message or 'remaining connection slots' in message:
        return '数据库连接数已达上限；请检查连接池、连接代理和数据库连接额度。'
    if 'could not translate host name' in message or 'name or service not known' in message:
        return '数据库主机名解析失败；检查容器内 DNS 与数据库地址。'
    if 'connection refused' in message:
        return '数据库连接被拒绝；检查监听端口、连接代理及防火墙。'
    if 'timeout' in message or 'timed out' in message:
        return '数据库连接或操作超时；检查服务器到数据库的网络及连接代理状态。'
    if 'certificate verify failed' in message:
        return '数据库 TLS 证书校验失败；核对证书、主机名和 sslmode。'
    if any(value in message for value in ('connection reset', 'closed the connection', 'eof detected')):
        return '数据库或中间代理断开连接；检查数据库/代理日志及 TLS 配置。'
    return '驱动未提供可识别的错误原因；请结合本次失败阶段检查数据库及连接代理日志。'


@contextmanager
def database_connection(params, stage):
    print(f'[数据库] 正在执行：{stage}。', flush=True)
    try:
        with closing(psycopg2.connect(**params)) as connection:
            yield connection
    except psycopg2.Error as exc:
        raise DatabaseBootstrapError(
            f'{stage}失败（{type(exc).__name__}，SQLSTATE={exc.pgcode or "不可用"}）。{database_error_reason(exc)}'
        ) from None


def database_parameters(url):
    for scheme in ('postgresql+psycopg2://', 'postgresql+psycopg://'):
        if url.startswith(scheme):
            url = 'postgresql://' + url[len(scheme) :]
    if not url.startswith(('postgresql://', 'postgres://')):
        raise ValueError('DATABASE_URL / PGVECTOR_DB_URL 必须是 PostgreSQL URL。')
    try:
        params = parse_dsn(url)
    except psycopg2.Error:
        raise ValueError('PostgreSQL URL 无效，请检查格式和密码的 URL 编码。') from None
    if not all(params.get(key) for key in ('host', 'user', 'dbname')):
        raise ValueError('PostgreSQL URL 必须明确提供 host、user 和数据库名。')
    if params['dbname'] in ('postgres', 'template0', 'template1'):
        raise ValueError('应用必须使用独立业务数据库，不能使用 PostgreSQL 管理库或模板库。')
    params.setdefault('connect_timeout', '10')
    return params


def ensure_database(params, check_only=False, label='业务库 DATABASE_URL'):
    if not check_only:
        admin_params = dict(params, dbname='postgres')
        with database_connection(admin_params, f'{label} 的管理库 postgres 初始化检查') as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (params['dbname'],))
                if cursor.fetchone() is None:
                    cursor.execute(
                        sql.SQL('CREATE DATABASE {} OWNER {} TEMPLATE template0').format(
                            sql.Identifier(params['dbname']), sql.Identifier(params['user'])
                        )
                    )
                    print('[数据库] 已创建业务数据库。', flush=True)
                else:
                    print('[数据库] 业务数据库已存在，保留现有数据。', flush=True)
    with database_connection(params, f'{label} 的目标库连接验证') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    print(f'[数据库] {label} 连接验证通过。', flush=True)


def ensure_vector(params, check_only=False):
    with database_connection(params, 'pgvector 扩展连接与检查') as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT e.extversion, n.nspname FROM pg_extension e '
                "JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"
            )
            extension = cursor.fetchone()
            if extension is None:
                if check_only:
                    raise ValueError('目标向量数据库尚未启用 vector 扩展，请先由 DBA 初始化。')
                cursor.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
                if cursor.fetchone() is None:
                    raise ValueError('PostgreSQL 服务端未安装 pgvector，请先在服务端安装对应版本的扩展包。')
                cursor.execute('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
                print('[pgvector] 已启用 vector 扩展。', flush=True)
            elif extension[1] != 'public':
                raise ValueError('现有 vector 扩展不在 public schema，请先核对数据库布局。')
            else:
                print(f'[pgvector] vector {extension[0]} 已启用，保留现有数据。', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', choices=('local', 'test', 'prod'))
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    if os.getenv('DEPLOYMENT_ENV') != args.environment:
        raise ValueError('DEPLOYMENT_ENV 与所选环境不一致，请检查对应 .env。')
    for name in ('DATABASE_URL', 'WEBUI_SECRET_KEY', 'VECTOR_DB'):
        if not os.getenv(name) or 'CHANGE_ME' in os.environ[name] or '${' in os.environ[name]:
            raise ValueError(f'{name} 缺失、未填写或变量引用未展开。')
    if os.getenv('DATABASE_SCHEMA', 'public') != 'public':
        raise ValueError('当前一键初始化支持 public schema；自定义 schema 请先调整初始化流程。')
    if os.environ['VECTOR_DB'] != 'pgvector':
        raise ValueError('当前分环境部署脚本要求 VECTOR_DB=pgvector。')

    # Validate both URLs before making any database changes.
    business = database_parameters(os.environ['DATABASE_URL'])
    vector = database_parameters(os.getenv('PGVECTOR_DB_URL') or os.environ['DATABASE_URL'])
    ensure_database(business, check_only=args.check_only)
    if vector != business:
        print('[数据库] 向量库连接配置与业务库不同，将单独检查 PGVECTOR_DB_URL。', flush=True)
        ensure_database(vector, check_only=args.check_only, label='向量库 PGVECTOR_DB_URL')
    else:
        print('[数据库] 向量库与业务库使用相同连接配置。', flush=True)
    ensure_vector(vector, check_only=args.check_only)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, DatabaseBootstrapError) as exc:
        print(f'[错误] {exc}', file=sys.stderr)
        sys.exit(1)
    except psycopg2.Error as exc:
        # Driver error strings can include connection information. Do not dump
        # the exception or a traceback with credentials into deployment logs.
        print(
            f'[错误] PostgreSQL 操作失败（{type(exc).__name__}，SQLSTATE={exc.pgcode or "不可用"}）。'
            f'{database_error_reason(exc)}',
            file=sys.stderr,
        )
        sys.exit(1)
