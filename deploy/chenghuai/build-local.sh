#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$repo_root"
command -v bun >/dev/null || { echo '请先安装 Bun，并将 bun 加入 PATH。' >&2; exit 1; }
command -v go >/dev/null || { echo '请先安装符合 go.mod 要求的 Go 工具链。' >&2; exit 1; }

mkdir -p .local/bin
(
  cd web
  bun install --frozen-lockfile
  bun --bun run typecheck
  VITE_REACT_APP_VERSION=v1.0.0-rc.23-chenghuai bun --bun run build
)
go build -p 4 -ldflags '-s -w -X github.com/QuantumNous/new-api/common.Version=v1.0.0-rc.23-chenghuai' \
  -o .local/bin/new-api-demo.next .
mv .local/bin/new-api-demo.next .local/bin/new-api-demo
echo '构建完成。启用模拟充值：python3 deploy/chenghuai/run-local.py start --demo-payments'
