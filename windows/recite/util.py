"""通用工具：文件名清洗、JSON 读写、章节文件名、宽松 JSON 解析。"""
import re
import json
from pathlib import Path

_BAD = re.compile(r'[\\/:*?"<>|]')


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
