"""联网核对：把每章“待核(〔补〕)”点拿去检索权威来源，
让 DeepSeek 仅依据检索内容提炼出带真实出处的补充，写回 .md 的“联网核对补充”小节。"""
import re
import time

from .deepseek import DeepSeek
from .websearch import search
from .util import read_json, chapter_stem, parse_json_loose

SECTION_MARK = "## 联网核对补充（真实来源）"

GROUND_SYS = ("你是严谨的学科资料核对员。只依据我提供的“检索资料”作答，"
              "不得使用资料之外的知识，不得编造或臆测。回答要忠实、简明、可直接背诵，"
              "保留术语/数字/英文与单位。")


def extract_pending(md: str) -> list[str]:
    """从 md 的“## 待核”小节抽取待核知识点（去掉〔补〕与尾部来源括注）。"""
    items, in_sec = [], False
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            in_sec = "待核" in s
            continue
        if in_sec and s and not s.startswith((">", "#")):
            t = s.lstrip("-•*　 ").strip().replace("〔补〕", "").strip()
            t = re.sub(r"（[^（）]*）\s*$", "", t).strip()     # 去尾部（来源…）
            if t and t not in ("无", "无。"):
                items.append(t)
    return list(dict.fromkeys(items))


def _select(chapters, only):
    if not only:
        return chapters
    toks = [t.strip() for t in only.split(",") if t.strip()]
    return [c for c in chapters
            if any(t == str(c.get("index")) or t in c.get("title", "") for t in toks)]


def _ground(ds: DeepSeek, subject: str, point: str, hits: list[dict]) -> dict:
    blocks = []
    for i, h in enumerate(hits[:5], 1):
        tag = "（可信源）" if h.get("trusted") else ""
        blocks.append(f"[{i}]{tag} {h.get('title','')} | {h.get('url','')}\n"
                      f"{(h.get('content','') or '')[:1500]}")
    user = (f"学科：{subject}\n待核知识点：{point}\n\n"
            f"请只依据下列检索资料，判断能否可靠支撑该知识点，并给出可直接背诵的简明补充"
            f"（1–4 句，忠实原意，保留术语/数字/英文）。\n\n"
            f"检索资料：\n" + "\n----\n".join(blocks) +
            f"\n\n只输出 JSON：{{\"covered\": true/false, "
            f"\"content\": \"covered 为 true 时给出简明背诵补充，否则空串\", "
            f"\"sources\": [用到的资料编号]}}")
    res = ds.chat([{"role": "system", "content": GROUND_SYS},
                   {"role": "user", "content": user}],
                  temperature=0.2, max_tokens=800, json_mode=True)
    try:
        return parse_json_loose(res.content)
    except Exception:
        return {"covered": False, "content": "", "sources": []}


def _strip_old_section(md: str) -> str:
    idx = md.find("\n" + SECTION_MARK)
    return md[:idx].rstrip() + "\n" if idx >= 0 else md.rstrip() + "\n"


def run_verify(cfg, only: str = "", force: bool = False, progress_cb=None) -> None:
    cfg.require_api_key()
    cfg.require_search_key()
    cfg.ensure_dirs()
    if not cfg.audit_path.exists():
        raise SystemExit("缺少 audit.json，请先 审计→生成 后再联网核对。")

    audit = read_json(cfg.audit_path)
    subject = cfg.subject or audit.get("subject") or "本课程"
    chapters = _select(audit["chapters"], only)
    ds = DeepSeek(cfg)

    total = len(chapters)
    print(f"[核对] provider={cfg.search_provider}  学科={subject}  待处理 {total} 章")
    for i, ch in enumerate(chapters, 1):
        if progress_cb:
            progress_cb(i, total, ch.get("title", ""))
        stem = chapter_stem(ch.get("index"), ch.get("title", ""))
        md_path = cfg.output_dir / f"{stem}.md"
        if not md_path.exists():
            print(f"  · 跳过（未生成）: {stem}")
            continue
        md = md_path.read_text(encoding="utf-8")
        points = extract_pending(md)
        if not points:
            print(f"  · {ch.get('title')}: 无待核项，跳过")
            continue
        points = points[:cfg.verify_max_items]
        print(f"  · {ch.get('title')}: 待核 {len(points)} 项，开始检索…")

        lines = []
        for p in points:
            try:
                hits = search(cfg, f"{subject} {p}".strip())
            except SystemExit:
                raise
            except Exception as e:
                print(f"      ! 检索失败：{e}")
                hits = []
            if not hits:
                lines.append(f"- 【{p[:40]}】未检索到来源，请自行核对。")
                continue
            data = _ground(ds, subject, p, hits)
            content = (data.get("content") or "").strip()
            if data.get("covered") and content:
                used = [hits[i - 1] for i in (data.get("sources") or []) if 1 <= i <= len(hits)] or hits[:1]
                cite = "；".join(f"{(u.get('title') or u.get('url'))[:40]} {u.get('url')}" for u in used[:2])
                lines.append(f"- 〔网核〕【{p[:40]}】{content}（来源：{cite}）")
                print(f"      ✓ {p[:24]} → 已补 ({len(used)} 源)")
            else:
                lines.append(f"- 【{p[:40]}】未检索到可靠来源，请自行核对。")
                print(f"      ? {p[:24]} → 检索资料不足")
            time.sleep(0.5)

        section = (f"\n{SECTION_MARK}\n"
                   f"> 〔网核〕＝经联网检索补充，依据下列来源；仍可能有误，请以你的核对为准。\n"
                   + "\n".join(lines) + "\n")
        md_path.write_text(_strip_old_section(md) + section, encoding="utf-8")
        print(f"      已写回 {md_path.name}")

    print("[核对] 完成。")
