"""CustomTkinter 版图形界面（圆角卡片 + 现代列表 + 深色终端日志）。
后端逻辑与 ttk 版一致；CustomTkinter 缺失时由 gui.launch() 回退到 ttk 版。"""
import os
import queue
import threading
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from .config import ROOT, load_config
from .audit import run_audit
from .build import run_build
from .generate import run_generate
from .verify import run_verify
from .util import read_json, chapter_stem, read_text_tolerant
from .providers import PROVIDERS, DEFAULT_PROVIDER
# 复用 ttk 版里已写好的本地存储/环境变量助手，避免重复
from .gui import (read_env_key, write_env_kv, write_env_key, load_state, save_state,
                  _QueueWriter, SEARCH_ENV, ENV_PATH)

# ---- 设计令牌：温润“书房伴侣”（纸感暖底 + 古典低饱和强调色）----
# 取自 ui-ux-pro-max → E-Ink/Paper（纸感、阅读优先、衬线）+ Nature Distilled（暖陶土/米白）
# + Notes/Writing（暖墨色 + 强调色落在米色上）。原则：温润纸感、弱边框重留白、
# 衬线标题、单一古典强调色（深松石绿），状态用古典色（暗瓦红/苔绿/赭石）。
CANVAS = "#FAF6EF"        # 主画布：温润纸色（暖米白，模拟纸张、降反光）
CARD = "#FFFDF9"          # 卡片：暖象牙白（比纸面略亮，靠留白与微差区分，不靠硬边框）
SURFACE_SOFT = "#F3ECE0"  # 输入框 / 内嵌区：更暖的纸面
INK = "#33302A"           # 标题（暖近黑、褐调）—— 衬线
TEXT = "#4A443B"          # 正文（暖深灰褐）
SUB = "#8C8273"           # 次要文字（暖灰褐 taupe）
ACCENT = "#2F6B5E"        # 主操作：深松石绿（低饱和、古典装帧感）
ACCENT_H = "#25564B"      # 主操作 hover
OKC = "#4B7A5B"           # 成功 / 已完成：苔绿（不刺眼）
WARNC = "#A9762F"         # 警告 / 截断：赭石
ERRC = "#9C4A3C"          # 错误 / 未设置：暗瓦红（古典）
BORDER = "#E7DECF"        # 极弱暖描边（很少用，避免“框套框”）
LINE = "#EADFCD"          # 分隔线（比 border 更弱）
ZEBRA = "#FBF7EF"         # 斑马行（暖）
HOVER = "#F2EADC"         # 行 hover（暖）
SEL = "#E3EEE7"           # 选中行：极浅松石绿
HEADBG = "#F1E9DA"        # 表头底（暖）
HERO = "#33302A"          # 兼容旧引用（不再用于横幅）
HERO_SUB = "#8C8273"
CHIP_OK = "#FFFDF9"       # 状态改用色点 + 文字，不再用色块
CHIP_ERR = "#FFFDF9"


