# 生产环境部署

在仓库根目录执行本文命令。生产配置位于 `deploy/prod/.env`，真实密码已填写，允许随代码提交上传。提交后，服务器拉取仓库即可获得配置，无需单独传输 `.env`。Docker 构建仍排除该文件，Compose 在部署时读取，一键脚本会将文件权限设置为 `600`。`.env.example` 保留相同配置结构，密码使用占位符；不要用模板覆盖已填写的文件。

## 已运行实例的生产发布

应用已部署在 `172.22.11.124:3000`，正式入口为 `https://chatbot.maxphotonics.com`。2026-09-23 从本机检查正式域名，证书验证和 `/health` 请求通过（200），标准 HTTP/1.1 WebSocket 握手返回 101。该结果不替代登录、长连接稳定性、模型对话和知识库验收。

1. 先确认生产数据库、OSS 和应用持久卷有可恢复的备份。发布源码时，先在本地提交并推送本次要发布的改动，再在服务器仓库根目录执行 `git pull --ff-only`；本地未提交的改动不会被服务器拉取。保留服务器已有模型缓存和环境凭据。
2. 核对服务器 `deploy/prod/.env`：`CORS_ALLOW_ORIGIN='https://chatbot.maxphotonics.com'`，`WEBUI_SESSION_COOKIE_SECURE=true`，`WEBUI_AUTH_COOKIE_SECURE=true`。保留原来的 `WEBUI_SECRET_KEY`、数据库和存储连接信息。执行 `bash deploy/prod/deploy.sh --check`。
3. 按本次发布内容选择下面的一种方式。

**仅修改访问入口或环境变量，沿用现有镜像：**

```bash
docker compose --project-name open-webui-prod \
  --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  up -d --no-deps --no-build --pull never --force-recreate \
  --wait --wait-timeout 300 open-webui
```

**包含源码修改（例如 LDAP 登录代码）：**

```bash
test -f deploy/offline-models/manifest.json && \
bash deploy/prod/deploy.sh --skip-db-init --wait-timeout 600
```

先确认 `test` 检查成功再执行部署。当前服务器无法正常下载 Hugging Face 模型，缓存缺失时先按 [离线模型包](../OFFLINE_MODELS.md) 上传并解压。`--skip-db-init` 适用于当前已初始化的数据库和 pgvector；仍会验证连接，并正常执行应用自身迁移。源码发布必须重建镜像，不能用 `--no-build` 来应用 Python 或前端源码修改。

更新容器会造成短暂中断。部署后统一从 HTTPS 域名重新登录，按第 5 节验收。AD 应用账号绑定失败和模型服务不可达需要分别修复；`healthy` 不代表这两项已通过。

## 一键入口

同步完整仓库及生产 `.env` 后，在仓库根目录执行：

```bash
bash deploy/prod/deploy.sh
```

也可以从任意目录调用脚本的绝对路径，例如 `bash /opt/max/deploy/prod/deploy.sh`（将 `/opt/max` 替换为实际仓库目录）。脚本自动定位环境文件，依次校验配置、构建镜像、初始化数据库和 pgvector、启动应用并等待健康检查。数据库初始化使用应用镜像内的驱动，因此无需宿主机新版 `psql`，也无需挂载 `init-db.sql`，可避免之前的 SCRAM 客户端版本和相对路径错误。

```bash
bash deploy/prod/deploy.sh --check         # 只检查配置，不部署
bash deploy/prod/deploy.sh --no-build      # 已有当前源码构建的生产镜像时复用
bash deploy/prod/deploy.sh --skip-db-init  # 数据库及扩展已经由 DBA 初始化时使用
```

默认初始化会创建缺失的 `openwebui` 库和 `vector` 扩展，已有库及扩展会保留。`--skip-db-init` 仍会检查数据库连接及扩展，但不会执行初始化 DDL；应用启动后的正常迁移照常进行。凭据从 `.env` 自动读取。其余选项见 [分环境部署入口说明](../README.md)。以下手动步骤用于核对或排障，使用脚本时无需重复执行建库及构建启动命令。

## 1. 本次配置

