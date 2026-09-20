#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--https" ) ]]; then
  echo "用法：./start.sh [--https]" >&2
  exit 2
fi

command -v docker >/dev/null || { echo "请先安装 Docker Engine 和 Docker Compose v2。" >&2; exit 1; }
docker compose version >/dev/null
command -v python3 >/dev/null || { echo "请先安装 Python 3。" >&2; exit 1; }

python3 - <<'PY'
import os
from pathlib import Path
import secrets

target = Path('.env')
if not target.exists():
    config = Path('.env.example').read_text(encoding='utf-8')
    config = config.replace('SESSION_SECRET=CHANGE_ME', 'SESSION_SECRET=' + secrets.token_hex(32))
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write(config)
    print('已生成 .env；会话密钥保存在本机，重复启动不会更换。')
elif 'SESSION_SECRET=CHANGE_ME' in target.read_text(encoding='utf-8'):
    raise SystemExit('请将 .env 中的 SESSION_SECRET=CHANGE_ME 替换为随机密钥。')
PY

compose_args=(-f compose.yml)
if [[ "${1:-}" == "--https" ]]; then
  compose_args+=(-f compose.https.yml)
fi

exec docker compose "${compose_args[@]}" up -d --wait --wait-timeout 180
