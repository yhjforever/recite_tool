"""可插拔联网检索。默认 bing_cn（cn.bing.com，中国大陆可直连、免 Key），
另含 pubmed（学术，国内可直连）、ddg、tavily/serper/bing(Azure)。
返回 [{title, url, content}]，可抓网页正文、按可信域名优先。"""
import re
from urllib.parse import urlparse
from html.parser import HTMLParser

import requests

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    """Bing 网页版抓取。注意：Bing 现已基本改为 JS 客户端渲染，静态 HTML 多无结果块，
    通常返回 0；保留作兜底（个别地区/缓存仍可能给出 b_algo）。主力见 _so360 / _sogou。"""
    r = requests.get("https://www.bing.com/search", headers=UA, timeout=30,
                     params={"q": query, "mkt": "zh-CN"})
    r.encoding = r.apparent_encoding or "utf-8"
    return _parse_bing(r.text, n)


# 搜索引擎/导航站自身域名：从抓取结果里剔除（它们不是内容来源）
# 搜索引擎/导航/备案页脚等非内容域名（被风控时页面常只剩这些）
_ENGINE_HOSTS = ("bing.com", "baidu.com", "google.", "so.com", "360.cn", "360.com",
                 "360kan.com", "sogou.com", "sogou.cn", "sm.cn", "yahoo.", "youdao.com",
                 "hao123.com", "msn.com", "microsoft.com",
                 "miibeian.gov.cn", "beian.gov.cn", "beian.miit.gov.cn", "icp.gov.cn")


def _is_engine(host: str) -> bool:
    return (not host) or any(e in host for e in _ENGINE_HOSTS)


# ---------------- 360 搜索（so.com，国内直连、免 Key、服务端渲染、可解析）----------------
def _so360(query, n):
    """360 把真实目标 URL 放在结果 <a> 的 data-url/data-mdurl；href 是 so.com/link 跳转。"""
    r = requests.get("https://www.so.com/s", timeout=30, params={"q": query},
                     headers=dict(UA, Referer="https://www.so.com/"))
    html = r.text
    out, seen = [], set()
    for am in re.finditer(r'<a\b[^>]*?\bdata-(?:url|mdurl)="(https?://[^"]+)"[^>]*>(.*?)</a>',
                          html, re.S):
        url = am.group(1)
        host = _domain(url)
        if _is_engine(host) or url in seen:                 # 跳过引擎自身/AI 卡片/去重
            continue
        seen.add(url)
        out.append({"title": html_to_text(am.group(2)), "url": url, "content": ""})
        if len(out) >= n:
            break
    return out


