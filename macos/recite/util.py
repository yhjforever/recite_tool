"""通用工具：文件名清洗、JSON 读写、章节文件名、宽松 JSON 解析。"""
import re
import json
from pathlib import Path

_BAD = re.compile(r'[\\/:*?"<>|]')


def read_text_tolerant(path: Path) -> str:
    """读取文本，按 Windows 常见编码依次尝试，绝不因 BOM / 编码抛异常。
    用于 .env / config.yaml / gui_state.json 等启动关键小文件：
    某些编辑器把它们存成 UTF-8(BOM) 或 ANSI/GBK 时，原来的 read_text('utf-8')
    会读出空键（BOM 让首行键名带 \\ufeff）或直接抛 UnicodeDecodeError，
    导致 get_init 失败、界面卡死并误报“API Key 未设置”。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def safe_name(s: str) -> str:
    return _BAD.sub("", str(s)).replace(" ", "").strip() or "untitled"


def safe_index(index) -> str:
    """把章节 index 变成文件名安全前缀，容忍非整数：
    1 -> '01'；'1.1' -> '01-01'；'绪论'/'上篇' -> 清洗后的原文；None -> 'XX'。"""
    if index is None:
        return "XX"
    s = str(index).strip()
    if re.fullmatch(r"\d+", s):
        return f"{int(s):02d}"
    if re.fullmatch(r"\d+(?:\.\d+)+", s):
        return "-".join(f"{int(p):02d}" for p in s.split("."))
    return safe_name(s)


def chapter_stem(index, title: str) -> str:
    return f"{safe_index(index)}_{safe_name(title)}"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_json_loose(text: str):
    """容忍 ```json ... ``` 包裹或前后多余文字，尽力提取 JSON 对象。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            return json.loads(t[a:b + 1])
        raise


def objective_codes(outline_excerpt: str) -> list[str]:
    """抽取大纲里的【编号学习目标】（如 1001、1101、2101、3708），用于生成后覆盖自检。
    只取"行首 4 位编号 + 空白 + 非数字"的定义行（避免把年份/页码/数量等 4 位数误当编号）；
    仅当这类编号 ≥3 个时才认定为"编号式大纲"并返回，否则返回空表（该课程不触发覆盖校验）。"""
    if not outline_excerpt:
        return []
    codes = re.findall(r"(?m)^\s*(\d{4})(?=[ \t　][^\d])", outline_excerpt)
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out if len(out) >= 3 else []


def coverage_gaps(outline_excerpt: str, md_text: str) -> list[str]:
    """返回大纲编号学习目标中【未出现在正文】的编号；用于生成后自检，防分类不清/漏知识点。"""
    md = md_text or ""
    return [c for c in objective_codes(outline_excerpt) if c not in md]


def resolve_source(name: str, sources: list[Path]) -> Path | None:
    """把审计给的文件名解析为实际 Path：精确→忽略大小写→去空格包含。"""
    if not name:
        return None
    for f in sources:
        if f.name == name:
            return f
    low = name.lower()
    for f in sources:
        if f.name.lower() == low:
            return f
    key = re.sub(r"\s+", "", name).lower()
    for f in sources:
        if key in re.sub(r"\s+", "", f.name).lower():
            return f
    return None
