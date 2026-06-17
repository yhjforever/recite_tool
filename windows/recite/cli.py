"""命令行入口：extract / audit / build / generate / run / status。"""
import sys
import argparse
from pathlib import Path

from .config import load_config
from .util import read_json, chapter_stem


def _reconfig_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _apply_overrides(cfg, args):
    """--source 会把母文件夹及其下的 output/_recite 路径一并重算为默认布局。"""
    if getattr(args, "source", None):
        cfg.set_source(args.source)
    if getattr(args, "subject", None):
        cfg.subject = args.subject


def cmd_extract(cfg, args):
    from .extract import list_source_files, extract_text
    cfg.require_source(); cfg.ensure_dirs()
    outline, sources = list_source_files(cfg)
    print(f"大纲: {outline.name}")
    extract_text(outline, cfg.cache_dir, force=args.force)
    for f in sources:
        t = extract_text(f, cfg.cache_dir, force=args.force)
        print(f"  抽取 {f.name}: {len(t)} 字")
    print(f"文本缓存目录: {cfg.cache_dir}")


def cmd_audit(cfg, args):
    from .audit import run_audit
    run_audit(cfg, force=args.force)


def cmd_build(cfg, args):
    from .build import run_build
    run_build(cfg)


def cmd_generate(cfg, args):
    from .generate import run_generate
    run_generate(cfg, only=args.chapters or "", force=args.force)


def cmd_run(cfg, args):
    from .audit import run_audit
    from .build import run_build
    from .generate import run_generate
    if args.force or not cfg.audit_path.exists():
        run_audit(cfg, force=args.force)
    else:
        print(f"[run] 复用已存在的 {cfg.audit_path.name}（加 --force 可重审计）")
    run_build(cfg)
    run_generate(cfg, only=args.chapters or "", force=args.force)


def cmd_verify(cfg, args):
    from .verify import run_verify
    run_verify(cfg, only=args.chapters or "", force=args.force)


def cmd_gui(cfg, args):
    from .gui import launch
    launch(args.config)


def cmd_status(cfg, args):
    if not cfg.audit_path.exists():
        print("尚无 audit.json，请先 audit。")
        return
    audit = read_json(cfg.audit_path)
    subject = cfg.subject or audit.get("subject")
    print(f"学科: {subject} | 大纲: {audit.get('outline_file')}")
    print(f"{'序':>2}  {'状态':<4} {'章名':<28} 来源")
    done = 0
    for ch in audit["chapters"]:
        stem = chapter_stem(ch.get("index"), ch.get("title", ""))
        md = cfg.output_dir / f"{stem}.md"
        ok = md.exists()
        done += ok
        flag = "✓done" if ok else "·todo"
        print(f"{str(ch.get('index')):>2}  {flag:<4} {ch.get('title',''):<28} {ch.get('source_resolved') or ch.get('source_file') or '无'}")
    print(f"\n完成 {done}/{len(audit['chapters'])} 章。输出目录: {cfg.output_dir}")
    if audit.get("warnings"):
        print("告警:")
        for w in audit["warnings"]:
            print("  ! " + w)


def build_parser():
    p = argparse.ArgumentParser(
        prog="python -m recite",
        description="按课程大纲，把 PPT/电子课本整理成可背诵的 Markdown（DeepSeek 驱动）。")
    p.add_argument("--config", help="配置文件路径（默认 config.yaml）")
    p.add_argument("--source", help="覆盖母文件夹路径")
    p.add_argument("--subject", help="覆盖学科名")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("extract", help="仅抽取并缓存所有文件文本")
    sp.add_argument("--force", action="store_true", help="忽略缓存重抽")
    sp.set_defaults(func=cmd_extract)

    sp = sub.add_parser("audit", help="DeepSeek 审计：章节↔文件映射 + 大纲切分 → audit.json")
    sp.add_argument("--force", action="store_true", help="重抽文本并重审计")
    sp.set_defaults(func=cmd_audit)

    sp = sub.add_parser("build", help="据 audit.json 生成提示词包 prompts/*.txt")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("generate", help="逐章调用 DeepSeek，输出 output/*.md")
    sp.add_argument("--chapters", help="只做部分章：如 1,2,5 或 疾病分布")
    sp.add_argument("--force", action="store_true", help="覆盖已存在的 .md")
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("run", help="一键：audit → build → generate")
    sp.add_argument("--chapters", help="只做部分章")
    sp.add_argument("--force", action="store_true", help="重审计并覆盖输出")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("verify", help="联网核对：给各章“待核”点检索权威来源并补充真实出处")
    sp.add_argument("--chapters", help="只核对部分章：如 1,2,5 或 章名关键词")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("status", help="查看各章生成进度")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("gui", help="启动图形界面（无需终端）")
    sp.set_defaults(func=cmd_gui)
    return p


def main(argv=None):
    _reconfig_stdout()
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    _apply_overrides(cfg, args)
    args.func(cfg, args)


if __name__ == "__main__":
    main()
