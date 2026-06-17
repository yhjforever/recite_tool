#!/bin/bash
# 背诵稿生成器 · macOS 一次性安装脚本（双击运行）
# 作用：创建本地 Python 虚拟环境 .venv 并安装全部依赖。装一次即可，之后双击「启动.command」。
cd "$(dirname "$0")" || exit 1

echo "==============================================="
echo "   背诵稿生成器 · macOS 安装"
echo "==============================================="

# 1) 查找可用的 python3
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "✗ 未找到 Python。请先安装 Python 3.10+："
  echo "    方式A（推荐，自带 Tkinter）：https://www.python.org/downloads/macos/"
  echo "    方式B（Homebrew）：brew install python python-tk"
  read -n 1 -s -r -p "按任意键退出…"; echo; exit 1
fi
echo "✓ 使用 Python：$($PY --version 2>&1)   ($PY)"

# 2) 检查 Tkinter（图形界面必需）
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "✗ 当前 Python 缺少 Tkinter（图形界面库）。"
  echo "    · 若用 Homebrew：brew install python-tk"
  echo "    · 或改用 python.org 的安装包（自带 Tkinter，最省心）。"
  read -n 1 -s -r -p "按任意键退出…"; echo; exit 1
fi
echo "✓ Tkinter 可用"

# 3) 创建虚拟环境 .venv（隔离依赖，避开 macOS 的 PEP 668 限制）
if [ ! -d ".venv" ]; then
  echo "· 正在创建虚拟环境 .venv …"
  "$PY" -m venv .venv || { echo "✗ 创建虚拟环境失败"; read -n 1 -s -r -p "按任意键退出…"; echo; exit 1; }
fi

# 4) 安装依赖
echo "· 正在安装依赖（pypdf / requests / PyYAML / python-pptx / ddgs）…"
./.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
if ! ./.venv/bin/python -m pip install -r requirements.txt; then
  echo "✗ 依赖安装失败，请检查网络后重试。"
  read -n 1 -s -r -p "按任意键退出…"; echo; exit 1
fi

# 5) 给其余 .command 脚本补上可执行权限，便于直接双击
chmod +x "启动.command" "创建桌面快捷方式.command" "打包App.command" 2>/dev/null

echo
echo "✅ 安装完成！现在可以双击「启动.command」打开程序。"
read -n 1 -s -r -p "按任意键退出…"; echo
