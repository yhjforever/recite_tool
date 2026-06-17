#!/bin/bash
# 打包“背诵稿生成器”为 macOS 应用 (.app)，免对方装 Python
cd "$(dirname "$0")" || exit 1
echo "============================================"
echo "  打包“背诵稿生成器”为 macOS 应用 (.app)"
echo "  .app 内不含任何 Key，对方首次运行填自己的 Key"
echo "============================================"

if [ -x ".venv/bin/python" ]; then
  PY="./.venv/bin/python"
else
  PY=""
  for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "✗ 未找到 Python，请先运行「安装-Mac.command」。"
  read -n 1 -s -r -p "按任意键退出…"; echo; exit 1
fi

"$PY" build_app.py
echo
read -n 1 -s -r -p "按任意键退出…"; echo
