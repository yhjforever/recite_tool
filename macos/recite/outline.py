"""按审计返回的章节标题，从大纲全文中"逐字切片"出每章原文（保证不改写大纲）。"""
import re


def _find_heading(text: str, heading: str, start: int) -> int:
    """从 start 起查找 heading；允许字符间有空白；优先返回行首匹配。"""
    norm = re.sub(r"\s+", "", heading or "")
    if not norm:
        return -1
    pat = re.compile(r"\s*".join(map(re.escape, norm)))
    fallback = -1
    for m in pat.finditer(text, start):
        s = m.start()
        if s == 0 or text[s - 1] == "\n":      # 行首，最可能是真标题
            return s
        if fallback == -1:
            fallback = s
    return fallback


def slice_text(text: str, headings: list[tuple]) -> dict:
    """通用：按一组有序 (key, 标题) 在 text 中逐字定位并切片，返回 {key: 片段}。
    用于把“整本电子课本”按各章标题切到对应章节。定位不到的 key 返回空串。"""
    found = []
    cursor = 0
    for key, h in headings:
        p = _find_heading(text, h, cursor)
        found.append((key, p))
        if p >= 0:
            cursor = p + 1
    res = {}
    for i, (key, p) in enumerate(found):
        if p < 0:
            res[key] = ""
            continue
        e = len(text)
        for j in range(i + 1, len(found)):
            if found[j][1] >= 0:
                e = found[j][1]
                break
        res[key] = text[p:e].strip()
    return res


_CN = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
       "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十"]


def _densest(text: str, pat, window: int = 4000):
    """在所有命中里挑‘后续窗口内自身最密集’的位置——正文页眉每页重复、密集；
    目录里只出现一次、稀疏。返回 (位置, 密度) 或 (None, 0)。"""
    cands = [m.start() for m in pat.finditer(text)]
    best_p, best_d = None, -1
    for p in cands:
        d = len(pat.findall(text[p:p + window]))
        if d > best_d:
            best_d, best_p = d, p
    return best_p, best_d


def slice_book(text: str, headings: list[tuple], max_chars: int = 0) -> dict:
    """把"整本电子课本"按各章切片，返回 {key: 片段}。
    课本章节物理顺序未必同大纲顺序，且区域名在全书到处出现，故：
    ① 用"第X章"页眉簇定位全部章节边界（密度法避开目录）；
    ② 每个大纲区域用"第X章+区域名"定位其正文起点；终点取下一个章节边界。
    若课本不用"第X章"体例，则返回空（该章退回只用 PPT）。"""
    NUMS = "一二三四五六七八九十百0-9"

    # ① 全部教材章节边界（按章序号找密集页眉簇，过滤目录里的稀疏命中）
    boundaries = []
    for n in range(1, len(_CN)):
        pat = re.compile("第" + _CN[n] + "章")
        p, d = _densest(text, pat)
        if p is not None and d >= 2:          # 出现≥2次＝正文页眉重复，非目录
            boundaries.append(p)
    boundaries = sorted(set(boundaries))

    # ② 每个大纲区域定位正文起点，终点取下一个章节边界
    res = {key: "" for key, _ in headings}
    for key, h in headings:
        raw = (h or "").split("\n")[0].strip()                 # 只取首行（去掉英文等次行）
        raw = re.sub(r"^\s*第[" + NUMS + r"]+[章节]\s*", "", raw)  # 去掉可能的“第X章”前缀
        norm = re.sub(r"\s+", "", raw)
        if not norm:
            continue
        region = r"\s*".join(map(re.escape, norm))
        pat = re.compile("第[" + NUMS + r"]+章\s*" + region)
        start, d = _densest(text, pat)
        if start is None or d < 2:            # 没有"第X章+区域"页眉 → 不切（退回 PPT）
            continue
        end = len(text)
        for b in boundaries:
            if b > start + 200:
                end = b
                break
        seg = text[start:end].strip()
        if max_chars and len(seg) > max_chars:
            seg = seg[:max_chars]
        res[key] = seg
    return res


def slice_outline(outline_text: str, chapters: list[dict]) -> list[str]:
    """为每个 chapter 计算 outline_excerpt（就地写回），并返回未定位到的章标题列表。"""
    positions = []
    cursor = 0
    for ch in chapters:
        heading = ch.get("outline_heading") or ch.get("title", "")
        pos = _find_heading(outline_text, heading, cursor)
        positions.append(pos)
        if pos >= 0:
            cursor = pos + 1

    missing = []
    for i, ch in enumerate(chapters):
        s = positions[i]
        if s < 0:
            ch["outline_excerpt"] = ""
            missing.append(ch.get("title") or ch.get("outline_heading") or f"#{i+1}")
            continue
        e = len(outline_text)
        for j in range(i + 1, len(chapters)):
            if positions[j] >= 0:
                e = positions[j]
                break
        ch["outline_excerpt"] = outline_text[s:e].strip()
    return missing