| 项目 | 配置 |
| --- | --- |
| 正式站点 | `https://chatbot.maxphotonics.com`，已有 HTTPS 代理入口 |
| 后端入口 | `http://172.22.11.124:3000`，供反向代理转发 |
| PostgreSQL | `172.16.60.190:5000`，用户 `postgres`，数据库 `openwebui`，schema `public` |
| Sentinel | `172.16.60.185:26379`、`172.16.60.186:26379`、`172.16.60.187:26379` |
| Sentinel master name | `aigwmaster` |
| Redis | DB `0`，key 前缀 `open-webui:prod`，Sentinel 模式，`REDIS_CLUSTER=false` |
| OSS | `https://fs.maxphotonics.com:9443`，桶 `chatbot`，对象前缀 `open-webui/prod/` |
| S3 协议 | Signature V4，`S3_ADDRESSING_STYLE=auto`，签名 region `us-east-1` |
| 向量库 | 同一 PostgreSQL 数据库中的 pgvector，HNSW 索引 |
| 嵌入模型 | 镜像缓存的 `all-MiniLM-L6-v2`，向量维度 `384` |
| 容器入口 | 宿主机端口 `3000` → 容器端口 `8080` |

`REDIS_URL` 中的主机名是 Sentinel 的逻辑主节点名 `aigwmaster`，不是 Sentinel IP，也不固定为当前 Redis master IP。Sentinel 负责返回实际数据节点地址及端口。`REDIS_PASSWORD` 用于数据节点；`SENTINEL_PASSWORD` 通过 `REDIS_SENTINEL_PASSWORD` 单独用于 Sentinel 认证。WebSocket 同样配置 Sentinel，后端代码已补齐两条连接路径的独立认证支持，必须重新构建包含本次修改的源码镜像。

PostgreSQL 密码中的 `/` 已编码为 `%2F`。`PGVECTOR_DB_URL` 引用 `DATABASE_URL`，避免业务库和向量库配置漂移。配置使用 Docker Compose / python-dotenv 支持的变量引用；不要改用不会展开这些引用的 `docker run --env-file` 直接启动应用。

2026-09-23 从本机临时容器进行的只读检查结果：三个 Sentinel 均返回 `aigwmaster`，应用同步/异步 Redis 客户端均可 PING，Socket.IO 的 Sentinel 连接及 Pub/Sub PING/PONG 通过；OSS `HEAD Bucket` 返回 `200`，客户端使用 `s3v4`；PostgreSQL 服务端可用 pgvector 版本为 `0.8.6`，但 `openwebui` 库尚不存在。检查时 PostgreSQL 连接未使用 TLS，所以当前配置为 `sslmode=prefer`。若 DBA 后续启用 TLS，应按证书配置改成 `require` 或带可信 CA 的 `verify-full`。这些结果不替代生产宿主机自身的网络验收。

## 2. 准备服务器与数据库

安装 Docker Engine、Docker Compose v2.24+（或 v5）。手动初始化数据库时可以使用下方 Docker 客户端命令；一键脚本自动使用应用镜像内的驱动。若使用宿主机 `psql`，其实际加载的 `libpq` 必须为 10 或更高版本，以支持 SCRAM 认证。服务器需要能访问：

- PostgreSQL `172.16.60.190:5000`；
- 三个 Sentinel 的 `26379` 端口，以及 Sentinel 返回的 Redis 数据节点端口（本次为 `6379`）；所有可能晋升为 master 的节点均须可达；
- OSS HTTPS `9443` 端口；
- 首次源码构建所需的镜像仓库、npm、pip 及模型下载源。

将包含生产 `.env` 的仓库同步到生产服务器后：

```bash
chmod 600 deploy/prod/.env
docker compose version
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml config --quiet
```

`config --quiet` 只验证配置，不输出含密码的解析结果。若同机运行其他环境，先调整 `OPEN_WEBUI_PORT` 和 `OPEN_WEBUI_SUBNET`，避免端口或 Docker 网段冲突。当前网段为 `192.168.30.0/24`，生产网络也不得与此重叠。

首次手动部署先初始化数据库。在 Linux 生产服务器使用 PostgreSQL 16 客户端容器，避免系统自带客户端过旧（首次运行从 DaoCloud 拉取客户端镜像）：

