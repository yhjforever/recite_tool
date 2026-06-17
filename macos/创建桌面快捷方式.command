#!/bin/bash
# 在「桌面」创建一个可双击的「背诵稿生成器」快捷方式（指向本目录的 启动.command）
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
DESK="$HOME/Desktop"
LNK="$DESK/背诵稿生成器.command"

# 确保被指向的启动脚本可执行
chmod +x "$HERE/启动.command" 2>/dev/null

cat > "$LNK" <<EOF
#!/bin/bash
# 由「创建桌面快捷方式.command」生成；双击即打开背诵稿生成器
cd "$HERE" || exit 1
exec "$HERE/启动.command"
EOF
chmod +x "$LNK"

echo "✅ 已在桌面创建快捷方式：背诵稿生成器"
echo "   目标：$HERE/启动.command"
echo
echo "提示：想要带图标、且不弹终端窗口的版本，可改用「打包App.command」生成 .app。"
read -n 1 -s -r -p "按任意键退出…"; echo
