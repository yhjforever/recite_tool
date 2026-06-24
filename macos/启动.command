#!/bin/bash
# 背诵稿生成器 · macOS 启动（双击即用；首次会自动装好依赖，无需手动操作）
cd "$(dirname "$0")" || exit 1

DL="https://www.python.org/downloads/macos/"
req_ok() { "$1" -c "import yaml, requests, pypdf, webview" >/dev/null 2>&1; }
tk_ok()  { "$1" -c "import tkinter" >/dev/null 2>&1; }
alert()  { osascript -e "display dialog \"$1\" buttons {\"好\"} default button 1 with icon $2 with title \"背诵稿生成器\"" >/dev/null 2>&1; }

# 1) 找系统 python3（首次创建虚拟环境用）
SYS_PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then SYS_PY="$c"; break; fi
done
if [ -z "$SYS_PY" ]; then
  alert "未检测到 Python。点“好”后会打开 Python 官网下载页，请安装 Python 3.10+（自带 Tkinter），装好后再双击本程序即可。" stop
  open "$DL"
  exit 1
fi

# 2) 优先用已建好的虚拟环境
PY=""
[ -x ".venv/bin/python" ] && PY="./.venv/bin/python"

# 3) 首次使用：自动建 .venv 并安装依赖（之后秒开）
if [ -z "$PY" ] || ! req_ok "$PY"; then
  echo "首次使用：正在自动安装依赖，请稍候（约 1 分钟，仅此一次）…"
  if [ ! -x ".venv/bin/python" ]; then
    if ! "$SYS_PY" -m venv .venv; then
      alert "创建运行环境失败。请确认已安装 python.org 版 Python 3.10+ 后重试。" stop
      open "$DL"; exit 1
    fi
  fi
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null 2>&1
  if ! "$PY" -m pip install -r requirements.txt; then
    alert "依赖安装失败，请检查网络后再次双击本程序重试。" stop
    exit 1
  fi
  echo "依赖安装完成。"
fi

# 4) 检查 Tkinter（图形界面必需）
if ! tk_ok "$PY"; then
  alert "当前 Python 缺少 Tkinter 图形库。建议改用 python.org 的安装包（自带 Tkinter）。点“好”打开下载页。" stop
  open "$DL"
  exit 1
fi

# 5) 启动图形界面
exec "$PY" -m recite gui
