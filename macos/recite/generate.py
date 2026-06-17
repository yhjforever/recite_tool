"""生成：读取 system + 单章提示词 → DeepSeek → 保存为 output/NN_*.md（断点续跑）。"""
import time
from datetime import datetime

from .deepseek import DeepSeek
from .prompts import render_system, render_chapter
from .extract import list_source_files
from .build import assemble_source_text
from .util import read_json, chapter_stem


def _select(chapters, only):
    if not only:
        return chapters
    tokens = [t.strip() for t in only.split(",") if t.strip()]
    picked = []
    for ch in chapters:
        idx = str(ch.get("index"))
        title = ch.get("title", "")
        if any(tok == idx or tok in title for tok in tokens):
            picked.append(ch)
    return picked


def _user_prompt(cfg, ch, all_chapters, sources) -> str:
    """优先用磁盘上的提示词文件（尊重用户手改）；缺失则按 audit 即时渲染（含多素材合并）。"""
    stem = chapter_stem(ch.get("index"), ch.get("title", ""))
    f = cfg.prompts_dir / f"{stem}.txt"
    if f.exists():
        return f.read_text(encoding="utf-8")
    label, source_text = assemble_source_text(cfg, ch, all_chapters, sources)
    return render_chapter(ch.get("title", ""), ch.get("hours", ""), ch.get("note", ""),
                          ch.get("outline_excerpt", ""), label, source_text,
                          requirements=getattr(cfg, "subject_note", ""))


def run_generate(cfg, only: str = "", force: bool = False) -> None:
    cfg.require_api_key()
    cfg.ensure_dirs()
    if not cfg.audit_path.exists():
        raise SystemExit("缺少 audit.json，请先运行: python -m recite audit && python -m recite build")

    audit = read_json(cfg.audit_path)
    subject = cfg.subject or audit.get("subject") or "本课程"
    all_chapters = audit["chapters"]
    chapters = _select(all_chapters, only)
    _, sources = list_source_files(cfg)

    sys_path = cfg.prompts_dir / "00_系统提示词.txt"
    system = sys_path.read_text(encoding="utf-8") if sys_path.exists() \
        else render_system(subject, getattr(cfg, "subject_note", ""))

    ds = DeepSeek(cfg)
    total = len(chapters)
    print(f"[生成] 学科: {subject}；本次 {total} 章；输出目录: {cfg.output_dir}")

    for i, ch in enumerate(chapters, 1):
        idx = ch.get("index")
        title = ch.get("title", f"第{idx}章")
        stem = chapter_stem(idx, title)
        out_path = cfg.output_dir / f"{stem}.md"
        partial_path = cfg.output_dir / f"{stem}.partial.md"

        if out_path.exists() and not force:
            print(f"[{i}/{total}] 跳过（已存在）: {stem}.md")
            continue

        print(f"[{i}/{total}] 生成: {title} …")
        user = _user_prompt(cfg, ch, all_chapters, sources)

        def on_progress(rnd, finish, usage):
            tag = "完成" if finish != "length" else "续写"
            print(f"        · 第{rnd}段 {tag}  out_tokens={usage.get('completion_tokens', 0)}")

        t0 = time.time()
        res = ds.chat_long(system, user,
                           reminder=getattr(cfg, "subject_note", ""),
                           on_progress=on_progress)
        dt = time.time() - t0
        usage = res.usage

        src_label = "；".join(ch.get("sources_resolved") or
                              [ch.get("source_resolved") or ch.get("source_file") or "无"])
        status = "完整" if res.complete else f"截断(已用 {res.continuations} 次续写仍未写完)"
        header = (f"<!-- recite_tool | 学科:{subject} | {title} | "
                  f"来源:{src_label} | 模型:{cfg.model} | {datetime.now():%Y-%m-%d %H:%M} | "
                  f"tokens in/out={usage.get('prompt_tokens',0)}/{usage.get('completion_tokens',0)} | "
                  f"状态:{status} -->\n\n")
        body = header + res.text.strip() + "\n"

        if res.complete:
            partial_path.unlink(missing_ok=True)       # 清理上次的残稿
            out_path.write_text(body, encoding="utf-8")
            print(f"        ✓ 已保存 {out_path.name}  用时{dt:.0f}s，"
                  f"out_tokens={usage.get('completion_tokens',0)}")
        else:
            # 截断：存成 .partial.md，不覆盖正式 .md，明确警告
            partial_path.write_text(
                "> ⚠ 本文件为**截断的残稿**：模型用尽续写仍未写完。请调大 config 的 "
                "max_tokens / max_continuations 后，勾选“覆盖重做”重新生成。\n\n" + body,
                encoding="utf-8")
            had_full = "（注意：已存在的正式 .md 未被覆盖）" if out_path.exists() else ""
            print(f"        ⚠ 输出被截断，已存为 {partial_path.name}（未写正式 .md）{had_full}"
                  f"；请提高 max_tokens 或 max_continuations 后重试。")

    print(f"[生成] 完成。Markdown 背诵稿在: {cfg.output_dir}")
