#!/usr/bin/env bash
# 重建前端镜像并替换正在运行的 web 容器（解决「只 build 不 up，UI 不变」）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

exec docker compose -f "$ROOT/docker-compose.yml" up -d --build --force-recreate web
