#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
用法：bash deploy/deploy.sh <local|test|prod> [选项]

默认流程：检查配置 → 构建镜像 → 初始化数据库/pgvector → 启动并等待健康。
  --check          仅检查本地配置，不构建、不连接数据库、不启动服务
  --no-build       使用已有镜像，跳过源码构建
  --skip-db-init   不创建数据库或扩展，但仍检查数据库连接及 pgvector
  --wait-timeout N 等待服务健康的秒数，默认 300
  -h, --help       显示帮助

配置文件固定为脚本所在仓库的 deploy/<环境>/.env；不会执行其中的 shell 代码。
示例：bash deploy/prod/deploy.sh
      bash /opt/max/deploy/deploy.sh test --no-build
EOF
}

fail() { printf '[错误] %s\n' "$*" >&2; exit 1; }
step() { printf '\n[部署] %s\n' "$*"; }

if [[ $# -eq 0 ]]; then usage; exit 1; fi
case "$1" in
  -h|--help) usage; exit 0 ;;
  local|test|prod) environment="$1"; shift ;;
  *) usage; fail '环境必须为 local、test 或 prod。' ;;
esac

check_only=false
build_image=true
initialize_db=true
wait_timeout=300
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) check_only=true ;;
    --no-build) build_image=false ;;
    --skip-db-init) initialize_db=false ;;
    --wait-timeout)
      [[ $# -ge 2 ]] || fail '--wait-timeout 缺少秒数。'
      wait_timeout="$2"; shift
      [[ "$wait_timeout" =~ ^[1-9][0-9]*$ ]] || fail '等待秒数必须为正整数。'
      ;;
    -h|--help) usage; exit 0 ;;
    *) fail "不支持的选项：$1" ;;
  esac
  shift
done

stage='检查环境'
trap 'status=$?; printf "[错误] %s 失败（退出码 %s），后续步骤已停止。\n" "$stage" "$status" >&2; exit "$status"' ERR
cd "$ROOT_DIR"
env_file="$ROOT_DIR/deploy/$environment/.env"
compose_file="$ROOT_DIR/deploy/$environment/docker-compose.yaml"
bootstrap_file="$ROOT_DIR/deploy/bootstrap.py"
[[ -f "$compose_file" && -f "$bootstrap_file" ]] || fail '部署文件不完整，请同步整个代码仓库。'
[[ -f "$env_file" ]] || fail "缺少 ${env_file}；请安全传入已填写的环境文件，或复制同目录 .env.example 后填写凭据。"
[[ -r "$env_file" ]] || fail "无法读取 ${env_file}。"

# Only report key names. Never source .env or print values containing credentials.
unfinished_keys="$(awk '
  /^[[:space:]]*(#|$)/ { next }
  /^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ {
    if ($0 ~ /CHANGE_ME|company[.]example|company[.]internal/) {
      key=$0; sub(/=.*/, "", key); sub(/^[[:space:]]*export[[:space:]]+/, "", key)
      gsub(/[[:space:]]/, "", key); print key
    }
  }
' "$env_file")"
[[ -z "$unfinished_keys" ]] || fail "请先填写环境文件中的占位配置（仅列变量名）：$unfinished_keys"
command -v docker >/dev/null 2>&1 || fail '未安装 Docker，请先安装 Docker Engine 和 Compose 插件。'
docker compose version >/dev/null 2>&1 || fail '需要 Docker Compose v2.24+ 或 v5（docker compose）。'

# Pin both the project and service env_file to the selected environment, even
# when the caller's shell has another Compose project or env_file configured.
export OPEN_WEBUI_ENV_FILE="$env_file"
compose=(docker compose --project-name "open-webui-$environment" --env-file "$env_file" -f "$compose_file")
step "检查 $environment 配置：$env_file"
"${compose[@]}" config --quiet
if [[ "$check_only" == true ]]; then
  printf '[完成] 配置检查通过；尚未验证远端依赖或部署服务。\n'
  exit 0
fi
docker info >/dev/null 2>&1 || fail 'Docker daemon 不可用，或当前用户没有 Docker 访问权限。'
chmod 600 "$env_file"

stage='准备应用镜像'
if [[ "$build_image" == true ]]; then
  step '从当前仓库源码构建应用镜像'
  "${compose[@]}" build open-webui
else
  image_name="$("${compose[@]}" config --images open-webui)"
  docker image inspect "$image_name" >/dev/null 2>&1 || fail '找不到当前环境的应用镜像，请去掉 --no-build 先构建。'
fi

stage='初始化或检查 PostgreSQL / pgvector'
bootstrap_args=("$environment")
if [[ "$initialize_db" == false ]]; then bootstrap_args+=(--check-only); fi
step "${stage}（使用应用镜像内的驱动，无需宿主机 psql）"
# Pass code through stdin so invocation never depends on the caller's cwd or
# bind-mounting a local SQL file. Compose supplies the fully expanded env_file.
"${compose[@]}" run --rm --no-deps --pull never -T --entrypoint python \
  open-webui - "${bootstrap_args[@]}" < "$bootstrap_file"

stage='启动应用并等待健康'
step "$stage"
if ! "${compose[@]}" up -d --no-build --pull never --wait --wait-timeout "$wait_timeout"; then
  "${compose[@]}" ps -a || true
  printf '[错误] 启动或健康检查失败，请用以下命令查看日志：\n' >&2
  printf 'docker compose --project-name %q --env-file %q -f %q logs --tail=100 open-webui model-cache-init\n' \
    "open-webui-$environment" "$env_file" "$compose_file" >&2
  exit 1
fi
"${compose[@]}" ps -a
printf '\n[完成] %s 环境应用已通过容器健康检查。\n' "$environment"
if [[ "$environment" == prod ]]; then
  printf '生产入口：请使用 deploy/prod/.env 中允许的站点地址；HTTP/HTTPS 切换见 deploy/prod/README.md。\n'
fi
