"""Web 版图形界面（pywebview + WebView2 + HTML/CSS/JS）。
后端逻辑与 ttk / CustomTkinter 版完全一致：复用 recite.* 各后端模块与 gui.py 的本地存储助手；
前端只负责呈现与交互（暖纸质感 + 衬线 + CSS 平滑动画，避开 Tk 重绘残影）。
WebView2 不可用时由 gui.launch() 回退到 CustomTkinter / ttk 版。"""
import os
import sys
import json
import time
import threading
import subprocess
import traceback
from pathlib import Path

from .config import ROOT, load_config
from .audit import run_audit
from .build import run_build
from .generate import run_generate
from .verify import run_verify
from .util import read_json, chapter_stem
# 复用 ttk 版里已写好的本地存储 / 环境变量助手，避免重复实现
from .gui import (read_env_key, write_env_kv, write_env_key, load_state, save_state,
                  SEARCH_ENV, ENV_PATH)

CANVAS = "#FAF6EF"   # 纸色（与前端一致，用于窗口底色与标题栏染色）
INK = "#33302A"      # 墨色
TITLE = "背诵稿生成器 · recite_tool"


def _html_path():
    here = Path(__file__).resolve().parent
    p = here / "web" / "index.html"
    if p.exists():
        return p
    mp = getattr(sys, "_MEIPASS", None)        # PyInstaller 解包目录
    if mp:
        cand = Path(mp) / "recite" / "web" / "index.html"
        if cand.exists():
            return cand
    return p


class _JsWriter:
    """把后端 print 输出按行推给前端日志。"""
    def __init__(self, api):
        self.api = api
        self.buf = ""

    def write(self, s):
        if not s:
            return 0
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.api._log(line)
        return len(s)

    def flush(self):
        if self.buf:
            self.api._log(self.buf)
            self.buf = ""


