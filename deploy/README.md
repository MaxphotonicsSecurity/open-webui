# Open WebUI 企业部署说明

`deploy` 按环境拆分部署文件。local、test、prod 各自拥有独立的环境配置和 Docker Compose 文件，修改某个环境时不会影响其他环境。

## 目录结构

```text
deploy/
├── local/
│   ├── .env.example
│   └── docker-compose.yaml
├── test/
│   ├── .env.example
│   └── docker-compose.yaml
├── prod/
│   ├── .env.example
│   └── docker-compose.yaml
└── README.md
```

每套环境配置都包含：

- PostgreSQL：业务数据持久化；
- Redis：缓存、WebSocket 和多实例协同；
- S3 兼容 OSS：用户上传文件和知识库文件存储；
- 向量数据库：local、test、prod 均使用 pgvector；prod 的 Redis 使用 Sentinel。

生产环境的实际配置、数据库初始化、HTTPS 入口和验收步骤见 [prod/README.md](prod/README.md)。

企业部署 Compose 会使用当前仓库根目录的 `Dockerfile` 和源代码构建 `company/open-webui` 镜像，并设置 `pull_policy: build`，不会拉取 `ghcr.io/open-webui/open-webui` 成品镜像。Node、Python 基础镜像以及 apt、npm、pip 依赖在首次源码构建时仍需下载。

企业 Compose 不再默认启动 Ollama。后续可以在管理界面接入公司内部模型服务；如需本地 Ollama，请单独部署并配置 `OLLAMA_BASE_URL`。

## 1. 初始化环境文件

在仓库根目录执行：

```bash
cp deploy/local/.env.example deploy/local/.env
cp deploy/test/.env.example deploy/test/.env
# 仅当生产环境文件不存在时才复制模板，避免覆盖已有凭据。
test -f deploy/prod/.env || cp deploy/prod/.env.example deploy/prod/.env
```

按环境修改相应 `.env`：

1. 替换所有 `CHANGE_ME`；
2. 替换 `*.company.internal`、`*.company.example` 示例域名；
3. 确认 PostgreSQL 数据库名、TLS 和连接池参数；
4. 确认 Redis DB、TLS、集群模式和 key 前缀；
5. 确认 OSS endpoint、region、bucket 和 key 前缀；
6. 确认向量数据库地址、认证信息和 collection 前缀；
7. 为每个环境生成不同的 `WEBUI_SECRET_KEY`。

三个目录中的私有 `.env` 均已被 `.gitignore` 排除。禁止提交真实密码、Access Key 或 API Key；生产环境建议由公司密钥管理系统或 CI/CD 平台动态生成 `.env`。

连接 URL 中的用户名或密码如果包含 `@`、`:`、`/`、`#`、`?` 等保留字符，需要先进行 URL 编码。

### local/test PostgreSQL 初始化

Open WebUI 不在 `litellm` 数据库中创建业务 schema。local 使用独立的 `openwebui` 数据库，test 使用独立的 `openwebui_test` 数据库，两者均使用各自数据库中的 `public` schema。

首次部署前，请连接 PostgreSQL 管理数据库并使用有 `CREATEDB` 权限的账号执行：

```sql
CREATE DATABASE openwebui OWNER litellm TEMPLATE template0;
CREATE DATABASE openwebui_test OWNER litellm TEMPLATE template0;
```

随后分别连接两个新数据库并启用 pgvector：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

`TEMPLATE template0` 可以避开部分 PostgreSQL 服务器上 `template1` 排序规则版本不一致的问题。数据库名发生变化时，必须同时修改目标环境 `.env` 中的 `DATABASE_URL` 和 `PGVECTOR_DB_URL`。

默认关闭嵌入、重排和 Whisper 模型的运行时自动更新。源码镜像构建会准备默认模型缓存，Compose 中的 `model-cache-init` 一次性服务会使用同一个本地镜像将缓存预热到持久卷，并生成稳定的本地嵌入模型目录；它设置了 `pull_policy: never`，不会从镜像仓库拉取应用镜像。需要升级模型时，在受控构建流程中刷新缓存后再发布镜像。

### local/test Redis 说明

local 和 test 当前直接连接 Redis master `172.22.11.122:6379`，账号密码配置在 `REDIS_URL` 中。两套环境通过不同的 `REDIS_KEY_PREFIX` 隔离数据。

Sentinel 当前未启用，因为 `172.22.11.122:26379` 从开发环境连接时返回 `Connection refused`。待 Sentinel 服务恢复后，可重新增加 `REDIS_SENTINEL_HOSTS` 配置。AOF 持久化属于 Redis 服务端配置，无需写入 Open WebUI 客户端环境变量。

## 2. 部署环境

以下命令均在仓库根目录执行。

### local

```bash
docker compose \
  --env-file deploy/local/.env \
  -f deploy/local/docker-compose.yaml \
  up -d --build
```

