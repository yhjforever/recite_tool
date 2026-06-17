@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   打包“背诵稿生成器”为单个 exe（免装 Python）
echo   exe 内不含任何 Key，对方首次运行填自己的 Key
echo ============================================
python build_exe.py
echo.
pause