class Api:
    def __init__(self, config_path=None):
        self.config_path = config_path
        self.window = None
        self.busy = False
        self.source = ""
        self.subject = ""
        self.note = ""
        self.provider = "bing_cn"
        self._max = False                 # 自绘标题栏的最大化状态
        self._restore = None              # 还原用的窗口矩形 (x,y,w,h)
        self._events = []                 # 待前端轮询取走的事件（日志/阶段/进度/完成）
        self._evlock = threading.Lock()

    # ---------- 与前端通信：缓冲事件，前端定时 drain ----------
    # 关键：不再从后台线程高频 window.evaluate_js() 推送（那会让 pywebview/pythonnet
    # 递归崩溃、界面卡死）。改为后端只往缓冲区追加事件，前端用 JS->Python 轮询取走（稳）。
    def _push(self, ev):
        with self._evlock:
            self._events.append(ev)

    def drain(self):
        """前端每 ~150ms 调一次：取走并清空缓冲的事件。"""
        with self._evlock:
            evs = self._events
            self._events = []
        return evs

    def _log(self, line):
        self._push({"t": "log", "v": line})

    def _phase(self, text):
        self._push({"t": "phase", "v": text})

    def _progress(self, i, total, title):
        self._push({"t": "progress", "i": i, "total": total, "title": title})

    # ---------- 配置 ----------
    def _cfg(self, src, subj, note, provider=None):
        cfg = load_config(self.config_path)
        if src:
            cfg.set_source(src)
        cfg.subject = subj
        cfg.subject_note = note
        if provider:
            cfg.search_provider = provider
        return cfg

    def _sync(self, source=None, subject=None, note=None, provider=None):
        if source is not None:
            self.source = source
        if subject is not None:
            self.subject = subject
        if note is not None:
            self.note = note
        if provider is not None:
            self.provider = provider

    def _persist(self):
        save_state({"source_dir": self.source.strip(), "subject": self.subject.strip(),
                    "subject_note": self.note.strip(), "search_provider": self.provider or "bing_cn"})

    # ---------- 章节 / 详情 ----------
    def _audit_path(self):
        return Path(self.source.strip()) / "_recite" / "audit.json" if self.source.strip() else None

    def _out_dir(self):
        return Path(self.source.strip()) / "output"

    def _chapters(self):
        ap = self._audit_path()
        if not ap or not ap.exists():
            return [], {}
        try:
            audit = read_json(ap)
        except Exception:
            return [], {}
        return audit.get("chapters", []), audit

    def _status_of(self, ch):
        out = self._out_dir()
        stem = chapter_stem(ch.get("index"), ch.get("title", ""))
        if (out / f"{stem}.md").exists():
            return "done"
        if (out / f"{stem}.partial.md").exists():
            return "partial"
        return "none"

    def _refresh_payload(self, include_warnings=False):
        chapters, audit = self._chapters()
        rows, done_n = [], 0
        for ch in chapters:
            st = self._status_of(ch)
            done_n += (st == "done")
            srcs = ch.get("sources_resolved") or [ch.get("source_resolved") or ch.get("source_file") or "无"]
            rows.append({"index": ch.get("index"), "title": ch.get("title", ""),
                         "status": st, "src": "＋".join(srcs),
                         "outline_len": len(ch.get("outline_excerpt", ""))})
        subj = self.subject.strip() or audit.get("subject", "")
        has_output = any(self._status_of(c) == "done" for c in chapters)
        payload = {"chapters": rows, "subject_label": subj or "—",
                   "n_chapters": len(rows), "n_done": done_n, "has_output": has_output}
        payload["warnings"] = audit.get("warnings", []) if include_warnings else []
        return payload

    def get_detail(self, index):
        chapters, _ = self._chapters()
        ch = next((c for c in chapters if str(c.get("index")) == str(index)), None)
        if ch is None:
            return None
        out = self._out_dir()
        stem = chapter_stem(ch.get("index"), ch.get("title", ""))
        md, partial = out / f"{stem}.md", out / f"{stem}.partial.md"
        srcs = ch.get("sources_resolved") or [ch.get("source_resolved") or ch.get("source_file") or "无"]
        n_sup = 0
        if md.exists():
            for ln in md.read_text(encoding="utf-8").splitlines():
                t = ln.strip()
                if not t.startswith(("#", ">")) and ("〔网核〕" in t or "〔补〕" in t):
                    n_sup += 1
        status = "done" if md.exists() else ("partial" if partial.exists() else "none")
        return {"index": ch.get("index"), "title": ch.get("title", ""), "sources": srcs,
                "outline_excerpt": (ch.get("outline_excerpt", "")[:400]),
                "outline_len": len(ch.get("outline_excerpt", "")),
                "status": status, "n_sup": n_sup,
                "prompt_path": f"_recite/prompts/{stem}.txt", "note": ch.get("note", "")}

    def _scan_gaps(self):
        chapters, _ = self._chapters()
        if not self.source.strip():
            return {}
        out = self._out_dir()
        gaps = {}
        for ch in chapters:
            f = out / f"{chapter_stem(ch.get('index'), ch.get('title',''))}.md"
            if not f.exists():
                continue
            lines = f.read_text(encoding="utf-8").splitlines()
            hits, in_sec, sec_found = [], False, False
            for ln in lines:
                s = ln.strip()
                if s.startswith("## "):
                    in_sec = "待核" in s
                    sec_found = sec_found or in_sec
                    continue
                if in_sec and s and not s.startswith((">", "#")):
                    it = s.lstrip("-•*　 ").strip()
                    if it and it not in ("无", "无。") and "〔补〕＝" not in it:
                        hits.append(it)
            if not sec_found:
                for ln in lines:
                    s = ln.strip()
                    if not s or s.startswith((">", "#")) or "〔补〕＝" in s or "〔补〕=" in s:
                        continue
                    if "〔补〕" in s or "未覆盖" in s:
                        hits.append(s.lstrip("-•*　 ").strip())
            if hits:
                key = f"{str(ch.get('index')).rjust(2)} {ch.get('title','')}"
                gaps[key] = list(dict.fromkeys(hits))
        return gaps

    def scan_gaps(self):
        return {"gaps": self._scan_gaps()}

    # ---------- 初始化 / 偏好 ----------
    def get_init(self):
        st = load_state()
        cfg_src = ""
        try:
            sd = load_config(self.config_path).source_dir
            if sd.exists() and sd.name != "_未选择资料文件夹":
                cfg_src = str(sd)
        except SystemExit:
            pass
        self.source = st.get("source_dir") or cfg_src or ""
        self.subject = st.get("subject", "")
        self.note = st.get("subject_note", "")
        self.provider = st.get("search_provider", "bing_cn") or "bing_cn"
        d = {"source": self.source, "subject": self.subject, "note": self.note,
             "provider": self.provider, "has_key": bool(read_env_key()), "env_path": str(ENV_PATH),
             "providers": ["bing_cn", "pubmed", "ddg", "tavily", "serper", "bing"],
             "keyless_providers": ["bing_cn", "pubmed", "ddg"],
             "search_status": self._search_status(self.provider)}
        d.update(self._refresh_payload(include_warnings=True))
        return d

    def _search_status(self, prov):
        prov = (prov or "bing_cn").strip() or "bing_cn"
        if prov in SEARCH_ENV:
            has = bool(os.environ.get(SEARCH_ENV[prov]))
            return f"检索源 {prov}（需Key·{'已设置' if has else '未设置'}）"
        return f"检索源 {prov}（免Key·国内直连）"

    def get_search_status(self, provider):
        self.provider = provider
        return {"status": self._search_status(provider)}

    def search_key_info(self, provider):
        if provider in SEARCH_ENV:
            return {"keyless": False}
        tip = {"bing_cn": "bing_cn（cn.bing.com）国内可直连、无需 Key。",
               "pubmed": "pubmed（NCBI）学术、国内可直连、无需 Key。",
               "ddg": "ddg 免费、无需 Key；需安装一次：pip install ddgs"}.get(provider, "该来源无需 Key。")
        return {"keyless": True, "msg": tip}

    def save_prefs(self, source, subject, note, provider):
        self._sync(source, subject, note, provider)
        self._persist()
        return {"ok": True, "search_status": self._search_status(provider)}

    def set_key(self, key):
        if key and key.strip():
            write_env_key(key.strip())
            self._log("API Key 已保存到 .env。")
        return {"ok": True, "has_key": bool(read_env_key())}

    def set_search_key(self, provider, key):
        if provider in SEARCH_ENV and key and key.strip():
            env_name = SEARCH_ENV[provider]
            write_env_kv(env_name, key.strip())
            self._log(f"{env_name} 已保存到 .env。")
            return {"ok": True, "status": self._search_status(provider), "msg": f"{env_name} 已保存"}
        return {"ok": False, "status": self._search_status(provider), "msg": "未保存"}

    # ---------- 文件夹 / 输出 / 安全检查 ----------
    def choose_source(self):
        try:
            import webview
            init = self.source or str(ROOT)
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG, directory=init)
        except Exception:
            res = None
        if not res:
            return {"chosen": False}
        self.source = res[0]
        self._persist()
        d = {"chosen": True, "source": self.source}
        d.update(self._refresh_payload(include_warnings=True))
        return d

    def open_output(self, create):
        if not self.source.strip():
            return {"no_source": True}
        out = self._out_dir()
        if not out.exists():
            if not create:
                return {"need_create": True, "msg": f"尚未生成任何输出（{out} 不存在）。"}
            out.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(out))                       # Windows
        except AttributeError:
            subprocess.Popen(["xdg-open", str(out)])
        return {"ok": True}

    # ---------- 自绘标题栏：窗口控制 ----------
    def win_minimize(self):
        try:
            self.window.minimize()
        except Exception:
            pass

    def win_close(self):
        try:
            self.window.destroy()
        except Exception:
            pass

    def win_toggle_max(self):
        """假最大化：缩放到所在显示器的工作区（避让任务栏、不溢出屏幕边缘）。
        无边框窗口用系统 maximize 会盖住任务栏并溢出，故改用工作区矩形。"""
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            hwnd = u.FindWindowW(None, TITLE)
            if not hwnd:
                raise RuntimeError("no hwnd")

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            SWP_NOZORDER = 0x0004
            if not self._max:
                r = wintypes.RECT(); u.GetWindowRect(hwnd, ctypes.byref(r))
                self._restore = (r.left, r.top, r.right - r.left, r.bottom - r.top)
                mi = MONITORINFO(); mi.cbSize = ctypes.sizeof(MONITORINFO)
                u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))  # NEAREST
                w = mi.rcWork
                u.SetWindowPos(hwnd, 0, w.left, w.top, w.right - w.left, w.bottom - w.top, SWP_NOZORDER)
                self._max = True
            else:
                if self._restore:
                    x, y, ww, hh = self._restore
                    u.SetWindowPos(hwnd, 0, x, y, ww, hh, SWP_NOZORDER)
                self._max = False
        except Exception:
            try:                                   # 兜底：系统 maximize/restore
                (self.window.restore if self._max else self.window.maximize)()
                self._max = not self._max
            except Exception:
                pass
        return {"maximized": self._max}

    def check_share_keys(self):
        import re as _re
        try:
            import webview
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:
            res = None
        if not res:
            return {"chosen": False}
        d = res[0]
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
        return {"chosen": True, "hits": hits}

    # ---------- 任务执行（后台线程 + 推送）----------
    def _run_task(self, kind, job, on_done):
        if self.busy:
            return {"started": False, "busy": True}
        self.busy = True
        self._push({"t": "busy", "v": True})

        def task():
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = _JsWriter(self)
            ok, err = True, ""
            try:
                job()
            except BaseException as e:
                ok = False
                err = str(e) or e.__class__.__name__
                self._log("\n[错误] " + traceback.format_exc())
            finally:
                try:
                    sys.stdout.flush()
                except Exception:
                    pass
                sys.stdout, sys.stderr = old_out, old_err
                try:
                    payload = on_done(ok, err)
                except Exception:
                    payload = {"ok": ok, "err": err, "kind": kind}
                self.busy = False
                self._push({"t": "done", "payload": payload})

        threading.Thread(target=task, daemon=True).start()
        return {"started": True}

    def _precheck(self, source):
        if not read_env_key():
            return {"need_key": True}
        if not source or not source.strip():
            return {"need_source": True}
        return None

    def run_audit(self, source, subject, note):
        self._sync(source, subject, note)
        bad = self._precheck(source)
        if bad:
            return bad
        self._persist()
        self._log("\n========== 开始审计 ==========")

        def job():
            self._phase("审计资料：让 DeepSeek 把课件对到大纲各章…")
            cfg = self._cfg(source, subject, note)
            cfg.require_api_key(); cfg.require_source()
            run_audit(cfg)
            self._phase("生成提示词包…")
            run_build(cfg)

        def done(ok, err):
            p = self._refresh_payload(include_warnings=True)
            p.update(ok=ok, err=err, kind="audit")
            return p

        return self._run_task("audit", job, done)

    def run_generate(self, indices, force, source, subject, note):
        self._sync(source, subject, note)
        bad = self._precheck(source)
        if bad:
            return bad
        if not indices:
            return {"none_selected": True}
        only = ",".join(str(i) for i in indices)
        self._persist()
        self._log(f"\n========== 开始生成 {len(indices)} 章{'（覆盖重做）' if force else ''} ==========")

        def job():
            cfg = self._cfg(source, subject, note)
            cfg.require_api_key(); cfg.require_source()
            self._phase("准备提示词…")
            run_build(cfg)
            run_generate(cfg, only=only, force=bool(force),
                         progress_cb=lambda i, t, ti: self._progress(i, t, ti))

        def done(ok, err):
            p = self._refresh_payload()
            p.update(ok=ok, err=err, kind="generate", gaps=(self._scan_gaps() if ok else {}))
            return p

        return self._run_task("generate", job, done)

    def run_generate_pending(self, source, subject, note):
        self._sync(source, subject, note)
        bad = self._precheck(source)
        if bad:
            return bad
        chapters, _ = self._chapters()
        out = self._out_dir()
        idxs = [str(ch.get("index")) for ch in chapters
                if not (out / f"{chapter_stem(ch.get('index'), ch.get('title',''))}.md").exists()]
        if not idxs:
            return {"all_done": True}
        only = ",".join(idxs)
        self._persist()
        self._log(f"\n========== 生成全部未完成 {len(idxs)} 章 ==========")

        def job():
            cfg = self._cfg(source, subject, note)
            cfg.require_api_key(); cfg.require_source()
            self._phase("准备提示词…")
            run_build(cfg)
            run_generate(cfg, only=only, progress_cb=lambda i, t, ti: self._progress(i, t, ti))

        def done(ok, err):
            p = self._refresh_payload()
            p.update(ok=ok, err=err, kind="generate", gaps=(self._scan_gaps() if ok else {}))
            return p

        return self._run_task("generate", job, done)

    def run_verify(self, indices, provider, source, subject, note):
        self._sync(source, subject, note, provider)
        bad = self._precheck(source)
        if bad:
            return bad
        prov = (provider or "bing_cn").strip() or "bing_cn"
        if prov in SEARCH_ENV and not os.environ.get(SEARCH_ENV[prov]):
            try:
                has_key = bool(self._cfg(source, "", "", provider=prov).search_key())
            except Exception:
                has_key = False
            if not has_key:
                return {"need_search_key": True, "msg": f"{prov} 需要先点“设置检索 Key”。"}
        chapters, _ = self._chapters()
        out = self._out_dir()
        if indices:
            idxs = [str(i) for i in indices]
        else:
            idxs = [str(ch.get("index")) for ch in chapters
                    if (out / f"{chapter_stem(ch.get('index'), ch.get('title',''))}.md").exists()]
        if not idxs:
            return {"nothing": True, "msg": "请先生成章节（或勾选章节）。"}
        only = ",".join(idxs)
        self._persist()
        self._log(f"\n========== 联网核对 {len(idxs)} 章（来源:{prov}）==========")

        def job():
            cfg = self._cfg(source, subject, note, provider=prov)
            cfg.require_api_key(); cfg.require_source(); cfg.require_search_key()
            run_verify(cfg, only=only, progress_cb=lambda i, t, ti: self._progress(i, t, ti))

        def done(ok, err):
            p = self._refresh_payload()
            p.update(ok=ok, err=err, kind="verify")
            return p

        return self._run_task("verify", job, done)