### test

```bash
docker compose \
  --env-file deploy/test/.env \
  -f deploy/test/docker-compose.yaml \
  up -d --build
```

### prod

先按 [生产部署说明](prod/README.md) 初始化 `openwebui` 数据库和 `vector` 扩展，再构建启动：

```bash
docker compose \
  --env-file deploy/prod/.env \
  -f deploy/prod/docker-compose.yaml \
  build open-webui

docker compose \
  --env-file deploy/prod/.env \
  -f deploy/prod/docker-compose.yaml \
  up -d --no-build --pull never --wait --wait-timeout 300
```

每个 `.env` 都设置了独立的 `COMPOSE_PROJECT_NAME`，Docker 网络和数据卷会按环境隔离。Compose 默认将项目网络固定为 `192.168.30.0/24`，可通过 `.env` 中的 `OPEN_WEBUI_SUBNET` 覆盖，避免 Docker 自动分配的网段与办公网冲突。如果多个环境部署在同一台主机上，必须为各环境设置互不重叠且不与办公网冲突的 `OPEN_WEBUI_SUBNET`，并给 `OPEN_WEBUI_PORT` 设置不同端口。

已有网络修改网段后，需要先执行对应环境的 `docker compose ... down`（不要加 `-v`，保留数据卷），再执行 `up`，仅 `restart` 不会重建网络。本地已有镜像和模型缓存时，可使用以下命令应用网络配置：

```bash
docker compose --env-file deploy/local/.env -f deploy/local/docker-compose.yaml down
docker compose --env-file deploy/local/.env -f deploy/local/docker-compose.yaml \
  up -d --no-deps --no-build --pull never --wait --wait-timeout 180 open-webui
```

## 3. 常用运维命令

以下以 test 环境为例；切换环境时，同时替换命令中的两个 `deploy/test` 路径。

查看服务状态：

```bash
docker compose --env-file deploy/test/.env -f deploy/test/docker-compose.yaml ps
```

查看 Open WebUI 日志：

```bash
docker compose --env-file deploy/test/.env -f deploy/test/docker-compose.yaml logs -f open-webui
```

重启服务：

```bash
docker compose --env-file deploy/test/.env -f deploy/test/docker-compose.yaml restart
```

停止并删除容器和网络，但保留数据卷：

```bash
docker compose --env-file deploy/test/.env -f deploy/test/docker-compose.yaml down
```

升级并重新构建：

```bash
docker compose --env-file deploy/test/.env -f deploy/test/docker-compose.yaml up -d --build
```

不要在生产环境执行 `docker compose down -v`，该命令会删除持久化数据卷。

## 4. 本地直接运行后端

不使用 Docker 时，可以加载 local 环境文件后启动：

```bash
set -a
source deploy/local/.env
set +a
cd backend
./dev.sh
```

Open WebUI 内部只识别 `ENV=dev`、`ENV=test`、`ENV=prod`，因此 local 配置使用 `ENV=dev`，并通过 `DEPLOYMENT_ENV=local` 标识企业部署环境。

## 5. 向量数据库配置

local、test 和 prod 默认启用 pgvector：

```dotenv
VECTOR_DB=pgvector
PGVECTOR_DB_URL=postgresql://user:password@postgres:5432/database
PGVECTOR_INDEX_METHOD=hnsw
```

向量表与 Open WebUI 业务表位于同一个环境专用数据库的 `public` schema。`PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH` 应按实际 embedding 模型输出维度设置；local/test 模板保留 `1536`，prod 配合 `all-MiniLM-L6-v2` 使用 `384`。已有向量表变更维度前需要安排迁移和知识库重建。

生产环境使用 pgvector 时，建议由 DBA 预先安装 `vector` 扩展，并设置 `PGVECTOR_CREATE_EXTENSION=false`，避免应用账号拥有扩展管理权限。如需切换 Milvus，请注释 pgvector 配置，并取消目标环境模板中的 Milvus 配置块；同一环境只能保留一个生效的 `VECTOR_DB`。

## 6. 上线前检查

- local、test、prod 使用不同的数据库、Redis 前缀、OSS bucket/prefix 和向量 collection 前缀；
- 核实 PostgreSQL 与 Redis 的实际 TLS 能力及连接策略；当前 prod PostgreSQL 使用 `sslmode=prefer`，Redis Sentinel 使用内网 TCP；
- 生产环境的 `CORS_ALLOW_ORIGIN` 只包含正式域名；
- `WEBUI_SECRET_KEY` 足够长且各环境不同；
- 容器能够访问 PostgreSQL、Redis、OSS 和向量数据库；
- 已配置数据库、OSS 和向量数据的备份与恢复策略；
- 已根据 `UVICORN_WORKERS` 和 PostgreSQL 最大连接数调整连接池；
- 反向代理已启用 HTTPS，并正确转发 WebSocket。
