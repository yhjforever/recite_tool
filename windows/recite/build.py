"""构建提示词包：依据 audit.json 写出 prompts/00_系统提示词.txt 和每章 NN_*.txt。
支持同一章多份素材（PPT + 电子课本）；整本课本按本章标题切片后再合并。"""
from .extract import list_source_files, extract_text
from .prompts import render_system, render_chapter
from .outline import slice_book, slice_text
from .util import read_json, chapter_stem, resolve_source

SHARE_THRESHOLD = 3   # 一个文件被 >= 3 章引用 → 视为“整本电子课本”，按章切片


def _ch_source_names(ch) -> list:
    if ch.get("sources_resolved"):
        return list(ch["sources_resolved"])
    one = ch.get("source_resolved") or ch.get("source_file")
    return [one] if one else []


def _share_counts(chapters) -> dict:
    cnt = {}
    for c in chapters:
        for f in _ch_source_names(c):
            cnt[f] = cnt.get(f, 0) + 1
    return cnt


def assemble_source_text(cfg, ch, chapters, sources):
    """把本章所有素材抽成一段文字。整本课本（被多章引用）按本章标题切片。
    返回 (来源标签, 合并文字)。"""
    counts = _share_counts(chapters)
    # 整本课本按章切片用“干净的章名”（title 优先，无英文/换行）
    headings = [(c.get("index"), c.get("title") or c.get("outline_heading") or "") for c in chapters]
    parts, used = [], []
    for fname in _ch_source_names(ch):
        p = resolve_source(fname, sources)
        if not p:
            continue
        text = extract_text(p, cfg.cache_dir)
        if counts.get(fname, 1) >= SHARE_THRESHOLD:        # 整本课本 → 只取本章那段
            cap = getattr(cfg, "book_slice_max_chars", 40000)
            seg = slice_book(text, headings, cap).get(ch.get("index"), "")
            if not seg:                                    # slice_book 失败 → 退回顺序切片
                seg = slice_text(text, headings).get(ch.get("index"), "")
                if seg and cap and len(seg) > cap:
                    seg = seg[:cap]
            text = seg
        if text and text.strip():
            parts.append(f"【素材来源：{fname}】\n{text.strip()}")
            used.append(fname)
    label = "；".join(used) if used else "（无对应素材）"
    return label, ("\n\n".join(parts) if parts else "")


def run_build(cfg) -> list[dict]:
    cfg.require_source()
    cfg.ensure_dirs()
    if not cfg.audit_path.exists():
        raise SystemExit("缺少 audit.json，请先运行: python -m recite audit")

    audit = read_json(cfg.audit_path)
    subject = cfg.subject or audit.get("subject") or "本课程"
    chapters = audit["chapters"]
    _, sources = list_source_files(cfg)

    # 系统提示词（含课程说明，因地制宜）
    sys_path = cfg.prompts_dir / "00_系统提示词.txt"
    sys_path.write_text(render_system(subject, getattr(cfg, "subject_note", "")), encoding="utf-8")

    manifest = []
    for ch in chapters:
        idx = ch.get("index")
        title = ch.get("title", f"第{idx}章")
        stem = chapter_stem(idx, title)

        label, source_text = assemble_source_text(cfg, ch, chapters, sources)
        user_prompt = render_chapter(
            title=title,
            hours=ch.get("hours", ""),
            note=ch.get("note", ""),
            outline=ch.get("outline_excerpt", ""),
            source=label,
            source_text=source_text,
            requirements=getattr(cfg, "subject_note", ""),
        )
        (cfg.prompts_dir / f"{stem}.txt").write_text(user_prompt, encoding="utf-8")
        manifest.append({
            "index": idx, "title": title, "stem": stem, "source": label,
            "outline_chars": len(ch.get("outline_excerpt", "")),
            "source_chars": len(source_text),
        })

    print(f"[构建] 系统提示词 + {len(manifest)} 章提示词已写入 {cfg.prompts_dir}")
    weak = [m for m in manifest if m["outline_chars"] < 10 or m["source_chars"] < 50]
    if weak:
        print("[构建] 以下章节大纲或素材偏少，建议人工核对：")
        for m in weak:
            print(f"   ! {m['stem']}  大纲{m['outline_chars']}字 / 素材{m['source_chars']}字 / 来源:{m['source']}")
    return manifest
