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
from .util import read_json, chapter_stem
# 复用 ttk 版里已写好的本地存储/环境变量助手，避免重复
from .gui import (read_env_key, write_env_kv, write_env_key, load_state, save_state,
                  _QueueWriter, SEARCH_ENV, ENV_PATH)

# ---- 调色板（浅色现代）----
CANVAS = "#EEF1F6"
CARD = "#FFFFFF"
TEXT = "#1F2937"
SUB = "#7B8694"
ACCENT = "#2F6FED"
ACCENT_H = "#2257C8"
OKC = "#16A34A"
WARNC = "#E08613"
ERRC = "#E5484D"
BORDER = "#DCE0E6"
ZEBRA = "#F6F8FB"
HOVER = "#EAF1FF"
SEL = "#DBE8FF"


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
        W, H = min(1180, max(1000, sw - 160)), min(900, max(660, sh - 90))
        self.root.geometry(f"{W}x{H}")
        self.root.minsize(1000, 660)
        try:
            ico = ROOT / "icon.ico"
            if ico.exists():
                self.root.iconbitmap(str(ico))
        except Exception:
            pass

        self.f = ctk.CTkFont("Microsoft YaHei UI", 12)
        self.fb = ctk.CTkFont("Microsoft YaHei UI", 12, "bold")
        self.f_sm = ctk.CTkFont("Microsoft YaHei UI", 11)
        self.f_h1 = ctk.CTkFont("Microsoft YaHei UI", 19, "bold")
        self.f_sec = ctk.CTkFont("Microsoft YaHei UI", 14, "bold")
        self.f_mono = ctk.CTkFont("Consolas", 11)

        self.var_source = tk.StringVar()
        self.var_subject = tk.StringVar()
        self.var_provider = tk.StringVar(value="bing_cn")
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
        self.root.after(120, self._poll)

    # ---------- 小部件助手 ----------
    def _primary(self, parent, text, cmd, width=140):
        b = ctk.CTkButton(parent, text=text, command=cmd, width=width, height=30,
                          corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_H,
                          font=self.fb, text_color="#FFFFFF")
        self._buttons.append(b)
        return b

    def _ghost(self, parent, text, cmd, width=96):
        b = ctk.CTkButton(parent, text=text, command=cmd, width=width, height=30,
                          corner_radius=8, fg_color=CARD, hover_color="#EEF2F8",
                          text_color="#3A4654", border_width=1, border_color=BORDER, font=self.f)
        self._buttons.append(b)
        return b

    def _card(self, parent, **kw):
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1,
                            border_color=BORDER, **kw)

    # ---------- 布局 ----------
    def _build_ui(self):
        root = self.root
        head = ctk.CTkFrame(root, fg_color=CANVAS)
        head.pack(fill="x", padx=22, pady=(10, 1))
        ctk.CTkLabel(head, text="背诵稿生成器", font=self.f_h1, text_color="#111827").pack(side="left")
        ctk.CTkLabel(head, text="  按大纲把课件 / 课本整理成可背诵的 Markdown",
                     font=self.f_sm, text_color=SUB).pack(side="left", pady=(10, 0))

        strip = ctk.CTkFrame(root, fg_color=CANVAS)
        strip.pack(fill="x", padx=22, pady=(0, 6))
        ctk.CTkLabel(strip, text="Key", font=self.f_sm, text_color=SUB).pack(side="left")
        self.lbl_keystat = ctk.CTkLabel(strip, text="未设置 ✗", font=self.fb, text_color=ERRC)
        self.lbl_keystat.pack(side="left", padx=(6, 18))
        self.lbl_search = ctk.CTkLabel(strip, text="", font=self.f_sm, text_color=SUB)
        self.lbl_search.pack(side="left")
        self.lbl_status = ctk.CTkLabel(strip, text="就绪", font=self.f_sm, text_color=SUB)
        self.lbl_status.pack(side="right")

        # ---- 卡片1：资料与设置 ----
        c1 = self._card(root)
        c1.pack(fill="x", padx=22, pady=5)
        ctk.CTkLabel(c1, text="资料与设置", font=self.f_sec, text_color="#111827").pack(
            anchor="w", padx=16, pady=(8, 2))
        r1 = ctk.CTkFrame(c1, fg_color=CARD); r1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(r1, text="资料文件夹", font=self.f, text_color=TEXT, width=80, anchor="w").pack(side="left")
        self.ent_src = ctk.CTkEntry(r1, textvariable=self.var_source, height=30, corner_radius=8,
                                    border_color=BORDER, font=self.f, state="readonly")
        self.ent_src.pack(side="left", fill="x", expand=True, padx=8)
        self.btn_choose = self._ghost(r1, "选择…", self._choose_source, 84); self.btn_choose.pack(side="left")
        self._ghost(r1, "设置 / 修改密钥", self._ask_key, 130).pack(side="left", padx=(8, 0))

        r2 = ctk.CTkFrame(c1, fg_color=CARD); r2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(r2, text="学科名称", font=self.f, text_color=TEXT, width=80, anchor="w").pack(side="left")
        self.ent_subj = ctk.CTkEntry(r2, textvariable=self.var_subject, width=200, height=30,
                                     corner_radius=8, border_color=BORDER, font=self.f)
        self.ent_subj.pack(side="left", padx=8)
        ctk.CTkLabel(r2, text="留空自动判断　·　联网核对来源", font=self.f_sm, text_color=SUB).pack(side="left", padx=(2, 8))
        self.cmb_prov = ctk.CTkOptionMenu(r2, variable=self.var_provider, width=120, height=30,
                                          corner_radius=8, font=self.f, fg_color=CARD, text_color=TEXT,
                                          button_color=ACCENT, button_hover_color=ACCENT_H,
                                          values=["bing_cn", "pubmed", "ddg", "tavily", "serper", "bing"])
        self.cmb_prov.pack(side="left")
        self._ghost(r2, "设置检索Key", self._set_search_key, 110).pack(side="left", padx=8)

        ctk.CTkLabel(c1, text="课程说明 / 整理偏好（可选，因地制宜，不会突破“忠实原文”铁律）",
                     font=self.f_sm, text_color=SUB).pack(anchor="w", padx=16, pady=(4, 0))
        self.txt_note = ctk.CTkTextbox(c1, height=40, corner_radius=8, border_width=1,
                                       border_color=BORDER, font=self.f, fg_color="#FBFCFE")
        self.txt_note.pack(fill="x", padx=16, pady=(2, 4))
        r3 = ctk.CTkFrame(c1, fg_color=CARD); r3.pack(fill="x", padx=16, pady=(0, 10))
        self._ghost(r3, "保存设置", self._save_prefs, 96).pack(side="left")
        self._ghost(r3, "检查分享包是否含密钥", self._check_share_keys, 170).pack(side="left", padx=8)
        ctk.CTkLabel(r3, text=f"密钥保存在 {ENV_PATH}", font=self.f_sm, text_color="#AAB2BD").pack(side="left", padx=4)

        # ---- 卡片2：流程 ----
        c2 = self._card(root)
        c2.pack(fill="both", expand=True, padx=22, pady=5)
        bar = ctk.CTkFrame(c2, fg_color=CARD); bar.pack(fill="x", padx=16, pady=(10, 4))
        self.btn_audit = self._primary(bar, "⟳  审计资料 / 刷新映射", self._do_audit, 190)
        self.btn_audit.pack(side="left")
        ctk.CTkLabel(bar, text="  自动判定学科、把课件对到大纲各章；勾选☑选章，点行看右侧详情",
                     font=self.f_sm, text_color=SUB).pack(side="left", padx=8)

        body = ctk.CTkFrame(c2, fg_color=CARD); body.pack(fill="both", expand=True, padx=16, pady=4)
        left = ctk.CTkFrame(body, fg_color=CARD); left.pack(side="left", fill="both", expand=True)
        self._build_table(left)
        # 详情面板
        self.detail = self._card(body, width=312)
        self.detail.pack(side="right", fill="y", padx=(12, 0))
        self.detail.pack_propagate(False)
        ctk.CTkLabel(self.detail, text="章节详情", font=self.fb, text_color="#111827").pack(
            anchor="w", padx=14, pady=(12, 4))
        self.detail_box = ctk.CTkTextbox(self.detail, corner_radius=0, font=self.f_sm,
                                         fg_color=CARD, border_width=0)
        self.detail_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        btns = ctk.CTkFrame(c2, fg_color=CARD); btns.pack(fill="x", padx=16, pady=(2, 12))
        b = self._ghost(btns, "全选", self._select_all, 70); b.pack(side="left", padx=2); self._need_audit.append(b)
        b = self._ghost(btns, "全不选", self._select_none, 78); b.pack(side="left", padx=2); self._need_audit.append(b)
        self.chk_ow = ctk.CTkCheckBox(btns, text="覆盖重做", variable=self.var_overwrite, font=self.f)
        self.chk_ow.pack(side="left", padx=(14, 6))
        self.btn_gen = self._primary(btns, "▶  生成所选章节", self._do_generate, 150)
        self.btn_gen.pack(side="left", padx=4); self._need_audit.append(self.btn_gen)
        b = self._ghost(btns, "生成全部未完成", self._do_generate_pending, 130); b.pack(side="left", padx=2); self._need_audit.append(b)
        b = self._ghost(btns, "联网核对补充项", self._do_verify, 130); b.pack(side="left", padx=(14, 2)); self._need_output.append(b)
        b = self._ghost(btns, "待核清单", self._show_gaps, 92); b.pack(side="left", padx=2); self._need_output.append(b)
        b = self._ghost(btns, "打开输出文件夹", self._open_output, 124); b.pack(side="left", padx=2); self._need_output.append(b)

        # ---- 进度 ----
        pf = ctk.CTkFrame(root, fg_color=CANVAS); pf.pack(fill="x", padx=24, pady=(4, 2))
        self.lbl_phase = ctk.CTkLabel(pf, text="", font=self.f_sm, text_color=ACCENT, anchor="w")
        self.lbl_phase.pack(side="left", fill="x", expand=True)
        self.progress = ctk.CTkProgressBar(pf, width=280, height=8, corner_radius=4,
                                           progress_color=ACCENT)
        self.progress.set(0)        # 仅运行中显示（见 _set_busy），空闲不占位、不留“蓝点”

        # ---- 日志（深色终端，固定高度，始终可见）----
        lg = self._card(root); lg.pack(fill="x", expand=False, padx=22, pady=(5, 12))
        ctk.CTkLabel(lg, text="运行日志", font=self.fb, text_color="#111827").pack(anchor="w", padx=16, pady=(8, 2))
        self.log = ctk.CTkTextbox(lg, height=128, corner_radius=10, font=self.f_mono,
                                  fg_color="#1E1E1E", text_color="#D4D4D4")
        self.log.pack(fill="x", padx=14, pady=(0, 12))
        self.log.configure(state="disabled")
        t = self.log._textbox
        t.tag_configure("head", foreground="#4FC1FF")
        t.tag_configure("ok", foreground="#4EC9B0")
        t.tag_configure("warn", foreground="#DCDCAA")
        t.tag_configure("err", foreground="#F48771")
        t.tag_configure("muted", foreground="#9AA0A6")

    # ---------- 自定义现代表格 ----------
    TBL = [("☑", 44, "center"), ("状态", 96, "w"), ("章序", 56, "center"),
           ("章名", 130, "w"), ("素材文件", 300, "w"), ("大纲字", 64, "e")]

    def _build_table(self, parent):
        head = ctk.CTkFrame(parent, fg_color="#EAEEF4", corner_radius=8, height=38)
        head.pack(fill="x", pady=(0, 4))
        head.pack_propagate(False)
        for t, w, a in self.TBL:
            ctk.CTkLabel(head, text=t, width=w, font=self.fb, text_color=SUB,
                         anchor={"center": "center", "e": "e"}.get(a, "w")).pack(
                side="left", padx=(10 if t == "☑" else 2, 2))
        self.rows = ctk.CTkScrollableFrame(parent, fg_color=CARD, corner_radius=10)
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
        base = CARD if pos % 2 == 0 else ZEBRA
        row = ctk.CTkFrame(self.rows, fg_color=base, corner_radius=6, height=36)
        row.pack(fill="x", pady=1, padx=1)
        row.pack_propagate(False)
        var = ctk.BooleanVar(value=False)
        cb = ctk.CTkCheckBox(row, text="", width=24, checkbox_width=18, checkbox_height=18,
                             variable=var, command=lambda p=pos: self._toggle(p),
                             fg_color=ACCENT, hover_color=ACCENT_H)
        cb.pack(side="left", padx=(14, 0))
        cells = [(stat, 96, "w", scol), (str(ch.get("index")), 56, "center", TEXT),
                 (ch.get("title", ""), 130, "w", TEXT), (src, 300, "w", "#475467"),
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
            for ln in md.read_text(encoding="utf-8").splitlines():
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
        self.detail_box.insert("1.0", "\n\n   ▤\n\n   点选左侧某一章，\n   这里显示它的素材、大纲摘录、\n   输出状态与待核情况。")
        self.detail_box.configure(state="disabled")

    # ---------- Key / 检索源 / 上下文 ----------
    def _set_keystat(self, ok):
        self.lbl_keystat.configure(text="已设置 ✓" if ok else "未设置 ✗",
                                   text_color=OKC if ok else ERRC)
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
        prov = self.var_provider.get().strip() or "bing_cn"
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
        self.var_provider.set(st.get("search_provider", "bing_cn") or "bing_cn")
        self.txt_note.delete("1.0", "end")
        self.txt_note.insert("1.0", st.get("subject_note", ""))

    def _save_prefs(self):
        save_state({"source_dir": self.var_source.get().strip(),
                    "subject": self.var_subject.get().strip(),
                    "subject_note": self.txt_note.get("1.0", "end").strip(),
                    "search_provider": self.var_provider.get().strip() or "bing_cn"})
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
            subprocess.Popen(["xdg-open", str(out)])

    def _set_search_key(self):
        prov = self.var_provider.get()
        if prov not in SEARCH_ENV:
            tip = {"bing_cn": "bing_cn 国内可直连、无需 Key。", "pubmed": "pubmed 学术、国内可直连、无需 Key。",
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
        prov = self.var_provider.get().strip() or "bing_cn"
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
            for ln in f.read_text(encoding="utf-8").splitlines():
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
        box = ctk.CTkTextbox(win, font=self.f, corner_radius=10)
        box.pack(fill="both", expand=True, padx=12, pady=12)
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
