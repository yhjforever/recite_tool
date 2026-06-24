"""把工具打包成 macOS 应用（.app，免对方装 Python）。用法： python3 build_app.py
产物： dist/背诵稿生成器.app（及便于分发的 .zip）—— 不含任何 API Key，
每个人首次运行填自己的 Key。请在 macOS 上运行本脚本。"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_NAME = "背诵稿生成器"
BUNDLE_ID = "com.recitetool.app"


def main():
    if sys.platform != "darwin":
        print("⚠ 本脚本用于在 macOS 上打包 .app；当前系统不是 macOS，请在 Mac 上运行。")

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("未安装 PyInstaller，正在安装： pip install pyinstaller ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 清理上次产物
    for d in ("build", "dist"):
        p = HERE / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    spec = HERE / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()

    args = [
        str(HERE / "run_app.py"),
        "--name", APP_NAME,
        "--windowed",                       # 生成 .app，无终端黑窗
        "--noconfirm",
        "--clean",
        "--osx-bundle-identifier", BUNDLE_ID,
        "--hidden-import", "pypdf",
        "--hidden-import", "yaml",
        "--hidden-import", "requests",
        # 注意：不打包 .env / gui_state.json / config.yaml —— 防止把你的 Key 带给别人
        "--exclude-module", "pytest",
    ]
    # 若装了 python-pptx，则把它（及其数据/依赖）一并打包，让 .app 支持 .pptx
    try:
        import pptx  # noqa: F401
        args += ["--collect-all", "pptx", "--collect-all", "lxml"]
        print("检测到 python-pptx：.app 将支持 .pptx 原生课件。")
    except ImportError:
        print("未装 python-pptx：.app 仅支持 PDF/txt/md（如需 pptx 请先 pip install python-pptx）。")

    web = HERE / "recite" / "web" / "index.html"
    if web.exists():
        args += ["--add-data", f"{web}{os.pathsep}recite/web"]
    try:
        import webview  # noqa: F401
        args += ["--collect-all", "webview"]
        print("检测到 pywebview：.app 将优先使用 Web 版界面。")
    except ImportError:
        print("未装 pywebview：.app 退回 CustomTkinter 界面。")

    icns = HERE / "icon.icns"
    if icns.exists():
        args += ["--icon", str(icns)]

    import PyInstaller.__main__ as pim
    pim.run(args)

    app = HERE / "dist" / f"{APP_NAME}.app"
    if app.exists():
        # 把《使用说明》一并放进 dist，便于和 .app 一起发给别人
        manual = HERE / "使用说明_macOS.txt"
        if manual.exists():
            shutil.copy2(manual, HERE / "dist" / "使用说明_macOS.txt")
        # 打成 zip（用 ditto 保留 .app 结构与权限，避免拷贝后损坏）
        try:
            subprocess.check_call(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                                   str(app), str(HERE / "dist" / f"{APP_NAME}.zip")])
            print("已生成 dist/背诵稿生成器.zip（便于发送）。")
        except Exception as e:
            print(f"（自动打 zip 失败，可在访达里手动压缩 .app：{e}）")
        print(f"\n✅ 打包成功： {app}")
        print("把 dist 里的 .app（或 .zip）发给别人即可；.app 不含任何 Key。")
        print("提示：对方首次打开若提示“无法验证开发者”，可右键→打开，")
        print("      或到「系统设置 → 隐私与安全性」点「仍要打开」。")
    else:
        print("\n❌ 打包未生成 .app，请把上面的报错发来排查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
