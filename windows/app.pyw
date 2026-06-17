"""双击入口（用 pythonw 运行，无控制台黑窗）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from recite.gui import launch
    launch()
except Exception:
    # 启动失败时弹窗显示原因（否则 pythonw 下无任何提示）
    import traceback
    msg = traceback.format_exc()
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("启动失败", msg)
    except Exception:
        sys.stderr.write(msg)
