# MAX chatbot 本地部署记录

## 目标与结果

- 完成时间：2026-09-22 20:06（Asia/Shanghai）。
- 环境：本机 Docker Desktop，Compose 项目 `open-webui-local`。
- 地址：http://localhost:3000
- 服务：`open-webui-local-open-webui-1`，状态 `healthy`，重启次数 0。
- 发布镜像：`company/open-webui:max-chatbot-20260922-200249`，同时标记为 `company/open-webui:local`。
- 当前镜像 ID：`sha256:1299331f0f41c83b1f953066cfc1f6bfc5306c446715974052790efc4f9e2506`。

## 变更边界

使用部署前正在运行的镜像作为底包，仅叠加本次已验证的 `build/` 前端产物。已核对旧镜像的基础层、环境、启动命令、工作目录、用户和健康检查均保持不变，没有重建后端依赖或修改认证逻辑。

复用数据卷 `open-webui-local_open-webui`，仍挂载于 `/app/backend/data`。既有环境配置与部署后容器逐项一致。没有运行 `model-cache-init`，没有初始化或删除数据库、Redis、OSS、向量数据和模型缓存；test、prod 环境未改动。

切换命令：

```sh
docker compose --env-file deploy/local/.env -f deploy/local/docker-compose.yaml \
  up -d --no-deps --no-build --pull never --wait --wait-timeout 180 open-webui
```

保留已有内容哈希静态文件，避免已打开的旧页面在切换时丢失资源；刷新页面会加载新入口。

## 实际服务验证

- `/health` 返回 `{"status":true}`。
- 浏览器标题与页面名称为 `MAX chatbot`，卡片为 784 × 520px。
- 企业 LDAP 入口、管理员邮箱入口、记住复选框、默认密码隐藏、底部联系人均通过检查。
- 实际服务返回的 10 个图标资源与本次源文件 SHA-256 逐一一致。
- 浏览器脚本错误为 0，没有更新或更新日志请求。
- 未向真实 LDAP 或邮箱认证接口提交测试密码。完整登录与记住行为已在上一阶段使用模拟接口回归通过。

## 回滚

旧镜像已保留为 `company/open-webui:rollback-20260922-200249`：
`sha256:265d6c581b025ec759de7e9581f13ca004395d08fe83ee3351ee72fa3aaaf397`。

需要回滚时，在仓库根目录执行以下命令；保留数据卷和配置，仅恢复旧镜像：

```sh
docker tag company/open-webui:rollback-20260922-200249 company/open-webui:local
docker compose --env-file deploy/local/.env -f deploy/local/docker-compose.yaml \
  up -d --no-deps --no-build --pull never --wait --wait-timeout 180 open-webui
```

不要使用 `down -v`，也不要在保留回滚版本期间清理该旧镜像。