```bash
docker run --rm -it --network host \
  --mount "type=bind,source=$PWD/deploy/prod/init-db.sql,target=/init-db.sql,readonly" \
  --entrypoint psql m.daocloud.io/docker.io/library/postgres:16-alpine \
  -h 172.16.60.190 -p 5000 -U postgres -W -d postgres \
  -v ON_ERROR_STOP=1 -f /init-db.sql
```

该容器只运行 `psql` 客户端，退出后自动删除。密码提示出现时，输入 PostgreSQL 原始密码（开头为 `/`，不是 URL 编码后的 `%2F`）。命令必须在仓库根目录执行，确保 `deploy/prod/init-db.sql` 存在。

如果宿主机已经安装兼容 SCRAM 的新版客户端，也可以执行：

```bash
psql -h 172.16.60.190 -p 5000 -U postgres -W -d postgres \
  -f deploy/prod/init-db.sql
```

如果出现 `psql: SCRAM authentication requires libpq version 10 or above`，说明客户端加载的 `libpq` 版本过旧，连接认证未完成，初始化脚本尚未执行。直接改用上面的 Docker 命令即可。也可升级宿主机 PostgreSQL 客户端及配套 `libpq` 后重试；本方案无需修改服务端认证方式。参见 [PostgreSQL 官方关于 libpq 10 支持 SCRAM 的说明](https://www.postgresql.org/message-id/CAB7nPqQokqy1ORBEjRqqGaCmW47W3tCbs85FUSqwZrrdivhBzA%40mail.gmail.com)。

脚本在数据库不存在时创建 `openwebui`，然后在该库中执行 `CREATE EXTENSION IF NOT EXISTS vector`，可重复运行。`PGVECTOR_CREATE_EXTENSION=false` 要求此步骤先完成；业务表和向量表由应用首次启动时初始化。若数据库已存在，先确认它专用于本应用，再运行初始化与应用迁移。本文提供操作步骤，本次未执行生产建库或应用迁移。

## 3. 构建并启动

```bash
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  build open-webui

docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  up -d --no-build --pull never --wait --wait-timeout 300
```

先构建 `company/open-webui:prod`，再让 `model-cache-init` 从该镜像向持久卷复制模型缓存，最后启动应用。初始化服务成功退出属于正常现象。首次构建需要下载依赖与嵌入模型，请等待构建完成。

`WEBUI_SECRET_KEY` 已生成；后续升级和多副本部署应保留同一个值。当前 `UVICORN_WORKERS=1`。数据库池分为业务同步、业务异步及向量连接池，扩容 worker 或副本前需合计连接上限。

### 构建时 Docker Hub 连接被重置

如果错误停在 `docker-image://docker.io/docker/dockerfile:1`，并提示 `registry-1.docker.io ... connection reset by peer`，失败发生在下载 Dockerfile 解析器阶段，尚未进入应用构建。仓库已移除外部 `syntax` 指令，改用 BuildKit 自带解析器；同步最新 `Dockerfile` 后重新执行 `bash deploy/prod/deploy.sh`。

如果暂时无法同步代码，也可以在 Linux 服务器的仓库根目录执行以下命令，再重试部署：

```bash
sed -i '1{/^# syntax=docker\/dockerfile:1$/d;}' Dockerfile
bash deploy/prod/deploy.sh
```

这个修改只消除 Dockerfile 解析器的额外拉取。若下一步在 `load metadata for docker.io/library/python` 或 `node` 失败，说明基础镜像拉取仍在直接访问 Docker Hub。

当前已按部署要求将 Dockerfile 默认值、三个环境的 Compose、实际 `.env` 和模板统一配置为 DaoCloud 镜像源：

```dotenv
OPEN_WEBUI_NODE_IMAGE=m.daocloud.io/docker.io/library/node:22-alpine3.20
OPEN_WEBUI_PYTHON_IMAGE=m.daocloud.io/docker.io/library/python:3.11-slim-bookworm
```

镜像地址采用 DaoCloud 官方推荐的增加前缀方式，完整路径保留 `docker.io/library/`，不包含 `https://`。直接使用这些完整镜像名即可，无需修改 `/etc/docker/daemon.json` 或重启 Docker。需要其他镜像源时，可在对应 `.env` 覆盖这两个变量，保持相同的运行时与操作系统版本。

将最新 Dockerfile、Compose 和生产 `.env` 同步到服务器后，可以先验证镜像拉取，再运行部署：

```bash
docker pull m.daocloud.io/docker.io/library/node:22-alpine3.20
docker pull m.daocloud.io/docker.io/library/python:3.11-slim-bookworm
bash deploy/prod/deploy.sh
```

若日志依然显示直接访问 `docker.io/library/python` 或 `node`，应检查这三个配置文件是否已同步，以及 shell 环境变量是否覆盖了 `.env`。如果暂时无法同步配置，可在旧版 Dockerfile 中将两个 `FROM` 使用的镜像名分别替换为上述完整镜像名。

基础镜像切换不会自动解决后续 npm、pip、apt/apk 或模型文件的下载限制。生产服务器缺少这些外网访问条件时，可以采用下面的完整镜像导入方式。

也可以在具备构建网络、并且目标 CPU 架构与生产服务器一致的机器上，用本仓库构建完整应用镜像：

```bash
docker build -t company/open-webui:prod .
docker save -o open-webui-prod.tar company/open-webui:prod
```

将镜像文件传到生产服务器，连同仓库和环境配置一起准备好后执行：

```bash
docker load -i open-webui-prod.tar
bash deploy/prod/deploy.sh --no-build
```

镜像标签需要与生产 `.env` 的 `OPEN_WEBUI_IMAGE_TAG` 保持一致，以上使用当前默认值 `prod`。导入镜像后，部署仍需访问 PostgreSQL、Redis 和 OSS。

参考：[DaoCloud 镜像前缀用法](https://github.com/DaoCloud/public-image-mirror#使用方法)、[BuildKit 自带 Dockerfile 解析器](https://docs.docker.com/build/buildkit/frontend/)、[Docker daemon 代理配置](https://docs.docker.com/engine/daemon/proxy/)。

> 如果构建在 Hugging Face 模型下载阶段失败，可先按 [离线模型包操作步骤](../OFFLINE_MODELS.md) 在联网机器下载模型并上传，再执行生产部署。

## 4. 配置访问入口

### 临时排障：内网 HTTP IP 直连

正式部署默认使用 HTTPS。只有需要临时通过 `http://172.22.11.124:3000/` 直连排障时，才将 `.env` 临时改为以下配置，并在排障后恢复 HTTPS 配置：

```dotenv
CORS_ALLOW_ORIGIN='http://172.22.11.124:3000;https://chatbot.maxphotonics.com'
WEBUI_SESSION_COOKIE_SECURE=false
WEBUI_AUTH_COOKIE_SECURE=false
```

头像使用浏览器 `<img>` 请求，需要登录 Cookie；普通 API 则可使用请求头中的 Bearer token。若在 HTTP 入口设置 `WEBUI_AUTH_COOKIE_SECURE=true`，浏览器无法为该入口正常使用 Secure Cookie，因此会出现普通接口返回 200、用户和模型头像返回 401 的现象。

`CORS_ALLOW_ORIGIN` 同时用于 Socket.IO 的来源校验，必须包含浏览器实际访问的协议、主机和端口，不加尾部 `/`，多个来源用分号分隔。只允许 HTTPS 域名时，HTTP IP 来源的 WebSocket 握手会被拒绝。2026-09-23 对当前服务器的对比检查中，同一 `/ws/socket.io/?EIO=4&transport=websocket` 请求使用 HTTP IP Origin 返回 403，使用配置中的 HTTPS 域名 Origin 返回 101，确认是来源配置不匹配；101 仅证明握手通过，不代表完整登录或长连接已验证。

更新服务器 `.env` 后，只需重新创建应用容器来加载环境变量，无需重建镜像，也无需再次运行模型缓存或数据库初始化：

```bash
docker compose --project-name open-webui-prod \
  --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  up -d --no-deps --no-build --pull never --force-recreate \
  --wait --wait-timeout 300 open-webui
```

然后在当前 IP 地址下退出并重新登录。浏览器 Network 中用户头像请求应返回 200，`/ws/socket.io/` 应返回 101 且保持连接。若仍有问题，检查运行中容器的这三个环境变量是否与文件一致；`docker compose restart` 不会加载新的环境变量。

HTTP 会明文传输登录凭据和 Cookie，这套配置仅用于当前内网 HTTP 入口。切换到 HTTPS 后，应恢复下面的 Secure Cookie 配置。

### 正式生产：HTTPS 域名

现有域名入口已通过健康检查与 WebSocket 握手检查，可沿用。新建或迁移入口时，将 `chatbot.maxphotonics.com` 的 DNS 指向反向代理或负载均衡入口，安装该域名证书，向应用服务器 `3000` 端口转发。必须支持 WebSocket Upgrade，并关闭响应缓冲以支持流式回复。

现有 Nginx HTTPS `server` 中可加入以下配置（假设 Nginx 与应用在同一宿主机；否则替换 `127.0.0.1`）：

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

按实际上传文件大小设置代理的请求体大小限制。DNS、证书和反向代理就绪后，将 `.env` 改为：

```dotenv
CORS_ALLOW_ORIGIN='https://chatbot.maxphotonics.com'
WEBUI_SESSION_COOKIE_SECURE=true
WEBUI_AUTH_COOKIE_SECURE=true
```

使用上面的命令重新创建应用容器，此后统一通过正式 HTTPS 域名访问并重新登录。

## 5. 验收

```bash
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml ps -a
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  logs --tail=100 open-webui
curl -fsS http://127.0.0.1:3000/health
# 仅在 HTTPS 域名入口配置完成后执行：
curl -fsS https://chatbot.maxphotonics.com/health
```

`open-webui` 应为 healthy，`model-cache-init` 应退出码为 0，两个健康接口应返回 `{"status":true}`。健康接口不能代替完整业务验收：

1. 首次打开站点创建管理员账号，在管理后台接入公司模型服务并完成一次流式对话。
2. 上传文件，确认 OSS `chatbot/open-webui/prod/` 下生成对象，并验证下载。
3. 导入一份知识库文档并提问，确认 pgvector 写入和检索正常，日志中没有认证或维度错误。
4. 确认浏览器 WebSocket 连接成功，日志中没有 Redis/Sentinel 认证失败。

如修改嵌入模型，先核对模型输出维度；当前表结构使用 `384`。已有向量数据时，不能只改环境变量就切换维度，需安排向量表迁移与知识库重建。

## 6. 更新和停止

修改 `.env` 后重建应用容器，`restart` 不会加载新环境变量：

```bash
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  up -d --no-build --pull never --force-recreate --wait --wait-timeout 300 open-webui
```

更新源码时重新执行第 3 节。生产升级前备份 PostgreSQL、OSS 和应用持久卷；版本回退还需确认数据库迁移兼容性。停止服务且保留持久卷：

```bash
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml down
```

## 7. Windows AD 登录：应用账号绑定失败

`Application account bind failed` 表示应用使用管理后台保存的 Application DN 和应用密码绑定 AD 失败，此时尚未搜索用户或校验个人登录密码。不能仅凭这句话认定密码错误，需要 AD 的 LDAP result 和诊断子码。

先核对应用账号的完整 DN 或 UPN（如 `svc_ldap@example.com`，使用实际 AD 域名），以及该应用账号的密码和账号状态。后台保存的 LDAP 配置默认优先于 `.env`，因此应在管理后台核对生效值。用户搜索基准、`sAMAccountName` 等属性要等应用账号绑定成功后再排查。

本项目的 TLS 开关传给 `ldap3.Server(use_ssl=...)`，对应直接 LDAPS，通常使用 636 端口；当前实现没有调用 389 端口的 StartTLS。AD 若要求加密或 LDAP 签名，可能拒绝明文 Simple Bind。浏览器站点的 HTTPS 配置不会改变应用到 AD 的连接方式。LDAPS 应使用证书匹配的域控主机名和容器内可信的 CA。

将 `deploy/diagnose_ldap.py` 同步到服务器，在仓库根目录运行一次：

```bash
docker compose --project-name open-webui-prod \
  --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  exec -T open-webui python - < deploy/diagnose_ldap.py
```

脚本适用于当前 PostgreSQL 部署，默认使用与应用常规数据库操作相同的 `psycopg` 驱动，读取运行中容器的环境变量和数据库 LDAP 配置，以只读数据库事务读取配置；不导入应用、不运行迁移、不搜索或修改 AD 用户。它只进行一次应用账号绑定，不重试、不跟随 LDAP referral，不打印密码、完整应用账号、数据库连接串或 AD 原始诊断文本。无需重建镜像。返回码 0 表示应用账号绑定成功，1 表示 AD 拒绝绑定，2 表示配置读取、网络或 TLS 等检查失败。

### 诊断脚本提示读取配置失败，但本地账号登录正常

此时脚本尚未连接 AD。旧脚本只显示 `OperationalError`，不能据此判断数据库宕机或密码错误；应用可能复用已有连接，而诊断脚本需要新建连接，且旧脚本使用 `psycopg2`，与应用的 `psycopg` 驱动不同。

同步新版 `deploy/diagnose_ldap.py` 后，先只检查配置，不尝试 AD 绑定：

```bash
docker compose --project-name open-webui-prod \
  --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  exec -T open-webui python - --config-only < deploy/diagnose_ldap.py
```

脚本会输出实际数据库主机、端口、库名、配置来源及客户端版本，不输出账号密码或连接串。数据库地址应与当前环境一致；不要把 `.env` 的内容整体贴到日志中。`exec` 使用的是运行中容器已有的环境，命令中的 `--env-file` 不会更新这个环境。

若成功，输出包含 `configuration_read_ok: true` 和 `ad_bind_attempted: false`，再执行上面的单次 AD 绑定命令。若仍失败，将输出的 `stage`、`category`、`sqlstate` 与数据库目标信息用于定位：

| category | 排查方向 |
| --- | --- |
| `database_authentication_failed` / `database_password_missing` | 容器实际使用的数据库凭据或认证方式 |
| `database_dns_failed` / `database_connection_refused` / `database_timeout` | 容器到数据库的域名解析、端口、网络或超时 |
| `database_connection_limit` | 数据库或代理是否拒绝新连接；现有应用连接仍可能可用 |
| `database_access_rule` / `database_tls_failed` | 数据库访问规则、TLS 或 CA 配置 |
| `client_libpq_too_old` | 客户端 libpq 与数据库认证协议不兼容 |
| `config_table_not_found` / `database_permission_denied` | 数据库、schema、表结构或查询权限 |

需要对比旧驱动时，在 `--config-only` 后增加 `--db-driver psycopg2`，只检查数据库，不重试 AD。不要因为诊断失败就重新建库或修改正常运行的数据库密码。

### AD 返回码

重点查看输出的 `ldap_result`、`description`、`ad_subcode`：`49 / invalidCredentials` 指向身份凭据或账号状态；AD 子码 `52e` 表示用户名或密码不正确，`775` 表示账号锁定；`8 / strongerAuthRequired` 表示要求更强认证，应核对 AD 的 LDAPS/签名要求。绑定成功仅代表应用账号可认证，用户搜索和个人密码校验仍需后续验证。已有连续失败时不要反复重试，以免触发 AD 锁定策略。

参考：[AD Simple Bind 支持的账号格式](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-adts/6a5891b8-928e-4b75-a4a5-0e3b77eaca52)、[AD LDAP 签名要求](https://learn.microsoft.com/en-us/troubleshoot/windows-server/active-directory/enable-ldap-signing-in-windows-server)、[ldap3 Bind 结果](https://ldap3.readthedocs.io/en/latest/bind.html)。

不要添加 `-v`。如变更 Docker 网段，需要先 `down` 再 `up`。

参考：[redis-py Sentinel 独立连接参数](https://redis.readthedocs.io/en/stable/connections.html#redis.sentinel.Sentinel)、[Socket.IO Redis/Sentinel 管理器](https://python-socketio.readthedocs.io/en/stable/api_manager.html#socketio.AsyncRedisManager)。
