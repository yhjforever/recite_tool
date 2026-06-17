"""审计：让 DeepSeek 把课件映射到大纲各章，并逐字切分大纲，落盘 audit.json。"""
from .extract import list_source_files, extract_text, fingerprint
from .deepseek import DeepSeek
from .prompts import AUDIT_SYSTEM, render_audit_user
from .outline import slice_outline
from .util import write_json, parse_json_loose, resolve_source


def run_audit(cfg, force: bool = False) -> dict:
    cfg.require_api_key()
    cfg.require_source()
    cfg.ensure_dirs()

    outline_path, sources = list_source_files(cfg)
    print(f"[审计] 大纲: {outline_path.name}")
    print(f"[审计] 课件: {len(sources)} 个；正在抽取文本与指纹 …")

    outline_text = extract_text(outline_path, cfg.cache_dir, force=force)
    fps = [fingerprint(f, cfg.cache_dir) for f in sources]

    print("[审计] 调用 DeepSeek 做章节→文件映射 …")
    ds = DeepSeek(cfg)
    user = render_audit_user(outline_text, fps)
    res = ds.chat(
        [{"role": "system", "content": AUDIT_SYSTEM},
         {"role": "user", "content": user}],
        temperature=cfg.audit_temperature, max_tokens=4096, json_mode=True,
    )
    data = parse_json_loose(res.content)

    subject = cfg.subject or data.get("subject") or "本课程"
    chapters = data.get("chapters") or []
    if not chapters:
        raise SystemExit("审计失败：DeepSeek 未返回任何章节。请检查大纲文件是否可读。")

    # 解析每章 source_files 为真实文件名列表（兼容旧的单个 source_file）
    warnings = list(data.get("warnings") or [])
    for ch in chapters:
        raw = ch.get("source_files")
        if not raw:
            one = ch.get("source_file")
            raw = [one] if one else []
        resolved = []
        for name in raw:
            p = resolve_source(name, sources)
            if p and p.name not in resolved:
                resolved.append(p.name)
        if not resolved:
            warnings.append(f"第{ch.get('index')}章「{ch.get('title')}」未匹配到可用素材文件。")
        ch["sources_resolved"] = resolved
        ch["source_resolved"] = resolved[0] if resolved else ""    # 兼容旧字段/界面显示

    # 逐字切分大纲到每章
    missing = slice_outline(outline_text, chapters)
    for t in missing:
        warnings.append(f"未能在大纲中定位章节标题：{t}（该章大纲为空，请人工检查 outline_heading）。")

    audit = {
        "subject": subject,
        "outline_file": outline_path.name,
        "source_count": len(sources),
        "chapters": chapters,
        "unused_files": data.get("unused_files") or [],
        "warnings": warnings,
        "usage": res.usage,
    }
    write_json(cfg.audit_path, audit)

    print(f"[审计] 学科判定: {subject}")
    print(f"[审计] 章节数: {len(chapters)}；未用文件: {len(audit['unused_files'])}；告警: {len(warnings)}")
    if warnings:
        for w in warnings:
            print("   ! " + w)
    print(f"[审计] 已写入 {cfg.audit_path}")
    return audit
