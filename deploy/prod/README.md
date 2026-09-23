# 生产环境部署

在仓库根目录执行本文命令。生产配置位于 `deploy/prod/.env`，真实密码已填写，文件权限为 `600`，已被 Git 和 Docker 构建上下文排除。`.env.example` 保留相同配置结构，密码使用占位符；将代码交付到服务器时，需要单独安全传输 `.env`，不要用模板覆盖已填写的文件。

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
| 站点 | `https://chatbot.maxphotonics.com` |
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

安装 Docker Engine、Docker Compose v2.24+（或 v5）。数据库初始化推荐使用下方 Docker 客户端命令；若使用宿主机 `psql`，其实际加载的 `libpq` 必须为 10 或更高版本，以支持 SCRAM 认证。服务器需要能访问：

- PostgreSQL `172.16.60.190:5000`；
- 三个 Sentinel 的 `26379` 端口，以及 Sentinel 返回的 Redis 数据节点端口（本次为 `6379`）；所有可能晋升为 master 的节点均须可达；
- OSS HTTPS `9443` 端口；
- 首次源码构建所需的镜像仓库、npm、pip 及模型下载源。

将仓库和私有 `.env` 放到生产服务器后：

```bash
chmod 600 deploy/prod/.env
docker compose version
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml config --quiet
```

`config --quiet` 只验证配置，不输出含密码的解析结果。若同机运行其他环境，先调整 `OPEN_WEBUI_PORT` 和 `OPEN_WEBUI_SUBNET`，避免端口或 Docker 网段冲突。当前网段为 `192.168.30.0/24`，生产网络也不得与此重叠。

首次部署先初始化数据库。推荐在 Linux 生产服务器使用 PostgreSQL 16 客户端容器，避免系统自带客户端过旧（首次运行需要拉取 `postgres:16-alpine` 镜像）：

```bash
docker run --rm -it --network host \
  --mount "type=bind,source=$PWD/deploy/prod/init-db.sql,target=/init-db.sql,readonly" \
  --entrypoint psql postgres:16-alpine \
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

## 4. 配置 HTTPS 入口

将 `chatbot.maxphotonics.com` 的 DNS 指向反向代理或负载均衡入口，安装该域名证书，向应用服务器 `3000` 端口转发。必须支持 WebSocket Upgrade，并关闭响应缓冲以支持流式回复。

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

按实际上传文件大小设置代理的请求体大小限制。浏览器应通过正式 HTTPS 域名访问；生产配置启用了 Secure Cookie，直接用 HTTP 访问 IP 可能无法保持登录。

## 5. 验收

```bash
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml ps -a
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yaml \
  logs --tail=100 open-webui
curl -fsS http://127.0.0.1:3000/health
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

不要添加 `-v`。如变更 Docker 网段，需要先 `down` 再 `up`。

参考：[redis-py Sentinel 独立连接参数](https://redis.readthedocs.io/en/stable/connections.html#redis.sentinel.Sentinel)、[Socket.IO Redis/Sentinel 管理器](https://python-socketio.readthedocs.io/en/stable/api_manager.html#socketio.AsyncRedisManager)。
