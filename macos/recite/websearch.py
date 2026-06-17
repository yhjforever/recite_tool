"""可插拔联网检索。默认 bing_cn（cn.bing.com，中国大陆可直连、免 Key），
另含 pubmed（学术，国内可直连）、ddg、tavily/serper/bing(Azure)。
返回 [{title, url, content}]，可抓网页正文、按可信域名优先。"""
import re
from urllib.parse import urlparse
from html.parser import HTMLParser

import requests

UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ---------------- HTML → 纯文本（仅用标准库）----------------
class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "header", "footer", "nav"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "header", "footer", "nav") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            s = data.strip()
            if s:
                self.parts.append(s)


def html_to_text(html: str) -> str:
    p = _Extractor()
    try:
        p.feed(html)
    except Exception:
        pass
    return re.sub(r"\s+", " ", " ".join(p.parts)).strip()


def fetch_text(url: str, timeout: int = 20, limit: int = 4000) -> str:
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        ctype = r.headers.get("Content-Type", "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            return ""
        r.encoding = r.apparent_encoding or r.encoding
        return html_to_text(r.text)[:limit]
    except Exception:
        return ""


# ---------------- Bing 中国（cn.bing.com，直连、免 Key）----------------
def _parse_bing(html: str, n: int) -> list[dict]:
    """从 Bing 结果页解析条目。先按 b_algo 块；DOM 变化时回退到通用 <h2><a> 抓取。"""
    out, seen = [], set()

    def _add(url, title, snippet):
        if url and url.startswith("http") and url not in seen:
            seen.add(url)
            out.append({"title": title, "url": url, "content": snippet})

    # 方案一：b_algo 结果块
    starts = [m.start() for m in re.finditer(r'<li class="b_algo[ "]', html)]
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(html)
        block = html[s:e]
        am = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not am:
            am = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not am:
            continue
        pm = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        _add(am.group(1), html_to_text(am.group(2)),
             html_to_text(pm.group(1)) if pm else "")
        if len(out) >= n:
            return out

    # 方案二（DOM 变化兜底）：全局 <h2 ...><a href="http...">标题</a>
    if not out:
        for am in re.finditer(r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                              html, re.S):
            _add(am.group(1), html_to_text(am.group(2)), "")
            if len(out) >= n:
                break
    return out


def _bing_cn(query, n):
    r = requests.get("https://cn.bing.com/search", headers=UA, timeout=30,
                     params={"q": query, "setmkt": "zh-CN", "ensearch": "0"})
    r.encoding = r.apparent_encoding or "utf-8"
    html = r.text
    hits = _parse_bing(html, n)
    if not hits:                              # 诊断：区分空结果 / 验证码 / 结构变化
        low = html.lower()
        if "captcha" in low or "verify" in low or "blocked" in low:
            print("      · bing_cn 可能触发了验证码/风控；建议切换 pubmed 或稍后重试。")
        else:
            print(f"      · bing_cn 解析到 0 条（页面长度 {len(html)}，未匹配结果块），"
                  f"可能是结构变化或无结果，将尝试回退源。")
    return hits


# ---------------- PubMed（NCBI E-utilities，学术、国内可直连、免 Key）----------------
def _pubmed(query, n):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    r = requests.get(f"{base}/esearch.fcgi", headers=UA, timeout=30,
                     params={"db": "pubmed", "term": query, "retmax": n, "retmode": "json"})
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    r2 = requests.get(f"{base}/esummary.fcgi", headers=UA, timeout=30,
                      params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    res = r2.json().get("result", {})
    out = []
    for pid in ids:
        it = res.get(pid, {})
        title = it.get("title", "")
        jour = it.get("fulljournalname") or it.get("source", "")
        out.append({"title": title,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                    "content": f"{title} {jour} {it.get('pubdate','')}".strip()})
    return out


# ---------------- DuckDuckGo（需 pip install ddgs；国内可能不稳定）----------------
def _ddg(query, n):
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            raise SystemExit("provider=ddg 需要先安装：pip install ddgs")
    out = []
    with DDGS() as d:
        for r in d.text(query, max_results=n):
            out.append({"title": r.get("title", ""),
                        "url": r.get("href") or r.get("url", ""),
                        "content": r.get("body", "")})
    return out


# ---------------- 需 Key 的国际接口（可能需自备网络环境）----------------
def _tavily(query, n, key):
    r = requests.post("https://api.tavily.com/search", timeout=30, json={
        "api_key": key, "query": query, "max_results": n,
        "include_raw_content": True, "search_depth": "advanced"})
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "content": x.get("raw_content") or x.get("content", "")}
            for x in r.json().get("results", [])]


def _serper(query, n, key):
    r = requests.post("https://google.serper.dev/search", timeout=30,
                      headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      json={"q": query, "num": n, "hl": "zh-cn"})
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("link", ""),
             "content": x.get("snippet", "")} for x in r.json().get("organic", [])]


def _bing_azure(query, n, key):
    r = requests.get("https://api.bing.microsoft.com/v7.0/search", timeout=30,
                     headers={"Ocp-Apim-Subscription-Key": key},
                     params={"q": query, "count": n, "mkt": "zh-CN"})
    r.raise_for_status()
    vals = r.json().get("webPages", {}).get("value", [])
    return [{"title": x.get("name", ""), "url": x.get("url", ""),
             "content": x.get("snippet", "")} for x in vals]


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


_NOKEY = {"bing_cn", "pubmed", "ddg"}


def _dispatch(prov: str, cfg, query: str, n: int) -> list[dict]:
    if prov == "bing_cn":
        return _bing_cn(query, n)
    if prov == "pubmed":
        return _pubmed(query, n)
    if prov == "ddg":
        return _ddg(query, n)
    if prov == "tavily":
        return _tavily(query, n, cfg.search_key())
    if prov == "serper":
        return _serper(query, n, cfg.search_key())
    if prov == "bing":
        return _bing_azure(query, n, cfg.search_key())
    raise SystemExit(f"未知 search_provider: {prov}（可选 bing_cn/pubmed/ddg/tavily/serper/bing）")


def search(cfg, query: str) -> list[dict]:
    n = cfg.search_max_results
    prov = cfg.search_provider
    hits = [h for h in _dispatch(prov, cfg, query, n) if h.get("url")]

    # 主源无结果 → 回退源（默认 pubmed，国内直连免 Key）
    fb = getattr(cfg, "search_fallback", "") or ""
    if not hits and fb and fb != prov and fb in _NOKEY:
        print(f"      · {prov} 无结果，回退到 {fb} …")
        hits = [h for h in _dispatch(fb, cfg, query, n) if h.get("url")]

    if cfg.search_fetch_pages:
        for h in hits[:3]:
            if len(h.get("content", "")) < 200:
                t = fetch_text(h["url"], cfg.fetch_timeout)
                if t:
                    h["content"] = t

    trusted = [d.lower() for d in cfg.trusted_domains]
    hits.sort(key=lambda h: 0 if any(t in _domain(h["url"]) for t in trusted) else 1)
    for h in hits:
        h["trusted"] = any(t in _domain(h["url"]) for t in trusted)
    return hits
