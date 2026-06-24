"""打包成 exe（免对方装 Python）。
  python build_exe.py            -> onedir（默认，启动快；产物是 dist/背诵稿生成器 文件夹）
  python build_exe.py onefile    -> 单文件（分发方便，但每次启动要解压、较慢）
产物不含任何 API Key，每个人首次运行填自己的 Key。"""
import os
import sys
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_NAME = "背诵稿生成器"

# 明显用不到的大依赖：显式排除以减小体积、加快启动（未安装时该项为无害空操作）
SLIM_EXCLUDES = ["pytest", "matplotlib", "numpy", "scipy", "pandas",
                 "PyQt5", "PySide2", "PySide6", "notebook", "IPython", "tornado"]


def main():
    onefile = "onefile" in sys.argv
    try:
        import PyInstaller.__main__  # noqa
    except ImportError:
        print("未安装 PyInstaller，正在安装： pip install pyinstaller ...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

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
        "--onefile" if onefile else "--onedir",
        "--windowed",            # 无控制台黑窗
        "--noconfirm",
        "--clean",
        "--hidden-import", "pypdf",
        "--hidden-import", "yaml",
        "--hidden-import", "requests",
        # 注意：不打包 .env / gui_state.json / config.yaml —— 防止把你的 Key 带给别人
    ]
    for m in SLIM_EXCLUDES:
        args += ["--exclude-module", m]

    try:
        import pptx  # noqa
        args += ["--collect-all", "pptx", "--collect-all", "lxml"]
        print("检测到 python-pptx：exe 将支持 .pptx 原生课件。")
    except ImportError:
        print("未装 python-pptx：exe 仅支持 PDF/txt/md（如需 pptx 请先 pip install python-pptx）。")

    # Web 版（pywebview + WebView2）：打包前端资源 + pywebview/pythonnet 运行时
    web = HERE / "recite" / "web" / "index.html"
    if web.exists():
        args += ["--add-data", f"{web}{os.pathsep}recite/web"]
    try:
        import webview  # noqa
        args += ["--collect-all", "webview", "--hidden-import", "clr"]
        for pkg in ("clr_loader", "pythonnet"):
            try:
                __import__(pkg)
                args += ["--collect-all", pkg]
            except Exception:
                pass
        print("检测到 pywebview：exe 将优先使用 Web 版界面（目标机需 WebView2，Win11 预装）。")
    except ImportError:
        print("未装 pywebview：exe 退回 CustomTkinter 界面。")

    try:
        import customtkinter  # noqa
        args += ["--collect-all", "customtkinter", "--hidden-import", "darkdetect"]
        print("检测到 customtkinter：exe 将使用圆角现代界面。")
    except ImportError:
        print("未装 customtkinter：exe 退回 ttk 界面。")

    try:
        import ttkbootstrap  # noqa
        args += ["--collect-all", "ttkbootstrap", "--collect-all", "PIL",
                 "--hidden-import", "darkdetect"]
        print("检测到 ttkbootstrap：ttk 回退界面也将现代化。")
    except ImportError:
        print("未装 ttkbootstrap：ttk 回退使用内置 clam 主题。")

    icon = HERE / "icon.ico"
    if icon.exists():
        args += ["--icon", str(icon)]

    import PyInstaller.__main__ as pim
    pim.run(args)

    # onedir: dist/背诵稿生成器/背诵稿生成器.exe ；onefile: dist/背诵稿生成器.exe
    out_dir = HERE / "dist" / APP_NAME if not onefile else HERE / "dist"
    exe = out_dir / f"{APP_NAME}.exe"
    if exe.exists():
        manual = HERE / "使用说明.txt"
        if manual.exists():
            shutil.copy2(manual, out_dir / "使用说明.txt")    # 说明书放进同一目录
        mode = "单文件(onefile)" if onefile else "目录(onedir，启动快)"
        print(f"\n✅ 打包成功（{mode}）： {exe}")
        if onefile:
            print("把 dist 里的 exe 和 使用说明.txt 发给别人即可。")
        else:
            print(f"把整个『dist/{APP_NAME}』文件夹打包成 zip 发给别人（启动快、双击里面的 exe）。")
    else:
        print("\n❌ 打包未生成 exe，请把上面的报错发来排查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