# ---------------- 搜狗（sogou.com，国内直连、免 Key；反爬较强，时通时断，作次选）----------------
def _sogou(query, n):
    r = requests.get("https://www.sogou.com/web", headers=dict(UA, Referer="https://www.sogou.com/"),
                     timeout=30, params={"query": query})
    html = r.text
    out, seen = [], set()
    # 取结果区里指向站外的直链（搜狗部分结果是直链，部分是 /link?url= 跳转，这里只收直链）
    for am in re.finditer(r'<a\b[^>]*?\bhref="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.S):
        url, host = am.group(1), _domain(am.group(1))
        if _is_engine(host) or url in seen:
            continue
        seen.add(url)
        out.append({"title": html_to_text(am.group(2)), "url": url, "content": ""})
        if len(out) >= n:
            break
    return out


# ---------------- 维基百科 API（zh，国内可直连、免 Key、无反爬、权威）----------------
def _wikipedia(query, n):
    """走 MediaWiki API：先 search 拿条目，再批量取每条 intro extract。API 不反爬，最稳。"""
    base = "https://zh.wikipedia.org/w/api.php"
    r = requests.get(base, headers=UA, timeout=20, params={
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": n, "format": "json"})
    found = r.json().get("query", {}).get("search", [])
    if not found:
        return []
    titles = [s["title"] for s in found]
    extracts = {}
    try:
        r2 = requests.get(base, headers=UA, timeout=20, params={
            "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
            "redirects": 1, "titles": "|".join(titles), "format": "json"})
        for p in r2.json().get("query", {}).get("pages", {}).values():
            extracts[p.get("title", "")] = (p.get("extract") or "").strip()
    except Exception:
        pass
    out = []
    from urllib.parse import quote
    for s in found:
        t = s["title"]
        body = extracts.get(t) or html_to_text(s.get("snippet", ""))
        out.append({"title": t, "content": body[:2000],
                    "url": "https://zh.wikipedia.org/wiki/" + quote(t.replace(" ", "_"))})
    return out


# ================= 权威来源白名单（医学/学术/官方）=================
# 只认编审制百科、临床参考、政府/卫生组织、学术期刊与索引、高校。
# 自媒体/问答/视频/SEO 站（百家号/知乎/有来/丁香问答/抖音/B站/微信公众号/医学教育SEO等）一律不算权威。
AUTHORITATIVE_DOMAINS = (
    "wikipedia.org",                                   # 维基百科（编审制百科）
    "msdmanuals.cn", "msdmanuals.com", "merckmanuals.com",  # 默沙东/默克诊疗手册
    "medlineplus.gov", "uptodate.com", "ncbi.nlm.nih.gov",  # MedlinePlus / UpToDate / NCBI
    "who.int", "nhc.gov.cn", "chinacdc.cn", "cdc.gov", "nih.gov", "nmpa.gov.cn",  # 官方卫生机构
    "nejm.org", "thelancet.com", "bmj.com", "jamanetwork.com", "nature.com",      # 顶级期刊
    "sciencedirect.com", "springer.com", "onlinelibrary.wiley.com", "cell.com",
    "cochranelibrary.com", "academic.oup.com", "frontiersin.org", "plos.org",
    "cma.org.cn", "yiigle.com",                        # 中华医学会 / 中华医学期刊网
)


def _is_authoritative(host: str) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    if host.endswith(".edu") or ".edu." in host or host.endswith(".ac.cn") or ".ac.uk" in host:
        return True                                    # 高校/科研机构
    if host.endswith(".gov") or ".gov." in host:       # 各国政府/卫生部门
        return True
    return any(d in host for d in AUTHORITATIVE_DOMAINS)


def _authoritative(query, n):
    """只取权威来源：维基百科(API) → 抓取引擎里命中权威域名的结果(WHO/MSD/期刊/.gov/.edu…) → PubMed(学术)。
    非权威一律丢弃；宁缺毋滥（搜不到权威就返回空）。"""
    out, seen = [], set()

    def _add(items):
        for h in items or []:
            u = h.get("url", "")
            if u and u not in seen and _is_authoritative(_domain(u)):
                seen.add(u); out.append(h)

    try:
        _add(_wikipedia(query, n))                      # 维基：权威、API、无反爬
    except Exception:
        pass
    if len(out) < n:                                    # 抓取引擎只收命中权威域名的结果
        for fn in (_so360, _sogou):
            try:
                _add(fn(query, n * 3))
            except Exception:
                pass
            if len(out) >= n:
                break
    if len(out) < n:                                    # 学术兜底（英文为主）
        try:
            _add(_pubmed(query, n))
        except Exception:
            pass
    if not out:
        print("      · 未检索到权威来源（维基/官方/期刊/高校/PubMed）；按设置宁缺毋滥，本条不补。")
    return out[:n]


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


_NOKEY = {"authoritative", "bing_cn", "so360", "sogou", "wikipedia", "pubmed", "ddg"}


def _dispatch(prov: str, cfg, query: str, n: int) -> list[dict]:
    # 默认（含旧 bing_cn 兼容）：只取权威来源（维基/官方/期刊/高校/PubMed），非权威丢弃
    if prov in ("authoritative", "bing_cn"):
        return _authoritative(query, n)
    if prov == "so360":            # 显式宽搜（不过滤权威，结果含自媒体/SEO，慎用）
        return _so360(query, n)
    if prov == "sogou":
        return _sogou(query, n)
    if prov == "wikipedia":
        return _wikipedia(query, n)
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
    raise SystemExit(f"未知 search_provider: {prov}"
                     f"（可选 authoritative/bing_cn/so360/sogou/wikipedia/pubmed/ddg/tavily/serper/bing）")


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
