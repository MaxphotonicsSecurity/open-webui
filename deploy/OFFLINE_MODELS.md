# 离线上传模型，在 Linux 服务器构建

适用于服务器能够安装 npm、pip、apt 依赖，但访问 Hugging Face 时连接被重置的情况。模型在联网的 Mac 或 Linux 上下载后打包，服务器构建时只读取离线缓存。模型数据可跨 ARM64/x86_64 传输，Python 二进制依赖仍在 Linux 镜像内安装。

这不是完整的断网构建：基础镜像、系统软件包、前端和 Python 依赖仍需从现有软件源获取。保留镜像中的 `numpy<2.4` 约束；离线模型包不改变 CPU 兼容性。

## 1. 在联网的本地机器准备

在项目根目录执行（需要 Python 3.11+ 和 uv）：

```bash
uv run --no-project --script deploy/model_cache.py download
```

脚本使用隔离环境，只安装下载工具，不需要在 Mac 安装整个项目或 PyTorch。网络中断后可以重新执行同一命令，Hugging Face 缓存会复用已下载文件。成功后生成：

- `deploy/offline-models.tar.gz`：供上传的离线包。
- `deploy/offline-models.tar.gz.sha256`：传输完整性校验。
- `deploy/offline-models/`：本地解压形式的缓存，不提交 Git。

包内包含当前 Dockerfile 默认配置所需的五组资源：

| 资源 | 内容 |
| --- | --- |
| 知识库 embedding | `sentence-transformers/all-MiniLM-L6-v2` |
| 辅助 embedding | `TaylorAI/bge-micro-v2` |
| 语音识别 | `Systran/faster-whisper-base` |
| Token 计数 | tiktoken `cl100k_base` |
| 文本分词 | NLTK `punkt_tab` |

当前下载脚本准备默认模型组合。如果修改了 Docker 构建中的模型参数，构建会因与离线包不匹配而停止，避免悄悄联网下载或使用错误模型。

## 2. 上传并校验

先同步本次代码改动到服务器，包括根目录 `Dockerfile`、`.dockerignore`、`backend/requirements.docker.in`、`deploy/model_cache.py` 和 `deploy/offline-models/.gitkeep`。镜像现在从 `.in` 文件读取 UTF-8 依赖清单；`.env` 和数据卷应保留。

将两个文件上传到服务器项目的 `deploy/` 目录。例如将 `/实际项目路径` 替换为服务器路径：

```bash
scp deploy/offline-models.tar.gz deploy/offline-models.tar.gz.sha256 \
  root@aigw-log02:/实际项目路径/deploy/
```

在 **Linux 服务器**的项目根目录执行：

```bash
(cd deploy && sha256sum -c offline-models.tar.gz.sha256)
tar -xzf deploy/offline-models.tar.gz -C deploy
```

应看到 `deploy/offline-models/manifest.json`。直接传输压缩包再解压，避免文件传输工具破坏 Hugging Face 缓存里的相对软链接。

## 3. 构建部署

```bash
bash deploy/prod/deploy.sh
```

Dockerfile 自动检测离线包，不需要设置代理、切换模型镜像站或使用 `USE_SLIM=true`。日志应包含：

```text
Validating and importing offline model cache...
Model cache ready (offline).
```

构建时先检查每个文件的 SHA-256，再复制到原来的模型缓存目录，并在禁止网络连接的 Python 进程中加载模型。缺失、损坏、模型配置不匹配或加载失败都会让构建停止。现有 `model-cache-init` 服务继续将模型复制到持久卷，应用的知识库模型路径保持一致。

Python 依赖安装和模型准备已经拆成独立构建层，后续只修复或替换模型缓存时，不必重跑未变更的依赖安装层。缓存目录为空（只包含 `.gitkeep`）时，仍使用原来的在线模型准备流程。