# ---------- 无边框窗口：补回原生缩放边框（不带标题栏）----------
def _frameless_setup():
    """frameless 会去掉 WS_THICKFRAME（连缩放一起没了）。这里补回它：
    恢复原生边缘拉伸 + Aero 贴边/吸附，但不恢复系统标题栏（WS_CAPTION 仍关）。"""
    try:
        import ctypes
        u = ctypes.windll.user32
        time.sleep(0.4)                        # 等 pywebview 把 frameless 样式应用完，再补 THICKFRAME，否则会被覆盖
        hwnd = 0
        for _ in range(40):                    # 等窗口出现，最多 ~6s
            hwnd = u.FindWindowW(None, TITLE)
            if hwnd:
                break
            time.sleep(0.15)
        if not hwnd:
            return
        GWL_STYLE, WS_THICKFRAME = -16, 0x00040000
        style = u.GetWindowLongW(hwnd, GWL_STYLE)
        u.SetWindowLongW(hwnd, GWL_STYLE, style | WS_THICKFRAME)
        # SWP_NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED
        u.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
    except Exception:
        pass


def launch(config_path=None):
    """启动 Web 版；若 webview / WebView2 不可用会抛异常，交由 gui.launch() 回退。"""
    import webview
    api = Api(config_path)
    html = _html_path().read_text(encoding="utf-8")   # 内联加载：避免 WebView2 缓存旧页面
    window = webview.create_window(
        TITLE, html=html, js_api=api,
        width=1180, height=824, min_size=(980, 680),
        frameless=True, easy_drag=False, shadow=True,   # 无系统标题栏，自绘暖色标题栏
        background_color=CANVAS, text_select=True)
    api.window = window
    # 页面加载完成后再补回缩放边框：此时 pywebview 已应用 frameless 样式，不会被覆盖。
    window.events.loaded += lambda *a: threading.Thread(target=_frameless_setup, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    launch()
