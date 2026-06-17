"""PyInstaller 打包入口（纯 ASCII 文件名，避免编码相关的打包失败）。功能同 app.pyw。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from recite.gui import launch
    launch()
except Exception:
    import traceback
    msg = traceback.format_exc()
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("启动失败", msg)
    except Exception:
        sys.stderr.write(msg)
