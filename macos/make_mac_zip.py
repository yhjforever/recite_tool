"""在 Windows 上打出一个「macOS 解压即点开」的分发包。

为什么需要它：Windows 自带的“压缩为 zip”不会保存 Unix 可执行权限，
对方在 Mac 上解压后双击 .command 会因“没有执行权限”而打不开。
本脚本用 Python 的 zipfile 把 .command 脚本的可执行位（0755）写进 zip 的
Unix 权限字段，并标记宿主系统为 Unix —— macOS 的“归档实用工具”和 unzip
都会照此恢复权限。于是对方流程变成：解压 → 双击「启动.command」即可，
全程不用打开终端、不用 chmod。

用法（在本目录）：  python make_mac_zip.py
产物：             ../recite_tool_mac.zip
"""
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent
TOP = "recite_tool_mac"                       # 解压后顶层文件夹名
OUT = SRC.parent / "recite_tool_mac.zip"

# 不打进分发包的内容：缓存、虚拟环境、打包产物、隐私文件、本脚本自身
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".venv", "build", "dist", ".git", ".idea"}
EXCLUDE_FILES = {".env", "config.yaml", "gui_state.json", ".DS_Store", Path(__file__).name}


def unix_mode(path: Path) -> int:
    """.command 脚本 = 可执行 0755；其余普通文件 = 0644（含文件类型位 S_IFREG）。"""
    return 0o100755 if path.suffix == ".command" else 0o100644


def included(rel: Path) -> bool:
    if set(rel.parts) & EXCLUDE_DIRS:
        return False
    return rel.name not in EXCLUDE_FILES


def main():
    if OUT.exists():
        OUT.unlink()
    files = []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(SRC.rglob("*")):
            if p.is_dir():
                continue
            rel = p.relative_to(SRC)
            if not included(rel):
                continue
            zi = zipfile.ZipInfo(f"{TOP}/{rel.as_posix()}", date_time=(2026, 1, 1, 0, 0, 0))
            zi.create_system = 3                  # 3 = Unix：让解压端尊重下面的权限位
            zi.external_attr = unix_mode(p) << 16  # 高 16 位 = Unix st_mode
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, p.read_bytes())
            files.append(zi.filename)

    print(f"✅ 已生成分发包：{OUT}")
    print(f"   共 {len(files)} 个文件。其中 .command 已带可执行权限：")
    with zipfile.ZipFile(OUT) as z:
        for info in z.infolist():
            if info.filename.endswith(".command"):
                mode = (info.external_attr >> 16) & 0o777
                ok = "✓" if (mode & 0o100) else "✗"
                print(f"     {ok} {info.filename}  mode={oct(mode)} host={'Unix' if info.create_system == 3 else info.create_system}")
    print("\n把 recite_tool_mac.zip 拷到 Mac → 双击解压 → 双击「启动.command」即可。")


if __name__ == "__main__":
    main()