class App:
    def __init__(self, config_path=None):
        self.config_path = config_path
        self.q = queue.Queue()
        self.busy = False
        self.chapters = []
        self._rows = []
        self._checked = set()
        self._sel_pos = None
        self._logbuf = ""

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.title("背诵稿生成器 · recite_tool")
        self.root.configure(fg_color=CANVAS)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        W, H = min(1200, max(1000, sw - 150)), min(920, max(680, sh - 90))
        self.root.geometry(f"{W}x{H}")
        self.root.minsize(1000, 680)
        try:
            ico = ROOT / "icon.ico"
            if ico.exists():
                self.root.iconbitmap(str(ico))
        except Exception:
            pass
        self._style_titlebar()                       # 标题栏染成纸色，消除冷暖割裂
        self.root.after(60, self._style_titlebar)    # 窗口完全实现后再染一次，确保生效

        self.f = ctk.CTkFont("Microsoft YaHei UI", 12)
        self.fb = ctk.CTkFont("Microsoft YaHei UI", 12, "bold")
        self.f_sm = ctk.CTkFont("Microsoft YaHei UI", 11)
        self.f_h1 = ctk.CTkFont("Microsoft YaHei UI", 19, "bold")
        self.f_sec = ctk.CTkFont("Microsoft YaHei UI", 13, "bold")
        self.f_mono = ctk.CTkFont("Consolas", 11)
        # 衬线（书卷气）：标题与阅读区用宋体，正文/控件保持无衬线以保证屏幕清晰度。
        self.serif_name = self._pick_serif()
        self.f_serif_h1 = ctk.CTkFont(self.serif_name, 24, "bold")
        self.f_serif_sec = ctk.CTkFont(self.serif_name, 16, "bold")
        self.f_read = ctk.CTkFont(self.serif_name, 13)
        self.f_read_b = ctk.CTkFont(self.serif_name, 13, "bold")
        self._collapse = {}

        self.var_source = tk.StringVar()
        self.var_subject = tk.StringVar()
        self.var_provider = tk.StringVar(value=DEFAULT_PROVIDER)
        self.var_overwrite = tk.BooleanVar(value=False)
        self._buttons = []
        self._need_audit = []
        self._need_output = []

        self._build_ui()
        self._load_prefs()
        self._ensure_key()
        self.var_provider.trace_add("write", lambda *a: self._update_search_status())
        self._refresh_chapters()
        self._update_search_status()
        self._update_actions()
        # 已配置过资料目录则收起“资料与设置”，第一眼留给内容（章节 + 详情预览）。
        if self.var_source.get().strip():
            self._set_collapse("settings", False, animate=False)
        # 从任务栏还原时补染标题栏，避免标题栏闪回系统冷色（最小化/还原本身由 DWM 动画驱动）。
        self.root.bind("<Map>", lambda e: self.root.after(1, self._style_titlebar))
        self.root.after(120, self._poll)

    # ---------- 小部件助手 ----------
    def _pick_serif(self):
        """挑一款本机可用的中文衬线（书卷气）；缺失则回退到宋体。"""
        import tkinter.font as tkfont
        try:
            fams = set(tkfont.families())
        except Exception:
            return "宋体"
        for name in ["Noto Serif SC", "Source Han Serif SC", "思源宋体", "华文中宋",
                     "STZhongsong", "仿宋", "FangSong", "新宋体", "宋体", "SimSun"]:
            if name in fams:
                return name
        return "宋体"

    def _style_titlebar(self):
        """Windows 11：把原生标题栏染成纸色、文字染成墨色，与暖色正文连成一片。
        旧系统 / 非 Windows 上 DWM 调用会失败，静默跳过（标题栏保持系统默认）。"""
        try:
            import ctypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()

            def _ref(h):  # "#RRGGBB" -> COLORREF(0x00BBGGRR)
                r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
                return ctypes.c_int((b << 16) | (g << 8) | r)

            dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
            for attr, col in ((35, _ref(CANVAS)), (36, _ref(INK))):  # 35=CAPTION_COLOR, 36=TEXT_COLOR
                dwm(hwnd, attr, ctypes.byref(col), ctypes.sizeof(col))
        except Exception:
            pass

    def _primary(self, parent, text, cmd, width=140):
        # 主操作：深松石绿实底，柔和大圆角；像盖在纸上的印章。
        b = ctk.CTkButton(parent, text=text, command=cmd, width=width, height=34,
                          corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_H,
                          font=self.fb, text_color="#FBF8F2")
        self._buttons.append(b)
        return b

    def _ghost(self, parent, text, cmd, width=96):
        # 次操作：暖纸面、无硬边框，hover 微暖；去“工业感”。
        b = ctk.CTkButton(parent, text=text, command=cmd, width=width, height=34,
                          corner_radius=10, fg_color=SURFACE_SOFT, hover_color=HOVER,
                          text_color=TEXT, border_width=0, font=self.f)
        self._buttons.append(b)
        return b

    def _card(self, parent, **kw):
        # 卡片：暖象牙白、大圆角、极弱暖描边（近无），靠留白区分层级而非硬框。
        color = kw.pop("fg_color", CARD)
        border = kw.pop("border_color", LINE)
        bw = kw.pop("border_width", 1)
        return ctk.CTkFrame(parent, fg_color=color, corner_radius=16, border_width=bw,
                            border_color=border, **kw)

    def _section(self, parent, title, hint=""):
        """衬线分区标题 + 简短说明（无编号、无营销副标）。"""
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(14, 4))
        ctk.CTkLabel(head, text=title, font=self.f_serif_sec, text_color=INK).pack(side="left")
        if hint:
            ctk.CTkLabel(head, text=hint, font=self.f_sm, text_color=SUB).pack(
                side="left", padx=12)
        return head

    def _collapsible(self, parent, key, title, hint="", start_open=True):
        """可折叠卡片：点表头即时收起/展开。
        说明：曾试过逐帧高度缓动，但 CTkScrollableFrame 在反复 reflow 下会留残影/空白
        （Tk 重绘模型限制），故采用即时切换 + 一次干净重绘，确保不出现幽灵残像。"""
        card = self._card(parent)
        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=22, pady=(13, 3))
        caret = ctk.CTkLabel(hdr, text="", font=self.f_sm, text_color=SUB, width=16)
        caret.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(hdr, text=title, font=self.f_serif_sec, text_color=INK).pack(side="left")
        if hint:
            ctk.CTkLabel(hdr, text=hint, font=self.f_sm, text_color=SUB).pack(side="left", padx=12)
        body = ctk.CTkFrame(card, fg_color="transparent")
        self._collapse[key] = {"caret": caret, "body": body, "open": None}
        for w in (hdr, caret):
            w.bind("<Button-1>", lambda e, k=key: self._toggle_collapse(k))
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
        self._set_collapse(key, start_open)
        return card, body

    def _set_collapse(self, key, open_, animate=False):
        c = self._collapse.get(key)
        if not c or c["open"] == open_:
            return
        c["open"] = open_
        c["caret"].configure(text="▾" if open_ else "▸")
        if open_:
            c["body"].pack(fill="x", pady=(0, 8))
        else:
            c["body"].pack_forget()
        self._clean_redraw()                     # 切换后强制一次干净重绘，消除 reflow 残影

    def _clean_redraw(self):
        """折叠/展开使下方滚动表 reflow，强制重算并清屏，避免 Tk 留下幽灵像素。"""
        try:
            self.root.update_idletasks()
            self.rows.update_idletasks()         # 让滚动表重算 scrollregion 并重绘
        except Exception:
            pass

    def _toggle_collapse(self, key):
        c = self._collapse.get(key)
        if c:
            self._set_collapse(key, not c["open"])

    # ---------- 布局 ----------
    def _build_ui(self):
        root = self.root
        # 顶部：衬线标题 + 右侧状态；无横幅、无标语、无硬分割线，靠留白分隔。
        header = ctk.CTkFrame(root, fg_color=CANVAS)
        header.pack(fill="x", padx=30, pady=(20, 8))
        ctk.CTkLabel(header, text="背诵稿生成器", font=self.f_serif_h1,
                     text_color=INK).pack(side="left")
        state = ctk.CTkFrame(header, fg_color="transparent")
        state.pack(side="right")
        # 状态用“色点 + 文字”，古典低饱和色，不用色块药丸。
        self.lbl_keystat = ctk.CTkLabel(state, text="● API Key 未设置", font=self.fb,
                                        text_color=ERRC, fg_color="transparent")
        self.lbl_keystat.pack(side="right", padx=(18, 0))
        self.lbl_search = ctk.CTkLabel(state, text="", font=self.f_sm, text_color=SUB)
        self.lbl_search.pack(side="right", padx=(18, 0))
        self.lbl_status = ctk.CTkLabel(state, text="准备就绪", font=self.f_sm, text_color=SUB)
        self.lbl_status.pack(side="right")

        content = ctk.CTkFrame(root, fg_color=CANVAS)

        # ---- 资料与设置（低频，可折叠；已配置后默认收起，让内容区占主视觉）----
        c1, sbody = self._collapsible(content, "settings", "资料与设置",
                                      "选择资料文件夹、学科与生成偏好 · 点此展开/收起")
        c1.pack(fill="x", pady=(0, 14))

        r1 = ctk.CTkFrame(sbody, fg_color="transparent")
        r1.pack(fill="x", padx=22, pady=5)
        ctk.CTkLabel(r1, text="资料文件夹", font=self.fb, text_color=TEXT,
                     width=90, anchor="w").pack(side="left")
        self.ent_src = ctk.CTkEntry(r1, textvariable=self.var_source, height=36, corner_radius=9,
                                    fg_color=SURFACE_SOFT, text_color=TEXT, border_width=0,
                                    font=self.f, state="readonly")
        self.ent_src.pack(side="left", fill="x", expand=True, padx=(8, 10))
        self.btn_choose = self._ghost(r1, "选择资料", self._choose_source, 92)
        self.btn_choose.pack(side="left")
        self._ghost(r1, "设置 / 修改密钥", self._ask_key, 128).pack(side="left", padx=(8, 0))

        r2 = ctk.CTkFrame(sbody, fg_color="transparent")
        r2.pack(fill="x", padx=22, pady=5)
        ctk.CTkLabel(r2, text="学科名称", font=self.fb, text_color=TEXT,
                     width=90, anchor="w").pack(side="left")
        self.ent_subj = ctk.CTkEntry(r2, textvariable=self.var_subject, width=200, height=36,
                                     corner_radius=9, fg_color=SURFACE_SOFT, text_color=TEXT,
                                     border_width=0, font=self.f)
        self.ent_subj.pack(side="left", padx=(8, 10))
        ctk.CTkLabel(r2, text="留空将自动判断", font=self.f_sm, text_color=SUB).pack(side="left", padx=(0, 18))
        ctk.CTkLabel(r2, text="联网核对来源", font=self.f_sm, text_color=SUB).pack(side="left", padx=(0, 8))
        self.cmb_prov = ctk.CTkOptionMenu(r2, variable=self.var_provider, width=126, height=36,
                                          corner_radius=9, font=self.f, fg_color=SURFACE_SOFT,
                                          text_color=TEXT, button_color=ACCENT,
                                          button_hover_color=ACCENT_H, dropdown_fg_color=CARD,
                                          values=PROVIDERS)
        self.cmb_prov.pack(side="left")
        self._ghost(r2, "设置检索 Key", self._set_search_key, 116).pack(side="left", padx=8)

        ctk.CTkLabel(sbody, text="课程说明 / 整理偏好（可选；辅助组织表达，不会突破“忠实原文”铁律）",
                     font=self.f_sm, text_color=SUB).pack(anchor="w", padx=22, pady=(8, 2))
        self.txt_note = ctk.CTkTextbox(sbody, height=34, corner_radius=9, border_width=0,
                                       font=self.f, fg_color=SURFACE_SOFT, text_color=TEXT)
        self.txt_note.pack(fill="x", padx=22, pady=(2, 8))
        r3 = ctk.CTkFrame(sbody, fg_color="transparent")
        r3.pack(fill="x", padx=22, pady=(0, 14))
        self._ghost(r3, "保存设置", self._save_prefs, 96).pack(side="left")
        self._ghost(r3, "检查分享包是否含密钥", self._check_share_keys, 168).pack(side="left", padx=8)
        ctk.CTkLabel(r3, text=f"密钥仅保存在本机：{ENV_PATH}", font=self.f_sm,
                     text_color=SUB).pack(side="left", padx=4)

        # ---- 章节与详情（内容主舞台）----
        c2 = self._card(content)
        c2.pack(fill="both", expand=True)
        self._section(c2, "章节", "审计资料 → 选择章节 → 生成背诵稿 → 联网核对")

        bar = ctk.CTkFrame(c2, fg_color="transparent")
        bar.pack(fill="x", padx=22, pady=(0, 10))
        self.btn_audit = self._primary(bar, "审计资料 / 刷新映射", self._do_audit, 180)
        self.btn_audit.pack(side="left")
        ctk.CTkLabel(bar, text="把课件与课本对应到大纲各章；点击某一行查看右侧详情。",
                     font=self.f_sm, text_color=SUB).pack(side="left", padx=12)

        body = ctk.CTkFrame(c2, fg_color="transparent")
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        self._build_table(left)

        # 右侧详情/预览：放大、衬线、宽行距，像一本排印精良的书页。
        self.detail = self._card(body, width=460, fg_color=SURFACE_SOFT, border_width=0)
        self.detail.pack(side="right", fill="y", padx=(18, 0))
        self.detail.pack_propagate(False)
        ctk.CTkLabel(self.detail, text="章节详情", font=self.f_serif_sec,
                     text_color=INK).pack(anchor="w", padx=20, pady=(16, 4))
        self.detail_box = ctk.CTkTextbox(self.detail, corner_radius=10, font=self.f_read,
                                         fg_color=CARD, text_color=TEXT, border_width=0,
                                         wrap="word")
        self.detail_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        try:
            self.detail_box._textbox.configure(spacing1=5, spacing2=4, spacing3=7,
                                               padx=14, pady=12)
        except Exception:
            pass

        btns = ctk.CTkFrame(c2, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=22, pady=(2, 16))
        b = self._ghost(btns, "全选", self._select_all, 68)
        b.pack(side="left", padx=2); self._need_audit.append(b)
        b = self._ghost(btns, "全不选", self._select_none, 74)
        b.pack(side="left", padx=2); self._need_audit.append(b)
        self.chk_ow = ctk.CTkCheckBox(btns, text="覆盖重做", variable=self.var_overwrite,
                                       font=self.f, text_color=TEXT, fg_color=ACCENT,
                                       hover_color=ACCENT_H, border_color=SUB)
        self.chk_ow.pack(side="left", padx=(12, 6))
        self.btn_gen = self._primary(btns, "生成所选章节", self._do_generate, 132)
        self.btn_gen.pack(side="left", padx=2); self._need_audit.append(self.btn_gen)
        b = self._ghost(btns, "生成全部未完成", self._do_generate_pending, 122)
        b.pack(side="left", padx=2); self._need_audit.append(b)
        ctk.CTkFrame(btns, width=1, height=22, fg_color=LINE).pack(side="left", padx=10)
        b = self._ghost(btns, "联网核对补充项", self._do_verify, 124)
        b.pack(side="left", padx=2); self._need_output.append(b)
        b = self._ghost(btns, "待核清单", self._show_gaps, 90)
        b.pack(side="left", padx=2); self._need_output.append(b)
        b = self._ghost(btns, "打开输出文件夹", self._open_output, 118)
        b.pack(side="left", padx=2); self._need_output.append(b)

        body.pack(side="top", fill="both", expand=True, padx=22, pady=(0, 6))

        # ---- 运行反馈：仅在任务进行中显示进度条，空闲时不挤占空间。 ----
        pf = ctk.CTkFrame(root, fg_color=CANVAS)
        self.lbl_phase = ctk.CTkLabel(pf, text="", font=self.f_sm, text_color=ACCENT, anchor="w")
        self.lbl_phase.pack(side="left", fill="x", expand=True)
        self.progress = ctk.CTkProgressBar(pf, width=280, height=8, corner_radius=4,
                                           progress_color=ACCENT, fg_color=SURFACE_SOFT)
        self.progress.set(0)

        # ---- 运行日志：暖纸面、安静、按行着色；不喧宾夺主。 ----
        lg = ctk.CTkFrame(root, fg_color="transparent")
        lg.pack(side="bottom", fill="x", expand=False, padx=30, pady=(4, 16))
        ctk.CTkLabel(lg, text="运行日志", font=self.f_sm, text_color=SUB).pack(
            anchor="w", padx=2, pady=(0, 2))
        self.log = ctk.CTkTextbox(lg, height=52, corner_radius=10, font=self.f_mono,
                                  fg_color=SURFACE_SOFT, text_color=TEXT, border_width=0)
        self.log.pack(fill="x")
        self.log.configure(state="disabled")
        t = self.log._textbox
        t.tag_configure("head", foreground=ACCENT)
        t.tag_configure("ok", foreground=OKC)
        t.tag_configure("warn", foreground=WARNC)
        t.tag_configure("err", foreground=ERRC)
        t.tag_configure("muted", foreground=SUB)

        # 固定区先占位，工作区才会在它们之上弹性缩放；避免低分辨率下遮住操作按钮。
        pf.pack(side="bottom", fill="x", padx=30, pady=(4, 2))
        content.pack(side="top", fill="both", expand=True, padx=30, pady=(4, 4))

    # ---------- 自定义现代表格 ----------
    TBL = [("☑", 44, "center"), ("状态", 92, "w"), ("章序", 58, "center"),
           ("章名", 142, "w"), ("素材文件", 300, "w"), ("大纲字", 64, "e")]

    def _build_table(self, parent):
        head = ctk.CTkFrame(parent, fg_color=HEADBG, corner_radius=10, height=42)
        head.pack(fill="x", pady=(0, 6))
        head.pack_propagate(False)
        for t, w, a in self.TBL:
            ctk.CTkLabel(head, text=t, width=w, font=self.fb, text_color=SUB,
                         anchor={"center": "center", "e": "e"}.get(a, "w")).pack(
                side="left", padx=(10 if t == "☑" else 2, 2))
        self.rows = ctk.CTkScrollableFrame(parent, fg_color=CARD, corner_radius=10,
                                            border_width=0)
        self.rows.pack(fill="both", expand=True)

    def _refresh_chapters(self):
        for w in self.rows.winfo_children():    # 清空所有行/占位标签，避免残留
            w.destroy()
        self._rows = []
        self._checked = set()
        self._sel_pos = None
        self._set_detail_hint()
        ap = Path(self.var_source.get().strip()) / "_recite" / "audit.json"
        if not ap.exists():
            self.chapters = []
            ctk.CTkLabel(self.rows, text="尚未审计：请先点『审计资料』", font=self.f,
                         text_color=SUB).pack(pady=20)
            self._update_actions()
            return
        try:
            audit = read_json(ap)
        except Exception as e:
            self.chapters = []
            ctk.CTkLabel(self.rows, text=f"读取 audit.json 失败：{e}", text_color=ERRC).pack(pady=20)
            self._update_actions()
            return
        out = Path(self.var_source.get().strip()) / "output"
        self.chapters = audit.get("chapters", [])
        done_n = 0
        for pos, ch in enumerate(self.chapters):
            stem = chapter_stem(ch.get("index"), ch.get("title", ""))
            done = (out / f"{stem}.md").exists()
            partial = (out / f"{stem}.partial.md").exists()
            done_n += done
            stat, scol = ("● 已生成", OKC) if done else (("▲ 截断", WARNC) if partial else ("未生成", SUB))
            srcs = ch.get("sources_resolved") or [ch.get("source_resolved") or ch.get("source_file") or "无"]
            self._add_row(pos, stat, scol, ch, "＋".join(srcs))
        subj = self.var_subject.get() or audit.get("subject", "")
        self._update_actions()
        self.lbl_status.configure(text=f"学科：{subj}  章节：{len(self.chapters)}  已完成：{done_n}")
        if audit.get("warnings"):
            self._log("【审计告警】\n" + "\n".join("  ! " + w for w in audit["warnings"]) + "\n")

    def _add_row(self, pos, stat, scol, ch, src):
        base = ZEBRA if pos % 2 else CARD
        row = ctk.CTkFrame(self.rows, fg_color=base, corner_radius=8, height=40)
        row.pack(fill="x", pady=2, padx=2)
        row.pack_propagate(False)
        var = ctk.BooleanVar(value=False)
        cb = ctk.CTkCheckBox(row, text="", width=24, checkbox_width=18, checkbox_height=18,
                             variable=var, command=lambda p=pos: self._toggle(p),
                             fg_color=ACCENT, hover_color=ACCENT_H, border_color=SUB)
        cb.pack(side="left", padx=(14, 0))
        cells = [(stat, 96, "w", scol), (str(ch.get("index")), 56, "center", TEXT),
                 (ch.get("title", ""), 130, "w", INK), (src, 300, "w", SUB),
                 (str(len(ch.get("outline_excerpt", ""))), 64, "e", SUB)]
        labels = []
        for txt, w, a, col in cells:
            lb = ctk.CTkLabel(row, text=txt, width=w, anchor={"center": "center", "e": "e"}.get(a, "w"),
                              font=self.f, text_color=col)
            lb.pack(side="left", padx=2)
            labels.append(lb)
        rec = {"frame": row, "var": var, "pos": pos, "base": base, "labels": labels}
        self._rows.append(rec)
        for wdg in [row] + labels:
            wdg.bind("<Button-1>", lambda e, p=pos: self._select_row(p))
            wdg.bind("<Enter>", lambda e, p=pos: self._hover(p, True))
            wdg.bind("<Leave>", lambda e, p=pos: self._hover(p, False))

    def _row_color(self, pos):
        if pos == self._sel_pos:
            return SEL
        return self._rows[pos]["base"]

    def _hover(self, pos, on):
        if pos == self._sel_pos:
            return
        self._rows[pos]["frame"].configure(fg_color=HOVER if on else self._rows[pos]["base"])

    def _select_row(self, pos):
        if self._sel_pos is not None and self._sel_pos < len(self._rows):
            self._rows[self._sel_pos]["frame"].configure(fg_color=self._rows[self._sel_pos]["base"])
        self._sel_pos = pos
        self._rows[pos]["frame"].configure(fg_color=SEL)
        self._update_detail(pos)

    def _toggle(self, pos):
        if self._rows[pos]["var"].get():
            self._checked.add(pos)
        else:
            self._checked.discard(pos)

    def _selected_positions(self):
        return sorted(self._checked)

    def _select_all(self):
        self._checked = set(range(len(self._rows)))
        for r in self._rows:
            r["var"].set(True)

    def _select_none(self):
        self._checked = set()
        for r in self._rows:
            r["var"].set(False)

    # ---------- 详情 ----------
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
            for ln in read_text_tolerant(md).splitlines():
                t = ln.strip()
                if not t.startswith(("#", ">")) and ("〔网核〕" in t or "〔补〕" in t):
                    n_sup += 1
        status = "已生成" if md.exists() else ("截断残稿(.partial.md)" if partial.exists() else "未生成")
        lines = [f"章序：{ch.get('index')}", f"章名：{ch.get('title','')}", "",
                 "素材文件：", *[f"  · {x}" for x in srcs], "",
                 f"大纲摘录（{len(ch.get('outline_excerpt',''))} 字）：",
                 (ch.get("outline_excerpt", "")[:400] or "（无）"), "",
                 f"输出状态：{status}", f"〔补/网核〕条目：约 {n_sup}",
                 f"提示词：_recite/prompts/{stem}.txt"]
        if ch.get("note"):
            lines += ["", f"审计备注：{ch['note']}"]
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", "\n".join(lines))
        self.detail_box.configure(state="disabled")

    def _set_detail_hint(self):
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", "\n\n点选左侧某一章，\n\n这里会显示它的素材来源、\n大纲摘录、输出状态与待核情况。")
        self.detail_box.configure(state="disabled")

    # ---------- Key / 检索源 / 上下文 ----------
    def _set_keystat(self, ok):
        self.lbl_keystat.configure(text="● API Key 已设置" if ok else "● API Key 未设置",
                                   text_color=OKC if ok else ERRC, fg_color="transparent")
        self._update_actions()

    def _ensure_key(self):
        if read_env_key():
            self._set_keystat(True)
        else:
            self._ask_key(initial=True)

    def _ask_key(self, initial=False):
        prompt = "首次使用请输入你的 DeepSeek API Key（sk- 开头），保存在本地 .env：" if initial \
            else "请输入新的 DeepSeek API Key（sk- 开头）："
        k = simpledialog.askstring("DeepSeek API Key", prompt, show="*", parent=self.root)
        if k and k.strip():
            write_env_key(k.strip())
            self._set_keystat(True)
            self._log("API Key 已保存到 .env。\n")
        elif initial:
            self._set_keystat(False)
            messagebox.showwarning("提示", "暂未设置 API Key。审计/生成前请点“设置 / 修改密钥”。")

    def _update_search_status(self):
        prov = self.var_provider.get().strip() or DEFAULT_PROVIDER
        if prov in SEARCH_ENV:
            has = bool(os.environ.get(SEARCH_ENV[prov]))
            self.lbl_search.configure(text=f"检索源 {prov}（需Key·{'已设置' if has else '未设置'}）")
        else:
            self.lbl_search.configure(text=f"检索源 {prov}（免Key·国内直连）")

    def _has_any_output(self):
        src = self.var_source.get().strip()
        if not src or not self.chapters:
            return False
        out = Path(src) / "output"
        return any((out / f"{chapter_stem(c.get('index'), c.get('title',''))}.md").exists()
                   for c in self.chapters)

    def _update_actions(self):
        if self.busy:
            return
        has_key = bool(read_env_key())
        has_src = bool(self.var_source.get().strip())
        audited = bool(self.chapters)
        has_out = self._has_any_output()
        for b in self._buttons:
            b.configure(state="normal")
        self.btn_audit.configure(state="normal" if (has_key and has_src) else "disabled")
        for b in self._need_audit:
            b.configure(state="normal" if (audited and has_key) else "disabled")
        for b in self._need_output:
            b.configure(state="normal" if has_out else "disabled")
        hint = ("请先选择资料文件夹" if not has_src else "请先设置 DeepSeek Key"
                if not has_key else "请先点『审计资料』" if not audited else None)
        if hint:
            self.lbl_status.configure(text=hint)

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
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if "DEEPSEEK_API_KEY=sk" in txt or _re.search(r"sk-[0-9a-fA-F]{24,}", txt):
                    hits.append(str(p))
        if hits:
            messagebox.showwarning("发现可能的密钥",
                                   "以下文件可能含密钥，分享前请删除/清空：\n\n" + "\n".join(hits[:20]))
        else:
            messagebox.showinfo("安全检查", "未发现 .env 或 sk- 密钥，可以放心分享。")

    # ---------- 偏好 / 文件夹 ----------
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
        self.var_provider.set(st.get("search_provider") or DEFAULT_PROVIDER)
        self.txt_note.delete("1.0", "end")
        self.txt_note.insert("1.0", st.get("subject_note", ""))

    def _save_prefs(self):
        save_state({"source_dir": self.var_source.get().strip(),
                    "subject": self.var_subject.get().strip(),
                    "subject_note": self.txt_note.get("1.0", "end").strip(),
                    "search_provider": self.var_provider.get().strip() or DEFAULT_PROVIDER})
        self.lbl_status.configure(text="设置已保存")
        self._log("设置已保存。\n")

    def _snapshot(self):
        return (self.var_source.get().strip(), self.var_subject.get().strip(),
                self.txt_note.get("1.0", "end").strip())

    def _choose_source(self):
        d = filedialog.askdirectory(title="选择课程资料文件夹（含 PPT/课本 + 一份大纲）",
                                    initialdir=self.var_source.get() or str(ROOT))
        if d:
            self.var_source.set(d)
            self._save_prefs()
            self._refresh_chapters()
            self._update_actions()

    def _open_output(self):
        src = self.var_source.get().strip()
        if not src:
            messagebox.showinfo("提示", "请先选择资料文件夹。")
            return
        out = Path(src) / "output"
        if not out.exists():
            if not messagebox.askyesno("还没有输出目录", f"尚未生成任何输出（{out} 不存在）。现在创建吗？"):
                return
            out.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(out))
        except AttributeError:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, str(out)])

    def _set_search_key(self):
        prov = self.var_provider.get()
        if prov not in SEARCH_ENV:
            tip = {"bing_cn": "bing_cn＝authoritative 的旧名（权威来源聚合），免 Key、国内可直连。",
                   "pubmed": "pubmed 学术、国内可直连、无需 Key。",
                   "ddg": "ddg 免费、无需 Key；需 pip install ddgs"}.get(prov, "该来源无需 Key。")
            messagebox.showinfo("无需 Key", tip)
            return
        env_name = SEARCH_ENV[prov]
        k = simpledialog.askstring(f"{prov} 检索 Key", f"请输入 {prov} 的 API Key：", show="*", parent=self.root)
        if k and k.strip():
            write_env_kv(env_name, k.strip())
            self._update_search_status()
            messagebox.showinfo("已保存", f"{env_name} 已保存。")

    # ---------- 运行 / 日志 ----------
    def _cfg(self, src, subj, note, provider=None):
        cfg = load_config(self.config_path)
        if src:
            cfg.set_source(src)
        cfg.subject = subj
        cfg.subject_note = note
        if provider:
            cfg.search_provider = provider
        return cfg

    def _set_busy(self, busy):
        self.busy = busy
        if busy:
            for b in self._buttons:
                b.configure(state="disabled")
            for w in (self.ent_subj, self.cmb_prov, self.txt_note, self.chk_ow, self.btn_choose):
                try: w.configure(state="disabled")
                except Exception: pass
            self.progress.pack(side="right", pady=4)      # 运行中才显示进度条
            self.progress.configure(mode="indeterminate"); self.progress.start()
            self.lbl_status.configure(text="运行中…（请勿关闭窗口）")
        else:
            for w in (self.ent_subj, self.txt_note, self.chk_ow, self.btn_choose):
                try: w.configure(state="normal")
                except Exception: pass
            try: self.cmb_prov.configure(state="normal")
            except Exception: pass
            self.progress.stop(); self.progress.configure(mode="determinate"); self.progress.set(0)
            self.progress.pack_forget()                    # 空闲隐藏，避免残留“蓝点”
            self.lbl_phase.configure(text="")
            self._update_actions()

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
                    self.lbl_phase.configure(text=item[1])
                elif kind == "progress":
                    _, i, total, title = item
                    self.progress.stop(); self.progress.configure(mode="determinate")
                    self.progress.set(i / max(total, 1))
                    self.lbl_phase.configure(text=f"进度 {i}/{total}：{title}")
                elif kind == "done":
                    _, ok, err, on_done = item
                    self._flush_log()
                    self._set_busy(False)
                    self.lbl_status.configure(text="✓ 完成" if ok else "✗ 出错（详见日志）")
                    if not ok:
                        messagebox.showerror("出错", err)
                    if on_done:
                        try: on_done(ok)
                        except Exception: pass
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    @staticmethod
    def _line_tag(s):
        t = s.strip()
        if not t:
            return ""
        if t.startswith("==="):
            return "head"
        if t.startswith("[错误]") or "Traceback" in t or "Error" in t:
            return "err"
        if "⚠" in t or "失败" in t or "截断" in t or "告警" in t or " ! " in t:
            return "warn"
        if "✓" in t or "已保存" in t or "完成" in t:
            return "ok"
        if t.startswith(("·", "•")) or "out_tokens" in t or t.startswith(("[审计]", "[构建]", "[生成]", "[核对]")):
            return "muted"
        return ""

    def _append_log(self, s):
        self._logbuf += s
        if "\n" not in self._logbuf:
            return
        parts = self._logbuf.split("\n")
        self._logbuf = parts.pop()
        self.log.configure(state="normal")
        for ln in parts:
            self.log._textbox.insert("end", ln + "\n", self._line_tag(ln))
        self.log.see("end")
        self.log.configure(state="disabled")

    def _flush_log(self):
        if self._logbuf:
            self.log.configure(state="normal")
            self.log._textbox.insert("end", self._logbuf + "\n", self._line_tag(self._logbuf))
            self.log.see("end")
            self.log.configure(state="disabled")
            self._logbuf = ""

    def _log(self, s):
        self.q.put(("log", s))

    # ---------- 动作 ----------
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
            self.q.put(("phase", "审计资料：让 DeepSeek 把课件对到大纲各章…"))
            cfg = self._cfg(src, subj, note)
            cfg.require_api_key(); cfg.require_source()
            run_audit(cfg)
            self.q.put(("phase", "生成提示词包…"))
            run_build(cfg)

        self._run_async(job, on_done=lambda ok: self._refresh_chapters())

    def _do_generate(self):
        if not self._precheck():
            return
        sel = self._selected_positions()
        if not sel:
            messagebox.showwarning("未选择", "请在表格里勾选要生成的章节（可“全选”）。")
            return
        idxs = [str(self.chapters[i].get("index")) for i in sel if i < len(self.chapters)]
        only = ",".join(idxs)
        force = self.var_overwrite.get()
        self._save_prefs()
        src, subj, note = self._snapshot()
        self._log(f"\n========== 开始生成 {len(idxs)} 章{'（覆盖重做）' if force else ''} ==========\n")

        def job():
            cfg = self._cfg(src, subj, note)
            cfg.require_api_key(); cfg.require_source()
            self.q.put(("phase", "准备提示词…"))
            run_build(cfg)
            run_generate(cfg, only=only, force=force,
                         progress_cb=lambda i, t, ti: self.q.put(("progress", i, t, ti)))

        self._run_async(job, on_done=self._after_generate)

    def _do_generate_pending(self):
        if not self._precheck():
            return
        out = Path(self.var_source.get().strip()) / "output"
        idxs = [str(ch.get("index")) for ch in self.chapters
                if not (out / f"{chapter_stem(ch.get('index'), ch.get('title',''))}.md").exists()]
        if not idxs:
            messagebox.showinfo("已全部完成", "所有章节都已生成。")
            return
        only = ",".join(idxs)
        self._save_prefs()
        src, subj, note = self._snapshot()
        self._log(f"\n========== 生成全部未完成 {len(idxs)} 章 ==========\n")

        def job():
            cfg = self._cfg(src, subj, note)
            cfg.require_api_key(); cfg.require_source()
            self.q.put(("phase", "准备提示词…"))
            run_build(cfg)
            run_generate(cfg, only=only,
                         progress_cb=lambda i, t, ti: self.q.put(("progress", i, t, ti)))

        self._run_async(job, on_done=self._after_generate)

    def _do_verify(self):
        if not self._precheck():
            return
        prov = self.var_provider.get().strip() or DEFAULT_PROVIDER
        if prov in SEARCH_ENV and not os.environ.get(SEARCH_ENV[prov]):
            try:
                ok = bool(self._cfg(self.var_source.get().strip(), "", "", provider=prov).search_key())
            except Exception:
                ok = False
            if not ok:
                messagebox.showwarning("缺少检索 Key", f"{prov} 需要先点“设置检索Key”。")
                return
        out = Path(self.var_source.get().strip()) / "output"
        sel = self._selected_positions()
        if sel:
            idxs = [str(self.chapters[i].get("index")) for i in sel if i < len(self.chapters)]
        else:
            idxs = [str(ch.get("index")) for ch in self.chapters
                    if (out / f"{chapter_stem(ch.get('index'), ch.get('title',''))}.md").exists()]
        if not idxs:
            messagebox.showinfo("无可核对", "请先生成章节（或勾选章节）。")
            return
        only = ",".join(idxs)
        self._save_prefs()
        src, subj, note = self._snapshot()
        self._log(f"\n========== 联网核对 {len(idxs)} 章（来源:{prov}）==========\n")

        def job():
            cfg = self._cfg(src, subj, note, provider=prov)
            cfg.require_api_key(); cfg.require_source(); cfg.require_search_key()
            run_verify(cfg, only=only,
                       progress_cb=lambda i, t, ti: self.q.put(("progress", i, t, ti)))

        self._run_async(job, on_done=lambda ok: self._refresh_chapters())

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
        src = self.var_source.get().strip()
        if not src:
            return {}
        out = Path(src) / "output"
        gaps = {}
        for ch in self.chapters:
            f = out / f"{chapter_stem(ch.get('index'), ch.get('title',''))}.md"
            if not f.exists():
                continue
            hits, in_sec, sec_found = [], False, False
            for ln in read_text_tolerant(f).splitlines():
                s = ln.strip()
                if s.startswith("## "):
                    in_sec = "待核" in s
                    sec_found = sec_found or in_sec
                    continue
                if in_sec and s and not s.startswith((">", "#")):
                    it = s.lstrip("-•*　 ").strip()
                    if it and it not in ("无", "无。") and "〔补〕＝" not in it:
                        hits.append(it)
            if hits:
                gaps[f"{str(ch.get('index')).rjust(2)} {ch.get('title','')}"] = list(dict.fromkeys(hits))
        return gaps

    def _show_gaps(self):
        if not self.chapters:
            messagebox.showinfo("提示", "请先审计并生成章节。")
            return
        gaps = self._scan_gaps()
        if not gaps:
            messagebox.showinfo("待核清单", "未发现 〔补〕 补充项，或尚无已生成章节。")
            return
        self._show_gaps_window(gaps)

    def _show_gaps_window(self, gaps):
        win = ctk.CTkToplevel(self.root)
        win.title("待核清单 · 〔补〕补充内容（课件未含，可能不准确，请核对）")
        win.geometry("720x520")
        win.configure(fg_color=CANVAS)
        box = ctk.CTkTextbox(win, font=self.f_read, corner_radius=12, fg_color=CARD,
                             text_color=TEXT, border_width=0, wrap="word")
        box.pack(fill="both", expand=True, padx=16, pady=16)
        try:
            box._textbox.configure(spacing1=5, spacing3=6, padx=14, pady=12)
        except Exception:
            pass
        total = sum(len(v) for v in gaps.values())
        box.insert("end", f"共 {len(gaps)} 章有 {total} 处 〔补〕 补充内容（可能不准确，请核对）：\n\n")
        for title, items in gaps.items():
            box.insert("end", f"■ {title}\n")
            for it in items:
                box.insert("end", f"    - {it}\n")
            box.insert("end", "\n")
        box.configure(state="disabled")
        ctk.CTkButton(win, text="关闭", command=win.destroy, width=100,
                      fg_color=ACCENT, hover_color=ACCENT_H).pack(pady=(0, 12))


def launch(config_path=None):
    App(config_path).root.mainloop()


if __name__ == "__main__":
    launch()
