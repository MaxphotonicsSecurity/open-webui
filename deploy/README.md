# Open WebUI 企业部署说明

`deploy` 按环境拆分部署文件。local、test、prod 各自拥有独立的环境配置和 Docker Compose 文件，修改某个环境时不会影响其他环境。

## 一键部署（推荐）

各环境的 deploy 目录提供部署入口；以下命令在仓库根目录执行，先确认对应 `deploy/<环境>/.env` 已填写：

```bash
bash deploy/local/deploy.sh  # 本地环境
bash deploy/test/deploy.sh   # 测试环境
bash deploy/prod/deploy.sh   # 生产环境
```

每次选择一个环境执行。脚本按自身位置定位仓库，因此也可以从其他目录运行，例如 `bash /opt/max/deploy/prod/deploy.sh`（替换为实际仓库路径），无需依赖当前目录。各环境 `.env` 允许随代码提交上传；需要同步包含对应 `.env` 的完整仓库，不能只复制入口脚本。

默认依次执行：检查 Docker/Compose 与配置 → 从源码构建应用镜像 → 用镜像中的 PostgreSQL 驱动创建缺失的业务库和 pgvector 扩展 → 预热模型缓存并启动应用 → 等待容器健康。无需宿主机 `psql`、Python，也无需手动挂载 SQL 文件或重复输入数据库密码。若数据库或扩展已经存在，会保留它们；应用启动仍会正常执行自身的数据库迁移。

统一入口和可选参数：

```bash
bash deploy/deploy.sh prod --check                    # 仅检查本地配置，不访问数据库或启动容器
bash deploy/deploy.sh test --no-build                 # 使用本环境已有的应用镜像
bash deploy/deploy.sh prod --skip-db-init             # 库和扩展已由 DBA 初始化，仅检查连接与扩展
bash deploy/deploy.sh prod --no-build --skip-db-init --wait-timeout 600
```

三个环境入口也支持上述参数，例如 `bash deploy/prod/deploy.sh --check`。脚本要求 `.env` 已存在，发现 `CHANGE_ME` 或示例公司域名时会报告变量名并停止，不会覆盖现有凭据或自动猜测缺失值。`--check` 只检查配置文件和 Compose 解析结果，不能代替远端服务连通性及业务验收。

初始化使用 `.env` 内的数据库账号，需要能连接 `postgres` 管理库，并在目标库缺失时拥有 `CREATEDB` 权限；新启用 `vector` 时需要相应扩展权限且服务端已安装 pgvector。已由 DBA 初始化的环境可使用 `--skip-db-init`。业务库和向量库地址均从配置读取，当前脚本支持 PostgreSQL + pgvector、`public` schema。

项目名固定为 `open-webui-local`、`open-webui-test`、`open-webui-prod`，与当前模板一致；不会因为调用者 shell 中另一个 `COMPOSE_PROJECT_NAME` 或 `OPEN_WEBUI_ENV_FILE` 而切到其他环境。多环境同机运行仍需配置不同的端口和网段。

构建、初始化或健康检查失败会立即返回非零退出码；脚本不执行 `down` 或删除数据卷。DNS、HTTPS 证书、反向代理及公司模型服务接入仍按环境说明配置。以下章节保留手动初始化与运维命令；使用一键脚本时无需重复手动建库。

## 目录结构

```text
deploy/
├── deploy.sh                 # 共享部署流程
├── bootstrap.py              # 应用镜像内执行的数据库初始化程序
├── local/
│   ├── .env
│   ├── .env.example
│   ├── deploy.sh
│   └── docker-compose.yaml
├── test/
│   ├── .env
│   ├── .env.example
│   ├── deploy.sh
│   └── docker-compose.yaml
├── prod/
│   ├── .env
│   ├── .env.example
│   ├── deploy.sh
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

Dockerfile 使用 BuildKit 自带解析器，无需额外拉取 `docker/dockerfile:1`。遇到镜像仓库连接重置时，参见 [构建网络排障与镜像导入部署](prod/README.md#构建时-docker-hub-连接被重置)。

企业 Compose 不再默认启动 Ollama。后续可以在管理界面接入公司内部模型服务；如需本地 Ollama，请单独部署并配置 `OLLAMA_BASE_URL`。

## 1. 初始化环境文件

在仓库根目录执行：

```bash
# 已随仓库同步的配置直接使用，仅在文件不存在时复制模板。
test -f deploy/local/.env || cp deploy/local/.env.example deploy/local/.env
test -f deploy/test/.env || cp deploy/test/.env.example deploy/test/.env
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

按项目要求，`deploy/local/.env`、`deploy/test/.env`、`deploy/prod/.env` 已从 Git 忽略规则中放行，允许包含实际凭据并随代码提交上传。提交这三个文件后，服务器拉取仓库即可获得环境配置，无需单独传输。Docker 构建仍排除它们；Compose 在部署时读取配置，一键部署脚本会将文件权限设置为 `600`。不要用 `.env.example` 覆盖已有配置。

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
bash deploy/local/deploy.sh
```

### test

```bash
bash deploy/test/deploy.sh
```

### prod

按 [生产部署说明](prod/README.md) 准备配置，脚本会自动初始化 `openwebui` 数据库及 `vector` 扩展：

```bash
bash deploy/prod/deploy.sh
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
