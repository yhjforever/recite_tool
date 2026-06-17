"""图形界面（Tkinter，无需终端）：首启询问并保存 API Key；选择资料文件夹；
填写学科与课程说明；审计映射；按章勾选生成 Markdown 背诵稿。"""
import os
import json
import queue
import threading
import subprocess
import sys
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, scrolledtext

try:
    import ttkbootstrap as tb          # 现代化主题引擎（可选；缺失时回退到 clam）
except Exception:
    tb = None

from .config import ROOT, load_config
from .audit import run_audit
from .build import run_build
from .generate import run_generate
from .verify import run_verify
from .util import read_json, chapter_stem

SEARCH_ENV = {"tavily": "TAVILY_API_KEY", "serper": "SERPER_API_KEY", "bing": "BING_API_KEY"}

ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / "gui_state.json"


# ---------------- 持久化：API Key 与界面偏好 ----------------
def read_env_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k.strip()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == "DEEPSEEK_API_KEY":   # 精确匹配，避免 _BACKUP 等误伤
                return val.strip().strip('"').strip("'")
    return ""


def write_env_kv(name: str, value: str) -> None:
    """写入/更新 .env 的某个键（精确匹配键名），并同步到当前进程环境变量。"""
    value = value.strip()
    lines, found = [], False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            key, sep, _ = line.partition("=")
            if sep and key.strip() == name:
                lines.append(f"{name}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{name}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[name] = value


def write_env_key(key: str) -> None:
    write_env_kv("DEEPSEEK_API_KEY", key)


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(d: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class _QueueWriter:
    """把 print 输出转发到 GUI 日志队列。"""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(("log", s))
        return len(s)

    def flush(self):
        pass


def _enable_dpi_awareness():
    """让 Windows 高分屏下界面清晰、不发虚（必须在创建 Tk 窗口前调用）。"""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 每显示器 DPI 感知
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class App:
    def __init__(self, config_path=None):
        _enable_dpi_awareness()
        self.config_path = config_path
        self.q = queue.Queue()
        self.busy = False
        self.chapters = []        # 来自 audit.json
        self._buttons = []
        self._inputs = []         # 运行时需要一并禁用的输入控件：(widget, 启用态)
        self._need_audit = []     # 需要“已审计”才可用的按钮
        self._need_output = []    # 需要“已有输出”才可用的按钮
        self._focused = None      # 详情面板当前展示的章节行

        self.root = tb.Window(themename="litera") if tb is not None else tk.Tk()
        self.root.title("背诵稿生成器 · recite_tool")
        self.root.minsize(960, 720)
        try:
            ico = ROOT / "icon.ico"
            if ico.exists():
                self.root.iconbitmap(str(ico))
        except Exception:
            pass

        self.var_source = tk.StringVar()
        self.var_subject = tk.StringVar()
        self.var_provider = tk.StringVar(value="bing_cn")
        self.var_overwrite = tk.BooleanVar(value=False)
        self.var_keystat = tk.StringVar(value="未设置 ✗")
        self.var_status = tk.StringVar(value="就绪")
        self.var_phase = tk.StringVar(value="")     # 当前正在做什么
        self.var_searchstat = tk.StringVar(value="")  # 检索源状态
        self._logbuf = ""                            # 日志按行缓冲，便于整行着色

        self._apply_theme()
        self._build_ui()
        self._load_prefs()
        self._ensure_key()        # 首次启动：询问并保存 Key
        self.var_provider.trace_add("write", lambda *a: self._update_search_status())
        self.var_source.trace_add("write", lambda *a: self._update_actions())
        self._refresh_chapters()
        self._update_search_status()
        self._update_actions()
        self.root.after(120, self._poll)

    # ---------------- 主题 ----------------
    def _apply_theme(self):
        if tb is not None:
            self._theme_bootstrap()
        else:
            self._theme_clam()

    def _theme_bootstrap(self):
        st = self.root.style
        b = st.colors
        surf = "#EDF0F4"
        self.colors = {
            "surface": surf, "field": "#FFFFFF", "text": b.fg, "sub": "#7A828C",
            "border": b.border, "accent": b.primary, "accent_h": b.primary,
            "sel": "#DCEAFE", "head": "#EEF1F5", "zebra": "#F6F8FA",
            "ok": b.success, "warn": b.warning, "err": b.danger, "muted": "#9AA4AF",
        }
        f = ("Microsoft YaHei UI", 10)
        self.font, self.font_b = f, ("Microsoft YaHei UI", 10, "bold")
        self.root.configure(background=surf)
        st.configure(".", font=f)
        for s in ("TFrame", "TCheckbutton"):
            st.configure(s, background=surf)
        st.configure("TLabelframe", background=surf, borderwidth=0, relief="flat")
        st.configure("TLabelframe.Label", background=surf, foreground="#5B636C", font=self.font_b)
        st.configure("TLabel", background=surf, foreground=b.fg)
        st.configure("Sub.TLabel", background=surf, foreground=self.colors["sub"])
        st.configure("H1.TLabel", background=surf, foreground=b.dark,
                     font=("Microsoft YaHei UI", 17, "bold"))
        st.configure("Sec.TLabel", background=surf, foreground=b.dark,
                     font=("Microsoft YaHei UI", 11, "bold"))
        st.map("TCheckbutton", background=[("active", surf)])
        # 白色表格 + 蓝色选中行 + 更高行高
        st.configure("Treeview", rowheight=34, font=f, background="#FFFFFF",
                     fieldbackground="#FFFFFF", borderwidth=0)
        st.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"), padding=(6, 8))
        st.map("Treeview", background=[("selected", "#DCEAFE")], foreground=[("selected", b.fg)])
        # 进度条更细更现代
        st.configure("TProgressbar", thickness=6)
        self._kw_accent = {"bootstyle": "primary"}
        self._kw_sec = {"bootstyle": "light"}        # 次按钮：浅色、深字，与蓝色主按钮区分

    # ---------------- 主题（clam 回退，无第三方依赖时使用）----------------
    def _theme_clam(self):
        c = self.colors = {
            "surface": "#F4F5F7", "field": "#FFFFFF", "text": "#1F2937", "sub": "#6B7280",
            "border": "#E3E6EA", "accent": "#2563EB", "accent_h": "#1D4ED8",
            "sel": "#E8F0FE", "head": "#F1F3F5",
            "ok": "#059669", "warn": "#D97706", "err": "#DC2626", "muted": "#9AA0A6",
        }
        f = ("Microsoft YaHei UI", 10)
        fb = ("Microsoft YaHei UI", 10, "bold")
        self.font, self.font_b = f, fb
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        self.root.configure(bg=c["surface"])
        st.configure(".", background=c["surface"], foreground=c["text"], font=f,
                     borderwidth=0, focuscolor=c["surface"])
        st.configure("TFrame", background=c["surface"])
        st.configure("TLabel", background=c["surface"], foreground=c["text"])
        st.configure("Sub.TLabel", background=c["surface"], foreground=c["sub"])
        st.configure("H1.TLabel", background=c["surface"], foreground=c["text"],
                     font=("Microsoft YaHei UI", 14, "bold"))
        st.configure("Sec.TLabel", background=c["surface"], foreground=c["text"], font=fb)

        # 普通按钮：白底、细边、扁平；hover 浅蓝边
        st.configure("TButton", background=c["field"], foreground=c["text"],
                     bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"],
                     relief="flat", padding=(13, 7))
        st.map("TButton",
               background=[("active", "#EFF4FE"), ("pressed", "#E4ECFD"), ("disabled", "#F0F1F3")],
               foreground=[("disabled", "#A8AEB8")],
               bordercolor=[("active", c["accent"]), ("focus", c["accent"])])
        # 强调按钮：蓝底白字
        st.configure("Accent.TButton", background=c["accent"], foreground="#FFFFFF",
                     bordercolor=c["accent"], lightcolor=c["accent"], darkcolor=c["accent"],
                     relief="flat", padding=(15, 7), font=fb)
        st.map("Accent.TButton",
               background=[("active", c["accent_h"]), ("pressed", c["accent_h"]),
                           ("disabled", "#AEC4F2")],
               foreground=[("disabled", "#EEF2FF")])

        for w in ("TEntry", "TCombobox"):
            st.configure(w, fieldbackground=c["field"], background=c["field"], foreground=c["text"],
                         bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"],
                         arrowcolor=c["sub"], padding=5, relief="flat")
        st.map("TEntry", bordercolor=[("focus", c["accent"])])
        st.map("TCombobox", fieldbackground=[("readonly", c["field"])],
               bordercolor=[("focus", c["accent"])], background=[("readonly", c["field"])])
        self.root.option_add("*TCombobox*Listbox.background", c["field"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])

        st.configure("TLabelframe", background=c["surface"], bordercolor=c["border"],
                     lightcolor=c["border"], darkcolor=c["border"], relief="solid", borderwidth=1)
        st.configure("TLabelframe.Label", background=c["surface"], foreground=c["sub"], font=fb)
        st.configure("TCheckbutton", background=c["surface"], foreground=c["text"])
        st.map("TCheckbutton", background=[("active", c["surface"])])

        st.configure("Treeview", background=c["field"], fieldbackground=c["field"],
                     foreground=c["text"], rowheight=30, borderwidth=0, relief="flat")
        st.configure("Treeview.Heading", background=c["head"], foreground=c["sub"],
                     relief="flat", padding=(6, 7), font=("Microsoft YaHei UI", 9, "bold"))
        st.map("Treeview.Heading", background=[("active", "#E8ECF1")])
        st.map("Treeview", background=[("selected", c["sel"])], foreground=[("selected", c["text"])])

        st.configure("TProgressbar", background=c["accent"], troughcolor="#E5E7EB",
                     bordercolor="#E5E7EB", lightcolor=c["accent"], darkcolor=c["accent"], thickness=8)
        st.configure("Vertical.TScrollbar", background="#D9DCE1", troughcolor=c["surface"],
                     bordercolor=c["surface"], arrowcolor=c["sub"], relief="flat")
        st.map("Vertical.TScrollbar", background=[("active", "#C3C7CE")])
        self._kw_accent = {"style": "Accent.TButton"}
        self._kw_sec = {"style": "TButton"}

    # ---------------- UI 布局 ----------------
    def _build_ui(self):
        c = self.colors
        pad = dict(padx=14, pady=(4, 8))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        W, H = min(1120, max(960, sw - 120)), min(940, max(720, sh - 120))
        self.root.geometry(f"{W}x{H}")
        self.root.minsize(940, 700)

        # ===== 标题 =====
        hd = ttk.Frame(self.root); hd.pack(fill="x", padx=16, pady=(12, 0))
        ttk.Label(hd, text="背诵稿生成器", style="H1.TLabel").pack(side="left")
        ttk.Label(hd, text="   按大纲把课件 / 课本整理成可背诵的 Markdown",
                  style="Sub.TLabel").pack(side="left", pady=(7, 0))

        # ===== 顶部状态条：Key / 检索源 / 当前状态 =====
        top = ttk.Frame(self.root); top.pack(fill="x", padx=16, pady=(4, 6))
        ttk.Label(top, text="Key ", style="Sub.TLabel").pack(side="left")
        self.lbl_keystat = ttk.Label(top, textvariable=self.var_keystat, foreground=c["err"])
        self.lbl_keystat.pack(side="left", padx=(0, 16))
        ttk.Label(top, textvariable=self.var_searchstat, style="Sub.TLabel").pack(side="left")
        ttk.Label(top, textvariable=self.var_status, style="Sub.TLabel", anchor="e").pack(side="right")

        # ===== 设置区 =====
        s = ttk.LabelFrame(self.root, text="① 资料与设置")
        s.pack(fill="x", **pad)

        r2 = ttk.Frame(s); r2.pack(fill="x", padx=8, pady=4)
        ttk.Label(r2, text="资料文件夹：").pack(side="left")
        e = ttk.Entry(r2, textvariable=self.var_source, state="readonly")
        e.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_choose = ttk.Button(r2, text="选择…", command=self._choose_source, **self._kw_sec)
        self.btn_choose.pack(side="left"); self._buttons.append(self.btn_choose)
        b = ttk.Button(r2, text="设置/修改密钥", command=self._ask_key, **self._kw_sec)
        b.pack(side="left", padx=4); self._buttons.append(b)

        r3 = ttk.Frame(s); r3.pack(fill="x", padx=8, pady=4)
        ttk.Label(r3, text="学科名称：").pack(side="left")
        ent_subj = ttk.Entry(r3, textvariable=self.var_subject, width=22)
        ent_subj.pack(side="left", padx=4)
        self._inputs.append((ent_subj, "normal"))
        ttk.Label(r3, text="（留空自动判断）　联网核对来源：").pack(side="left")
        cmb = ttk.Combobox(r3, textvariable=self.var_provider, width=10, state="readonly",
                           values=["bing_cn", "pubmed", "ddg", "tavily", "serper", "bing"])
        cmb.pack(side="left", padx=4)
        self._inputs.append((cmb, "readonly"))
        b = ttk.Button(r3, text="设置检索Key", command=self._set_search_key, **self._kw_sec)
        b.pack(side="left", padx=2); self._buttons.append(b)

        r4 = ttk.Frame(s); r4.pack(fill="x", padx=8, pady=4)
        ttk.Label(r4, text="课程说明 / 整理偏好（可选，因地制宜，不会突破“忠实原文”铁律）：").pack(anchor="w")
        self.txt_note = tk.Text(r4, height=2, wrap="word", font=("Microsoft YaHei UI", 9))
        self.txt_note.pack(fill="x", pady=2)
        self._inputs.append((self.txt_note, "normal"))

        r6 = ttk.Frame(s); r6.pack(fill="x", padx=8, pady=(2, 8))
        b = ttk.Button(r6, text="保存设置", command=self._save_prefs, **self._kw_sec)
        b.pack(side="left"); self._buttons.append(b)
        b = ttk.Button(r6, text="检查分享包是否含密钥", command=self._check_share_keys, **self._kw_sec)
        b.pack(side="left", padx=6); self._buttons.append(b)
        ttk.Label(r6, text=f"（密钥保存在 {ENV_PATH}）", style="Sub.TLabel").pack(side="left", padx=4)

        # ===== 流程区：审计按钮 + （章节表格 | 详情面板） =====
        a = ttk.LabelFrame(self.root, text="② 审计 → 选择章节 → 生成 → 核对")
        a.pack(fill="both", expand=True, **pad)

        bar = ttk.Frame(a); bar.pack(fill="x", padx=8, pady=(6, 4))
        self.btn_audit = ttk.Button(bar, text="⟳  审计资料 / 刷新映射",
                                    command=self._do_audit, **self._kw_accent)
        self.btn_audit.pack(side="left"); self._buttons.append(self.btn_audit)
        ttk.Label(bar, text="  自动判定学科、把课件对到大纲各章；单击行首 ☑ 勾选，点行看右侧详情",
                  style="Sub.TLabel").pack(side="left", padx=8)

        mid = ttk.Frame(a); mid.pack(fill="both", expand=True, padx=8, pady=2)
        # 左：表格
        lf = ttk.Frame(mid); lf.pack(side="left", fill="both", expand=True)
        cols = ("chk", "stat", "idx", "title", "src", "oc")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", height=10, selectmode="browse")
        for col, txt, w, anchor in [("chk", "☑", 36, "center"), ("stat", "状态", 70, "center"),
                                    ("idx", "章序", 50, "center"), ("title", "章名", 140, "w"),
                                    ("src", "素材文件", 250, "w"), ("oc", "大纲字", 56, "e")]:
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor=anchor, stretch=(col in ("src", "title")))
        self.tree.tag_configure("even", background=c["field"])
        self.tree.tag_configure("odd", background=c["zebra"])     # 斑马纹
        self.tree.tag_configure("done", foreground=c["ok"])
        self.tree.tag_configure("partial", foreground=c["warn"])
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.config(yscrollcommand=sb.set)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._checked = set()
        # 右：章节详情面板
        df = ttk.LabelFrame(mid, text="章节详情", width=300)
        df.pack(side="right", fill="y", padx=(10, 0))
        df.pack_propagate(False)
        self.detail = tk.Text(df, width=36, height=10, wrap="word", state="disabled",
                              font=("Microsoft YaHei UI", 9), background=c["field"],
                              foreground=c["text"], relief="flat", borderwidth=0,
                              padx=10, pady=8, spacing1=2, spacing3=2)
        self.detail.pack(fill="both", expand=True, padx=2, pady=2)

        # 章节操作按钮（文案去掉序号，序号在分区标题里）
        btns = ttk.Frame(a); btns.pack(fill="x", padx=8, pady=(4, 8))

        def addbtn(text, cmd, padx=3, group=None, accent=False):
            b = ttk.Button(btns, text=text, command=cmd,
                           **(self._kw_accent if accent else self._kw_sec))
            b.pack(side="left", padx=padx)
            self._buttons.append(b)
            if group is not None:
                group.append(b)
            return b

        addbtn("全选", self._select_all, group=self._need_audit)
        addbtn("全不选", self._select_none, group=self._need_audit)
        chk_ow = ttk.Checkbutton(btns, text="覆盖重做", variable=self.var_overwrite)
        chk_ow.pack(side="left", padx=(14, 4))
        self._inputs.append((chk_ow, "normal"))
        self.btn_gen = addbtn("▶  生成所选章节", self._do_generate, padx=4,
                              group=self._need_audit, accent=True)
        self.btn_genp = addbtn("生成全部未完成", self._do_generate_pending, group=self._need_audit)
        self.btn_verify = addbtn("联网核对补充项", self._do_verify, padx=14, group=self._need_output)
        self.btn_gaps = addbtn("待核清单", self._show_gaps, group=self._need_output)
        self.btn_open = addbtn("打开输出文件夹", self._open_output, group=self._need_output)

        # ===== 进度区 =====
        pf = ttk.Frame(self.root); pf.pack(fill="x", padx=16, pady=(2, 0))
        ttk.Label(pf, textvariable=self.var_phase, anchor="w",
                  foreground=c["accent"]).pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(pf, mode="indeterminate", length=280)
        self.progress.pack(side="right", padx=2)

        # ===== 日志区（深色终端风，压住底部视觉重心）=====
        lg = ttk.LabelFrame(self.root, text="运行日志")
        lg.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(lg, height=8, state="disabled",
                                             font=("Consolas", 9), wrap="word",
                                             background="#1E1E1E", foreground="#D4D4D4",
                                             insertbackground="#D4D4D4",
                                             relief="flat", borderwidth=0, padx=10, pady=8)
        self.log.pack(fill="both", expand=True, padx=4, pady=4)
        self.log.tag_configure("head", foreground="#4FC1FF", font=("Consolas", 9, "bold"))
        self.log.tag_configure("ok", foreground="#4EC9B0")
        self.log.tag_configure("warn", foreground="#DCDCAA")
        self.log.tag_configure("err", foreground="#F48771")
        self.log.tag_configure("muted", foreground="#808080")

    # ---------------- Key ----------------
    def _set_keystat(self, ok: bool):
        self.var_keystat.set("已设置 ✓" if ok else "未设置 ✗")
        if getattr(self, "lbl_keystat", None) is not None:
            self.lbl_keystat.configure(foreground=self.colors["ok"] if ok else self.colors["err"])
        self._update_actions()

    def _ensure_key(self):
        if read_env_key():
            self._set_keystat(True)
        else:
            self._ask_key(initial=True)

    def _ask_key(self, initial=False):
        prompt = ("欢迎使用！首次使用请输入你的 DeepSeek API Key（sk- 开头）。\n"
                  "它会保存在本地 .env，之后不再询问。") if initial else \
                 "请输入新的 DeepSeek API Key（sk- 开头）："
        k = simpledialog.askstring("DeepSeek API Key", prompt, show="*", parent=self.root)
        if k and k.strip():
            write_env_key(k.strip())
            self._set_keystat(True)
            self._log("API Key 已保存到 .env。\n")
        elif initial:
            self._set_keystat(False)
            messagebox.showwarning("提示", "暂未设置 API Key。审计/生成前请点“设置 / 修改密钥”。")

    # ---------------- 偏好持久化 ----------------
    def _load_prefs(self):
        st = load_state()
        cfg_src = ""
        try:
            sd = load_config(self.config_path).source_dir
            if sd.exists() and sd.name != "_未选择资料文件夹":
                cfg_src = str(sd)
        except SystemExit:
            pass
        self.var_source.set(st.get("source_dir") or cfg_src)
        self.var_subject.set(st.get("subject", ""))
        self.var_provider.set(st.get("search_provider", "bing_cn") or "bing_cn")
        self.txt_note.delete("1.0", "end")
        self.txt_note.insert("1.0", st.get("subject_note", ""))

    def _save_prefs(self):
        save_state({
            "source_dir": self.var_source.get().strip(),
            "subject": self.var_subject.get().strip(),
            "subject_note": self.txt_note.get("1.0", "end").strip(),
            "search_provider": self.var_provider.get().strip() or "bing_cn",
        })
        self.var_status.set("设置已保存")
        self._log("设置已保存。\n")

    def _snapshot(self):
        return (self.var_source.get().strip(),
                self.var_subject.get().strip(),
                self.txt_note.get("1.0", "end").strip())

    # ---------------- 文件夹 ----------------
    def _choose_source(self):
        init = self.var_source.get() or str(ROOT)
        d = filedialog.askdirectory(title="选择课程资料文件夹（含 PPT/课本 + 一份大纲）",
                                    initialdir=init)
        if d:
            self.var_source.set(d)
            self._save_prefs()
            self._refresh_chapters()

    def _open_output(self):
        src = self.var_source.get().strip()
        if not src:
            messagebox.showinfo("提示", "请先选择资料文件夹。")
            return
        out = Path(src) / "output"
        if not out.exists():                  # 不主动创建，避免点一下就改资料目录
            if not messagebox.askyesno("还没有输出目录",
                                       f"尚未生成任何输出（{out} 不存在）。\n现在创建该文件夹吗？"):
                return
            out.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(out))            # Windows
        except AttributeError:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, str(out)])

    # ---------------- 章节列表 ----------------
    def _audit_path(self):
        return Path(self.var_source.get().strip()) / "_recite" / "audit.json"

    def _refresh_chapters(self):
        self.tree.delete(*self.tree.get_children())
        self._checked.clear()
        self.chapters = []
        self._set_detail_hint()
        ap = self._audit_path()
        if not ap.exists():
            self.tree.insert("", "end", values=("", "", "", "（尚未审计：请先点『审计资料』）", "", ""))
            self._update_actions()
            return
        try:
            audit = read_json(ap)
        except Exception as e:
            self.tree.insert("", "end", values=("", "", "", f"读取 audit.json 失败：{e}", "", ""))
            self._update_actions()
            return
        out_dir = Path(self.var_source.get().strip()) / "output"
        self.chapters = audit.get("chapters", [])
        done_n = 0
        for pos, ch in enumerate(self.chapters):
            stem = chapter_stem(ch.get("index"), ch.get("title", ""))
            done = (out_dir / f"{stem}.md").exists()
            partial = (out_dir / f"{stem}.partial.md").exists()
            done_n += done
            stat = "● 已生成" if done else ("▲ 截断" if partial else "未生成")
            status_tag = "done" if done else ("partial" if partial else "")
            parity = "even" if pos % 2 == 0 else "odd"
            row_tags = (parity, status_tag) if status_tag else (parity,)
            srcs = ch.get("sources_resolved") or [ch.get("source_resolved") or ch.get("source_file") or "无"]
            self.tree.insert("", "end", iid=str(pos),
                             values=("☐", stat, ch.get("index"), ch.get("title", ""),
                                     "＋".join(srcs), len(ch.get("outline_excerpt", ""))),
                             tags=row_tags)
        subj = self.var_subject.get() or audit.get("subject", "")
        self._update_actions()
        self.var_status.set(f"学科：{subj}　章节：{len(self.chapters)}　已完成：{done_n}")
        if audit.get("warnings"):
            self._log("【审计告警】\n" + "\n".join("  ! " + w for w in audit["warnings"]) + "\n")

    def _on_tree_click(self, event):
        if self.busy:
            return
        iid = self.tree.identify_row(event.y)
        if not iid or not iid.isdigit():
            return
        if self.tree.identify_column(event.x) == "#1":   # 仅点“☑”列才切换勾选
            if iid in self._checked:
                self._checked.discard(iid)
                self.tree.set(iid, "chk", "☐")
            else:
                self._checked.add(iid)
                self.tree.set(iid, "chk", "☑")

    def _on_tree_select(self, _evt=None):
        iid = self.tree.focus()
        if iid and iid.isdigit():
            self._update_detail(int(iid))

    def _update_detail(self, pos):
        if pos >= len(self.chapters):
            return
        ch = self.chapters[pos]
        src = self.var_source.get().strip()
        stem = chapter_stem(ch.get("index"), ch.get("title", ""))
        out = Path(src) / "output"
        md, partial = out / f"{stem}.md", out / f"{stem}.partial.md"
        srcs = ch.get("sources_resolved") or [ch.get("source_resolved") or ch.get("source_file") or "无"]
        n_sup = 0
        if md.exists():
            for ln in md.read_text(encoding="utf-8").splitlines():
                t = ln.strip()
                if t.startswith(("#", ">")):
                    continue
                if "〔网核〕" in t or "〔补〕" in t:
                    n_sup += 1
        status = "已生成" if md.exists() else ("截断残稿(.partial.md)" if partial.exists() else "未生成")
        lines = [
            f"章序：{ch.get('index')}",
            f"章名：{ch.get('title', '')}",
            "",
            "素材文件：", *[f"  · {x}" for x in srcs],
            "",
            f"大纲摘录（{len(ch.get('outline_excerpt', ''))} 字）：",
            (ch.get("outline_excerpt", "")[:400] or "（无）"),
            "",
            f"输出状态：{status}",
            f"〔补/网核〕条目：约 {n_sup}",
            f"提示词：_recite/prompts/{stem}.txt",
        ]
        if ch.get("note"):
            lines += ["", f"审计备注：{ch['note']}"]
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.config(state="disabled")

    def _set_detail_hint(self, text=None):
        if text is None:
            text = ("\n\n        ▤\n\n"
                    "   点选左侧某一章，\n"
                    "   这里显示它的素材、大纲摘录、\n"
                    "   输出状态与待核情况。")
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.tag_configure("center", justify="center", foreground=self.colors["muted"])
        self.detail.tag_add("center", "1.0", "end")
        self.detail.config(state="disabled")

    # ---------------- 上下文：按钮可用性 / 检索源状态 / 安全检查 ----------------
    def _has_any_output(self):
        src = self.var_source.get().strip()
        if not src or not self.chapters:
            return False
        out = Path(src) / "output"
        return any((out / f"{chapter_stem(c.get('index'), c.get('title', ''))}.md").exists()
                   for c in self.chapters)

    def _update_actions(self):
        if self.busy:
            return
        has_key = bool(read_env_key())
        has_src = bool(self.var_source.get().strip())
        audited = bool(self.chapters)
        has_out = self._has_any_output()
        for b in self._buttons:
            b.config(state="normal")
        self.btn_audit.config(state="normal" if (has_key and has_src) else "disabled")
        for b in self._need_audit:
            b.config(state="normal" if (audited and has_key) else "disabled")
        for b in self._need_output:
            b.config(state="normal" if has_out else "disabled")
        hint = ("请先选择资料文件夹" if not has_src else
                "请先设置 DeepSeek Key" if not has_key else
                "请先点『审计资料』" if not audited else None)
        if hint:
            self.var_status.set(hint)

    def _update_search_status(self):
        prov = self.var_provider.get().strip() or "bing_cn"
        if prov in SEARCH_ENV:
            has = bool(os.environ.get(SEARCH_ENV[prov]))
            self.var_searchstat.set(f"检索源 {prov}（需Key·{'已设置' if has else '未设置'}）")
        else:
            self.var_searchstat.set(f"检索源 {prov}（免Key·国内直连）")

    def _check_share_keys(self):
        import re as _re
        d = filedialog.askdirectory(title="选择要检查的文件夹（如准备分享/解压后的包）")
        if not d:
            return
        hits = []
        for p in Path(d).rglob("*"):
            if not p.is_file():
                continue
            if p.name == ".env":
                hits.append(str(p)); continue
            if p.suffix.lower() in (".txt", ".md", ".yaml", ".yml", ".json", ".cfg", ".ini", ".py"):
                try:
                    if p.stat().st_size > 2_000_000:
                        continue
                    t = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if "DEEPSEEK_API_KEY=sk" in t or _re.search(r"sk-[0-9a-fA-F]{24,}", t):
                    hits.append(str(p))
        if hits:
            messagebox.showwarning("发现可能的密钥",
                                   "以下文件可能含密钥，分享前请删除或清空：\n\n" + "\n".join(hits[:20]))
        else:
            messagebox.showinfo("安全检查", "未发现 .env 或 sk- 密钥，可以放心分享。")

    def _selected_positions(self):
        return sorted(int(i) for i in self._checked if i.isdigit())

    def _select_all(self):
        for iid in self.tree.get_children():
            if iid.isdigit():
                self._checked.add(iid)
                self.tree.set(iid, "chk", "☑")

    def _select_none(self):
        for iid in self.tree.get_children():
            if iid.isdigit():
                self.tree.set(iid, "chk", "☐")
        self._checked.clear()

    # ---------------- 运行（后台线程）----------------
    def _set_busy(self, busy):
        self.busy = busy
        if busy:
            for b in self._buttons:
                b.config(state="disabled")
        for w, en in self._inputs:               # 运行时锁定所有输入控件，避免误改
            try:
                w.config(state="disabled" if busy else en)
            except Exception:
                pass
        if busy:
            self.progress.config(mode="indeterminate")
            self.progress.start(12)              # 持续动画 → 不再像“假死”
            self.var_status.set("运行中…（请勿关闭窗口）")
        else:
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
            self.var_phase.set("")
            self._update_actions()               # 按上下文恢复各按钮可用性

    def _run_async(self, fn, on_done=None):
        if self.busy:
            messagebox.showinfo("请稍候", "上一个任务还在运行。")
            return
        self._set_busy(True)
        import sys, traceback

        def task():
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = _QueueWriter(self.q)
            ok, err = True, ""
            try:
                fn()
            except BaseException as e:
                ok = False
                err = str(e) or e.__class__.__name__
                self.q.put(("log", "\n[错误] " + traceback.format_exc()))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                self.q.put(("done", ok, err, on_done))

        threading.Thread(target=task, daemon=True).start()

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log(item[1])
                elif kind == "phase":
                    self.var_phase.set(item[1])
                elif kind == "progress":
                    _, i, total, title = item
                    self.progress.stop()
                    self.progress.config(mode="determinate", maximum=max(total, 1), value=i)
                    self.var_phase.set(f"进度 {i}/{total}：{title}")
                elif kind == "done":
                    _, ok, err, on_done = item
                    self._flush_log()
                    self._set_busy(False)
                    self.var_status.set("✓ 完成" if ok else "✗ 出错（详见日志）")
                    if not ok:
                        messagebox.showerror("出错", err)
                    if on_done:
                        try:
                            on_done(ok)
                        except Exception:
                            pass
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    @staticmethod
    def _line_tag(s: str) -> str:
        t = s.strip()
        if not t:
            return ""
        if t.startswith("==="):
            return "head"
        if t.startswith("[错误]") or "Traceback" in t or "Error" in t:
            return "err"
        if "⚠" in t or "失败" in t or "截断" in t or "告警" in t or t.startswith("!") or " ! " in t:
            return "warn"
        if "✓" in t or "已保存" in t or "完成" in t or t.endswith("OK"):
            return "ok"
        if t.startswith(("·", "•")) or "out_tokens" in t or t.startswith(("[审计]", "[构建]", "[生成]", "[核对]")):
            return "muted"
        return ""

    def _append_log(self, s):
        """按整行着色：缓冲到换行再输出，给不同类型的行加颜色。"""
        self._logbuf += s
        if "\n" not in self._logbuf:
            return
        parts = self._logbuf.split("\n")
        self._logbuf = parts.pop()           # 末尾不完整的一行留着
        self.log.config(state="normal")
        for ln in parts:
            self.log.insert("end", ln + "\n", (self._line_tag(ln),))
        self.log.see("end")
        self.log.config(state="disabled")

    def _flush_log(self):
        if self._logbuf:
            self.log.config(state="normal")
            self.log.insert("end", self._logbuf + "\n", (self._line_tag(self._logbuf),))
            self.log.see("end")
            self.log.config(state="disabled")
            self._logbuf = ""

    def _log(self, s):
        self.q.put(("log", s))

    def _cfg(self, src, subj, note, provider=None):
        cfg = load_config(self.config_path)
        if src:
            cfg.set_source(src)
        cfg.subject = subj
        cfg.subject_note = note
        if provider:
            cfg.search_provider = provider
        return cfg

    def _set_search_key(self):
        prov = self.var_provider.get()
        if prov not in SEARCH_ENV:
            tip = {"bing_cn": "bing_cn（cn.bing.com）国内可直连、无需 Key。",
                   "pubmed": "pubmed（NCBI）学术、国内可直连、无需 Key。",
                   "ddg": "ddg 免费、无需 Key；需安装一次：pip install ddgs"}.get(prov, "该来源无需 Key。")
            messagebox.showinfo("无需 Key", tip)
            return
        env_name = SEARCH_ENV.get(prov)
        k = simpledialog.askstring(f"{prov} 检索 Key",
                                   f"请输入 {prov} 的 API Key：", show="*", parent=self.root)
        if k and k.strip():
            write_env_kv(env_name, k.strip())
            self._log(f"{env_name} 已保存到 .env。\n")
            self._update_search_status()
            messagebox.showinfo("已保存", f"{env_name} 已保存。")

    # ---------------- 三个动作 ----------------
    def _precheck(self):
        if not read_env_key():
            self._ask_key()
            if not read_env_key():
                return False
        if not self.var_source.get().strip():
            messagebox.showwarning("缺少文件夹", "请先选择课程资料文件夹。")
            return False
        return True

    def _do_audit(self):
        if not self._precheck():
            return
        self._save_prefs()
        src, subj, note = self._snapshot()
        self._log("\n========== 开始审计 ==========\n")

        def job():
            self.q.put(("phase", "① 审计资料：让 DeepSeek 把课件对到大纲各章…"))
            cfg = self._cfg(src, subj, note)
            cfg.require_api_key(); cfg.require_source()
            run_audit(cfg)
            self.q.put(("phase", "生成提示词包…"))
            run_build(cfg)

        self._run_async(job, on_done=lambda ok: self._refresh_chapters())

    def _do_generate(self):
        if not self._precheck():
            return
        if not self.chapters:
            messagebox.showwarning("请先审计", "还没有章节列表，请先点“① 审计资料”。")
            return
        sel = self._selected_positions()
        if not sel:
            messagebox.showwarning("未选择", "请在列表里勾选要生成的章节（可“全选”）。")
            return
        idxs = [str(self.chapters[i].get("index")) for i in sel if i < len(self.chapters)]
        only = ",".join(idxs)
        force = self.var_overwrite.get()
        self._save_prefs()
        src, subj, note = self._snapshot()
        self._log(f"\n========== 开始生成 {len(idxs)} 章：{only}{'（覆盖重做）' if force else ''} ==========\n")

        def job():
            cfg = self._cfg(src, subj, note)
            cfg.require_api_key(); cfg.require_source()
            self.q.put(("phase", "准备提示词…"))
            run_build(cfg)                       # 确保最新设置进入提示词
            run_generate(cfg, only=only, force=force,
                         progress_cb=lambda i, t, title: self.q.put(("progress", i, t, title)))

        self._run_async(job, on_done=self._after_generate)

    def _pending_indices(self):
        out_dir = Path(self.var_source.get().strip()) / "output"
        res = []
        for ch in self.chapters:
            stem = chapter_stem(ch.get("index"), ch.get("title", ""))
            if not (out_dir / f"{stem}.md").exists():
                res.append(str(ch.get("index")))
        return res

    def _do_generate_pending(self):
        if not self._precheck():
            return
        if not self.chapters:
            messagebox.showwarning("请先审计", "还没有章节列表，请先点“① 审计资料”。")
            return
        idxs = self._pending_indices()
        if not idxs:
            messagebox.showinfo("已全部完成", "所有章节都已生成。")
            return
        only = ",".join(idxs)
        self._save_prefs()
        src, subj, note = self._snapshot()
        self._log(f"\n========== 生成全部未完成 {len(idxs)} 章：{only} ==========\n")

        def job():
            cfg = self._cfg(src, subj, note)
            cfg.require_api_key(); cfg.require_source()
            self.q.put(("phase", "准备提示词…"))
            run_build(cfg)
            run_generate(cfg, only=only,
                         progress_cb=lambda i, t, title: self.q.put(("progress", i, t, title)))

        self._run_async(job, on_done=self._after_generate)

    def _do_verify(self):
        if not self._precheck():
            return
        if not self.chapters:
            messagebox.showwarning("请先审计", "还没有章节列表，请先点“① 审计资料”。")
            return
        prov = self.var_provider.get().strip() or "bing_cn"
        if prov in SEARCH_ENV:
            try:
                has_key = bool(self._cfg(self.var_source.get().strip(), "", "", provider=prov).search_key())
            except Exception:
                has_key = bool(os.environ.get(SEARCH_ENV[prov]))
            if not has_key:
                messagebox.showwarning("缺少检索 Key",
                                       f"{prov} 需要先点“设置检索Key”填入 Key（或写入 config.yaml）。")
                return
        out_dir = Path(self.var_source.get().strip()) / "output"
        sel = self._selected_positions()
        if sel:
            idxs = [str(self.chapters[i].get("index")) for i in sel if i < len(self.chapters)]
        else:   # 未选则核对所有已生成章节
            idxs = [str(ch.get("index")) for ch in self.chapters
                    if (out_dir / f"{chapter_stem(ch.get('index'), ch.get('title',''))}.md").exists()]
        if not idxs:
            messagebox.showinfo("无可核对", "请先生成章节（或在列表里选择章节）。")
            return
        only = ",".join(idxs)
        self._save_prefs()
        src, subj, note = self._snapshot()
        self._log(f"\n========== 联网核对 {len(idxs)} 章（来源:{prov}）==========\n")

        def job():
            cfg = self._cfg(src, subj, note, provider=prov)
            cfg.require_api_key(); cfg.require_source(); cfg.require_search_key()
            run_verify(cfg, only=only,
                       progress_cb=lambda i, t, title: self.q.put(("progress", i, t, title)))

        self._run_async(job, on_done=lambda ok: self._refresh_chapters())

    # ---------------- 生成后：自检缺口汇总 ----------------
    def _after_generate(self, ok):
        self._refresh_chapters()
        if not ok:
            return
        gaps = self._scan_gaps()
        if gaps:
            self._show_gaps_window(gaps)
        else:
            self._log("本次无 〔补〕 补充项（课件已覆盖大纲要求）。\n")

    def _scan_gaps(self):
        """扫描已生成的 .md，收集 〔补〕 补充项（课件未含、据权威资料补充、需核对），按章汇总。"""
        src = self.var_source.get().strip()
        if not src:
            return {}
        out_dir = Path(src) / "output"
        gaps = {}
        for ch in self.chapters:
            stem = chapter_stem(ch.get("index"), ch.get("title", ""))
            f = out_dir / f"{stem}.md"
            if not f.exists():
                continue
            lines = f.read_text(encoding="utf-8").splitlines()
            hits, in_sec, sec_found = [], False, False
            # 优先只取“## 待核”小节（模型自己汇总的补充清单）
            for ln in lines:
                s = ln.strip()
                if s.startswith("## "):
                    in_sec = "待核" in s
                    sec_found = sec_found or in_sec
                    continue
                if in_sec and s and not s.startswith((">", "#")):
                    item = s.lstrip("-•*　 ").strip()
                    if item and item not in ("无", "无。") and "〔补〕＝" not in item:
                        hits.append(item)
            # 回退：没有待核小节，就扫正文里的 〔补〕 / 残留“未覆盖”
            if not sec_found:
                for ln in lines:
                    s = ln.strip()
                    if not s or s.startswith((">", "#")):
                        continue
                    if "〔补〕＝" in s or "〔补〕=" in s:
                        continue
                    if "〔补〕" in s or "未覆盖" in s:
                        hits.append(s.lstrip("-•*　 ").strip())
            if hits:
                key = f"{str(ch.get('index')).rjust(2)} {ch.get('title','')}"
                gaps[key] = list(dict.fromkeys(hits))   # 去重保序
        return gaps

    def _show_gaps(self):
        if not self.chapters:
            messagebox.showinfo("提示", "请先“① 审计资料”并生成章节。")
            return
        gaps = self._scan_gaps()
        if not gaps:
            messagebox.showinfo("待核清单", "未发现 〔补〕 补充项，或尚无已生成章节。")
            return
        self._show_gaps_window(gaps)

    def _show_gaps_window(self, gaps):
        win = tk.Toplevel(self.root)
        win.title("待核清单 · 〔补〕补充内容（课件未含，可能不准确，请核对）")
        win.geometry("720x520")
        win.minsize(460, 320)
        win.transient(self.root)
        # 先放底部按钮栏（side=bottom 优先占位），避免被上方文本框挤掉
        bar = ttk.Frame(win)
        bar.pack(side="bottom", fill="x", pady=8)
        ttk.Button(bar, text="关闭", command=win.destroy).pack()
        txt = scrolledtext.ScrolledText(win, wrap="word", font=("Microsoft YaHei", 10))
        txt.pack(side="top", fill="both", expand=True, padx=8, pady=(8, 0))
        total = sum(len(v) for v in gaps.values())
        txt.insert("end", f"共 {len(gaps)} 章有 {total} 处 〔补〕 补充内容"
                          f"（课件里没有、据权威资料补充，可能不准确，请核对并以你的补充为准）：\n\n")
        for title, items in gaps.items():
            txt.insert("end", f"■ {title}\n")
            for it in items:
                txt.insert("end", f"    - {it}\n")
            txt.insert("end", "\n")
        txt.config(state="disabled")


def launch(config_path=None):
    # 优先用 CustomTkinter 圆角现代界面；缺失则回退到 ttk(bootstrap/clam) 版
    try:
        import customtkinter  # noqa
    except Exception:
        App(config_path).root.mainloop()
        return
    from .gui_ctk import launch as launch_ctk
    launch_ctk(config_path)


if __name__ == "__main__":
    launch()
