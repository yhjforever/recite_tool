"""图形界面（Tkinter，无需终端）：首启询问并保存 API Key；选择资料文件夹；
填写学科与课程说明；审计映射；按章勾选生成 Markdown 背诵稿。"""
import os
import json
import queue
import threading
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, scrolledtext

from .config import ROOT, load_config
from .audit import run_audit
from .build import run_build
from .generate import run_generate
from .verify import run_verify
from .util import read_json, chapter_stem

SEARCH_ENV = {"tavily": "TAVILY_API_KEY", "serper": "SERPER_API_KEY", "bing": "BING_API_KEY"}

ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / "gui_state.json"

# macOS 系统自带字体：日志区等宽用 Menlo，中文界面用苹方
MONO_FONT = ("Menlo", 12)
UI_FONT = ("PingFang SC", 13)


def _open_in_file_manager(path: str) -> None:
    """在「访达」中打开目录。"""
    subprocess.Popen(["open", path])


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


class App:
    def __init__(self, config_path=None):
        self.config_path = config_path
        self.q = queue.Queue()
        self.busy = False
        self.chapters = []        # 来自 audit.json
        self._buttons = []
        self._inputs = []         # 运行时需要一并禁用的输入控件：(widget, 启用态)

        self.root = tk.Tk()
        self.root.title("背诵稿生成器 · recite_tool")
        self.root.geometry("960x720")
        self.root.minsize(820, 600)
        try:
            png = ROOT / "icon.png"
            if png.exists():
                # 用 PhotoImage(PNG) 作窗口图标；需保留引用，否则被 GC 后图标丢失。
                self._icon_img = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

        self.var_source = tk.StringVar()
        self.var_subject = tk.StringVar()
        self.var_provider = tk.StringVar(value="bing_cn")
        self.var_overwrite = tk.BooleanVar(value=False)
        self.var_keystat = tk.StringVar(value="未设置 ✗")
        self.var_status = tk.StringVar(value="就绪")

        self._build_ui()
        self._load_prefs()
        self._ensure_key()        # 首次启动：询问并保存 Key
        self._refresh_chapters()
        self.root.after(120, self._poll)

    # ---------------- UI 布局 ----------------
    def _build_ui(self):
        pad = dict(padx=8, pady=4)

        # 设置区
        s = ttk.LabelFrame(self.root, text="设置")
        s.pack(fill="x", **pad)

        r1 = ttk.Frame(s); r1.pack(fill="x", padx=8, pady=4)
        ttk.Label(r1, text="DeepSeek API Key：").pack(side="left")
        self.lbl_keystat = ttk.Label(r1, textvariable=self.var_keystat, foreground="#c0392b")
        self.lbl_keystat.pack(side="left")
        b = ttk.Button(r1, text="设置 / 修改密钥", command=self._ask_key); b.pack(side="left", padx=8)
        self._buttons.append(b)

        r2 = ttk.Frame(s); r2.pack(fill="x", padx=8, pady=4)
        ttk.Label(r2, text="资料文件夹：").pack(side="left")
        e = ttk.Entry(r2, textvariable=self.var_source, state="readonly")
        e.pack(side="left", fill="x", expand=True, padx=4)
        b = ttk.Button(r2, text="选择…", command=self._choose_source); b.pack(side="left")
        self._buttons.append(b)

        r3 = ttk.Frame(s); r3.pack(fill="x", padx=8, pady=4)
        ttk.Label(r3, text="学科名称：").pack(side="left")
        ent_subj = ttk.Entry(r3, textvariable=self.var_subject, width=24)
        ent_subj.pack(side="left", padx=4)
        self._inputs.append((ent_subj, "normal"))
        ttk.Label(r3, text="（留空则自动判断）").pack(side="left")

        r4 = ttk.Frame(s); r4.pack(fill="x", padx=8, pady=4)
        ttk.Label(r4, text="课程说明 / 整理偏好（可选，因地制宜，不会突破“忠实原文”铁律）：").pack(anchor="w")
        self.txt_note = tk.Text(r4, height=3, wrap="word")
        self.txt_note.pack(fill="x", pady=2)
        self._inputs.append((self.txt_note, "normal"))

        r5 = ttk.Frame(s); r5.pack(fill="x", padx=8, pady=4)
        ttk.Label(r5, text="联网核对来源：").pack(side="left")
        cmb = ttk.Combobox(r5, textvariable=self.var_provider, width=10, state="readonly",
                           values=["bing_cn", "pubmed", "ddg", "tavily", "serper", "bing"])
        cmb.pack(side="left", padx=4)
        self._inputs.append((cmb, "readonly"))
        b = ttk.Button(r5, text="设置检索Key", command=self._set_search_key)
        b.pack(side="left", padx=4); self._buttons.append(b)
        ttk.Label(r5, text="（bing_cn/pubmed 国内直连免Key；tavily/serper/bing 需Key）").pack(side="left", padx=4)

        r6 = ttk.Frame(s); r6.pack(fill="x", padx=8, pady=4)
        b = ttk.Button(r6, text="保存设置", command=self._save_prefs); b.pack(side="left")
        self._buttons.append(b)
        ttk.Label(r6, text="（设置会自动记住，下次打开沿用）").pack(side="left", padx=8)

        # 流程区
        a = ttk.LabelFrame(self.root, text="流程")
        a.pack(fill="both", expand=True, **pad)

        top = ttk.Frame(a); top.pack(fill="x", padx=8, pady=4)
        b = ttk.Button(top, text="① 审计资料 / 刷新映射", command=self._do_audit)
        b.pack(side="left"); self._buttons.append(b)
        ttk.Label(top, text="先审计：自动判定学科、把课件对到大纲各章").pack(side="left", padx=8)

        mid = ttk.Frame(a); mid.pack(fill="both", expand=True, padx=8, pady=4)
        ttk.Label(mid, text="② 选择要生成的章节（单击行即勾选/取消☑，无需按 Ctrl）：").pack(anchor="w")
        lf = ttk.Frame(mid); lf.pack(fill="both", expand=True)
        cols = ("chk", "stat", "idx", "title", "src", "oc")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", height=10,
                                 selectmode="none")
        for c, txt, w, anchor in [("chk", "☑", 34, "center"), ("stat", "状态", 64, "center"),
                                  ("idx", "章序", 48, "center"), ("title", "章名", 150, "w"),
                                  ("src", "素材文件", 280, "w"), ("oc", "大纲字", 56, "e")]:
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c in ("src", "title")))
        self.tree.tag_configure("done", foreground="#0a7")
        self.tree.tag_configure("partial", foreground="#d35400")
        self.tree.tag_configure("warn", foreground="#c0392b")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.config(yscrollcommand=sb.set)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self._checked = set()            # 勾选的行 iid

        btns = ttk.Frame(mid); btns.pack(fill="x", pady=4)

        def addbtn(text, cmd, padx=2):
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side="left", padx=padx)
            self._buttons.append(b)
            return b

        addbtn("全选", self._select_all)
        addbtn("全不选", self._select_none)
        chk_ow = ttk.Checkbutton(btns, text="覆盖重做", variable=self.var_overwrite)
        chk_ow.pack(side="left", padx=(12, 2))
        self._inputs.append((chk_ow, "normal"))
        addbtn("③ 生成所选", self._do_generate, padx=4)
        addbtn("生成全部未完成", self._do_generate_pending)
        addbtn("④ 联网核对", self._do_verify, padx=12)
        addbtn("待核清单(补充)", self._show_gaps)
        addbtn("打开输出文件夹", self._open_output)

        # 日志区
        lg = ttk.LabelFrame(self.root, text="运行日志")
        lg.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(lg, height=10, state="disabled",
                                             font=MONO_FONT, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        sbar = ttk.Frame(self.root); sbar.pack(fill="x")
        ttk.Label(sbar, textvariable=self.var_status, relief="sunken",
                  anchor="w").pack(fill="x")

    # ---------------- Key ----------------
    def _set_keystat(self, ok: bool):
        self.var_keystat.set("已设置 ✓" if ok else "未设置 ✗")
        if getattr(self, "lbl_keystat", None) is not None:
            self.lbl_keystat.configure(foreground="#0a7" if ok else "#c0392b")

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
        _open_in_file_manager(str(out))

    # ---------------- 章节列表 ----------------
    def _audit_path(self):
        return Path(self.var_source.get().strip()) / "_recite" / "audit.json"

    def _refresh_chapters(self):
        self.tree.delete(*self.tree.get_children())
        self._checked.clear()
        self.chapters = []
        ap = self._audit_path()
        if not ap.exists():
            self.tree.insert("", "end", values=("", "", "", "（尚未审计：请先点①审计资料）", "", ""))
            return
        try:
            audit = read_json(ap)
        except Exception as e:
            self.tree.insert("", "end", values=("", "", "", f"读取 audit.json 失败：{e}", "", ""))
            return
        out_dir = Path(self.var_source.get().strip()) / "output"
        self.chapters = audit.get("chapters", [])
        done_n = 0
        for pos, ch in enumerate(self.chapters):
            stem = chapter_stem(ch.get("index"), ch.get("title", ""))
            done = (out_dir / f"{stem}.md").exists()
            partial = (out_dir / f"{stem}.partial.md").exists()
            done_n += done
            stat = "已生成" if done else ("截断" if partial else "未生成")
            tag = "done" if done else ("partial" if partial else "")
            srcs = ch.get("sources_resolved") or [ch.get("source_resolved") or ch.get("source_file") or "无"]
            self.tree.insert("", "end", iid=str(pos),
                             values=("☐", stat, ch.get("index"), ch.get("title", ""),
                                     "＋".join(srcs), len(ch.get("outline_excerpt", ""))),
                             tags=(tag,) if tag else ())
        subj = self.var_subject.get() or audit.get("subject", "")
        self.var_status.set(f"学科：{subj}　章节：{len(self.chapters)}　已完成：{done_n}")
        if audit.get("warnings"):
            self._log("【审计告警】\n" + "\n".join("  ! " + w for w in audit["warnings"]) + "\n")

    def _on_tree_click(self, event):
        if self.busy:
            return
        iid = self.tree.identify_row(event.y)
        if not iid or not iid.isdigit():
            return
        if iid in self._checked:
            self._checked.discard(iid)
            self.tree.set(iid, "chk", "☐")
        else:
            self._checked.add(iid)
            self.tree.set(iid, "chk", "☑")

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
        for b in self._buttons:
            b.config(state="disabled" if busy else "normal")
        for w, en in self._inputs:               # 运行时锁定所有输入控件，避免误改
            try:
                w.config(state="disabled" if busy else en)
            except Exception:
                pass
        if busy:
            self.var_status.set("运行中…（请勿关闭窗口）")

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
                if item[0] == "log":
                    self._append_log(item[1])
                elif item[0] == "done":
                    _, ok, err, on_done = item
                    self._set_busy(False)
                    self.var_status.set("完成" if ok else "出错")
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

    def _append_log(self, s):
        self.log.config(state="normal")
        self.log.insert("end", s)
        self.log.see("end")
        self.log.config(state="disabled")

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
            cfg = self._cfg(src, subj, note)
            cfg.require_api_key(); cfg.require_source()
            run_audit(cfg)
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
            run_build(cfg)                       # 确保最新设置进入提示词
            run_generate(cfg, only=only, force=force)

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
            run_build(cfg)
            run_generate(cfg, only=only)

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
            run_verify(cfg, only=only)

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
        txt = scrolledtext.ScrolledText(win, wrap="word", font=UI_FONT)
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
    App(config_path).root.mainloop()


if __name__ == "__main__":
    launch()
