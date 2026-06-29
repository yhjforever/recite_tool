"""最小回归测试：覆盖测试报告里的核心 bug。
直接运行： python tests/test_fixes.py   （无需 pytest；pytest 也能收集）"""
import os
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recite.util import safe_index, chapter_stem
from recite.extract import extract_text, _read_plain
from recite.outline import slice_book, slice_outline
from recite.websearch import _parse_bing
from recite.deepseek import DeepSeek, ChatResult


# ---------- P1-5 非整数 index ----------
def test_safe_index_non_integer():
    assert safe_index(1) == "01"
    assert safe_index("1.1") == "01-01"
    assert safe_index("绪论") == "绪论"
    assert safe_index(None) == "XX"
    # 不再抛异常
    assert chapter_stem("1.1", "Test/Title") == "01-01_TestTitle"
    assert chapter_stem(None, "绪论") == "XX_绪论"


# ---------- P1-3 GBK/ANSI 编码 ----------
def test_gbk_decoding():
    txt = "第一章 绪论：预防医学的概念与三级预防。"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "gbk.txt"
        f.write_bytes(txt.encode("gb18030"))          # 模拟记事本 ANSI/GBK 保存
        got = _read_plain(f)
    assert got == txt, f"GBK 解码出错: {got!r}"
    assert "�" not in got                        # 无替换符乱码


# ---------- P1-4 缓存按内容 hash 失效 ----------
def test_cache_invalidates_on_same_size_mtime():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        cache = d / "cache"
        f = d / "note.txt"
        f.write_text("ChapterA\nAlpha1", encoding="utf-8")
        mt = f.stat().st_mtime
        a = extract_text(f, cache)
        assert "Alpha1" in a
        # 同字节数、同秒级 mtime 改内容
        f.write_text("ChapterB\nBeta22", encoding="utf-8")
        os.utime(f, (mt, mt))
        b = extract_text(f, cache)                    # force=False
        assert "Beta22" in b and "Alpha1" not in b, f"缓存误用旧内容: {b!r}"


# ---------- P0-1 截断输出不当作完整 ----------
class _Cfg:
    model = "x"; temperature = 0.3; max_tokens = 50; max_continuations = 0
    max_retries = 1; retry_backoff = 0; request_timeout = 5
    base_url = "http://x"; api_key = "k"


def test_chat_long_reports_incomplete_on_truncation():
    ds = DeepSeek(_Cfg())
    ds.chat = lambda messages, **kw: ChatResult("半句被截断", "length", {})
    res = ds.chat_long("S", "U")
    assert res.complete is False
    assert res.finish_reason == "length"


def test_chat_long_complete_when_stop():
    ds = DeepSeek(_Cfg())
    ds.chat = lambda messages, **kw: ChatResult("完整内容", "stop", {})
    res = ds.chat_long("S", "U")
    assert res.complete is True


# ---------- P1-2 bing 解析空结果 / 兜底 ----------
def test_parse_bing_empty():
    assert _parse_bing("<html><body>no results</body></html>", 5) == []


def test_parse_bing_b_algo():
    html = ('<li class="b_algo"><h2><a href="https://who.int/x">标题A</a></h2>'
            '<p>摘要A</p></li>')
    r = _parse_bing(html, 5)
    assert len(r) == 1 and r[0]["url"] == "https://who.int/x" and r[0]["title"] == "标题A"


def test_parse_bing_fallback_h2_anchor():
    # 无 b_algo，靠通用 <h2><a> 兜底
    html = '<div><h2 class="x"><a href="https://nhc.gov.cn/y">标题B</a></h2></div>'
    r = _parse_bing(html, 5)
    assert len(r) == 1 and r[0]["url"] == "https://nhc.gov.cn/y"


# ---------- P1-6 整本课本顺序无关切片 ----------
def test_slice_book_order_independent():
    # 模拟真实教材：物理顺序 头部→颈部→下肢（与大纲相反）；每“页”重复页眉、章节相隔很远。
    def chap(cn, region, mark):
        page = f"第{cn}章 {region} 正文{mark}。" + "填充内容" * 200   # 一“页”约 800+ 字
        return page * 8                                            # 8 页，页眉反复出现
    toc = "目录：第一章 头部 9 第二章 颈部 38 第三章 下肢 63\n" + "前言说明" * 200
    book = toc + chap("一", "头部", "A") + chap("二", "颈部", "B") + chap("三", "下肢", "C")
    headings = [(1, "下肢"), (2, "上肢"), (3, "头部"), (4, "颈部")]   # 大纲顺序乱
    sl = slice_book(book, headings)
    assert "正文C" in sl[1] and "正文A" not in sl[1]      # 下肢段不含头部
    assert "正文A" in sl[3] and "正文B" not in sl[3]      # 头部定位正确、不串到颈部
    assert "正文B" in sl[4]                               # 颈部定位正确
    assert sl[2] == ""                                    # 上肢课本没有 → 空（退回PPT）


# ---------- 大纲匹配：章次与小节名被拆在表格不同单元格时仍能定位 ----------
def test_slice_outline_table_split_heading():
    """复现药理大纲：① 学习目标区按主题名（绪论/传出神经系统药物/化学治疗药物）作行首标题；
    ② 进度表里『第一章 Chapter One』与小节名被 PDF 抽取拆成多行，审计据此拼成一长串
    outline_heading。旧逻辑三个候选（长串/去前缀长串/带第X章的章标题）都无法逐字定位 →
    全章 outline_excerpt 为空。修复后应靠『去第X章前缀的主题名』短锚点命中。"""
    outline = (
        "学习目标 Learning Objectives\n"
        "总论 General principles\n"
        "绪论 Introduction\n"
        "1001 理解药物的概念。\n"
        "药物代谢动力学 Pharmacokinetics\n"
        "1101 描述药物跨膜转运方式。\n"
        "传出神经系统药物 Drugs affecting the efferent nerve system\n"
        "2001 阐释传出神经系统的递质和受体。\n"
        "化学治疗药物 Chemotherapy drugs\n"
        "3001 明确化学治疗概念和常用术语。\n"
        "教学内容进度安排\n"
        # 进度表里章次与小节名被拆成多行，且小节名之间夹着学习目标编号——
        # 这正是真实大纲里 full outline_heading 无法逐字连续命中的原因。
        "第一\n章\nChapter\nOne\n绪论 Introduction\n1001-1008\n药物代谢动力学 Pharmacokinetic\n"
    )
    chapters = [
        {"index": 1, "title": "第一章 绪论",
         "outline_heading": "第一章 Chapter One 绪论 Introduction 药物代谢动力学 Pharmacokinetic"},
        {"index": 2, "title": "第二章 传出神经系统药物",
         "outline_heading": "第二章 Chapter Two 传出神经系统药理概论 ..."},
        {"index": 3, "title": "第三章 化学治疗药物",
         "outline_heading": "第三章 Chapter Three 化学治疗药物概论 Introduction to chemotherapy"},
    ]
    missing = slice_outline(outline, chapters)
    assert missing == [], f"不应有未定位章节: {missing}"
    assert chapters[0]["outline_excerpt"].startswith("绪论"), chapters[0]["outline_excerpt"][:20]
    assert "1001" in chapters[0]["outline_excerpt"] and "1101" in chapters[0]["outline_excerpt"]
    assert "传出神经系统药物" not in chapters[0]["outline_excerpt"]    # 不串到下一章
    assert "2001" in chapters[1]["outline_excerpt"]
    assert "3001" in chapters[2]["outline_excerpt"]


# ---------- P0-1 端到端：截断 → 存 .partial.md，不写正式 .md ----------
def test_generate_writes_partial_not_md_on_truncation():
    import json
    from recite.config import Config
    import recite.deepseek as dsmod
    from recite.generate import run_generate

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "教学大纲.txt").write_text("第一章 绪论\n一、概述", encoding="utf-8")
        (d / "ch1.txt").write_text("绪论：预防医学的概念。", encoding="utf-8")
        (d / "_recite").mkdir()
        (d / "_recite" / "audit.json").write_text(json.dumps({
            "subject": "预防医学",
            "chapters": [{"index": 1, "title": "绪论",
                          "sources_resolved": ["ch1.txt"], "outline_excerpt": "一、概述"}],
        }, ensure_ascii=False), encoding="utf-8")

        cfg = Config({})
        cfg.api_key = "k"
        cfg.set_source(str(d))
        cfg.max_continuations = 0

        orig = dsmod.DeepSeek.chat
        dsmod.DeepSeek.chat = lambda self, messages, **kw: dsmod.ChatResult("半句被截断", "length", {})
        try:
            run_generate(cfg, only="1", force=True)
        finally:
            dsmod.DeepSeek.chat = orig

        md = d / "output" / "01_绪论.md"
        partial = d / "output" / "01_绪论.partial.md"
        assert partial.exists(), "截断输出应存为 .partial.md"
        assert not md.exists(), "截断时不应写正式 .md"


# ---------- 打开卡死 / apikey 误报根因：.env 带 BOM 或 GBK 不应致命 ----------
def test_read_text_tolerant_bom_and_gbk():
    from recite.util import read_text_tolerant
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        f1 = d / "bom.env"
        f1.write_bytes("﻿DEEPSEEK_API_KEY=sk-bom\n".encode("utf-8"))   # UTF-8 BOM
        assert read_text_tolerant(f1).splitlines()[0] == "DEEPSEEK_API_KEY=sk-bom"
        f2 = d / "gbk.env"
        f2.write_bytes("# 我的密钥\nDEEPSEEK_API_KEY=sk-gbk\n".encode("gb18030"))  # 中文注释 ANSI/GBK
        assert "DEEPSEEK_API_KEY=sk-gbk" in read_text_tolerant(f2)            # 不抛 UnicodeDecodeError


def test_read_env_key_survives_bom_and_gbk():
    import recite.gui as g
    old = g.ENV_PATH
    with tempfile.TemporaryDirectory() as d:
        env = Path(d) / ".env"
        try:
            env.write_bytes("﻿DEEPSEEK_API_KEY=sk-bomkey\n".encode("utf-8"))   # BOM
            g.ENV_PATH = env
            os.environ.pop("DEEPSEEK_API_KEY", None)
            assert g.read_env_key() == "sk-bomkey", "BOM 让首行键名带 \\ufeff，旧逻辑读出空 key"
            env.write_bytes("# 备注\nDEEPSEEK_API_KEY=sk-gbkkey\n".encode("gb18030"))  # GBK 注释
            os.environ.pop("DEEPSEEK_API_KEY", None)
            assert g.read_env_key() == "sk-gbkkey", "GBK 字节旧逻辑抛 UnicodeDecodeError"
        finally:
            g.ENV_PATH = old
            os.environ.pop("DEEPSEEK_API_KEY", None)


# ---------- apikey 错误：401/403/402 给出可操作中文提示，而非晦涩 HTTP 文本 ----------
def test_deepseek_friendly_auth_and_billing_errors():
    import recite.deepseek as dsmod

    class _Resp:
        def __init__(self, code):
            self.status_code = code
            self.text = "server body"

        def json(self):
            return {}

    ds = dsmod.DeepSeek(_Cfg())                       # _Cfg: max_retries=1, retry_backoff=0
    orig = dsmod.requests.post
    try:
        dsmod.requests.post = lambda *a, **k: _Resp(401)
        try:
            ds.chat([{"role": "user", "content": "hi"}]); assert False, "401 应抛错"
        except RuntimeError as e:
            assert "Key" in str(e) and "401" in str(e), str(e)
        dsmod.requests.post = lambda *a, **k: _Resp(402)
        try:
            ds.chat([{"role": "user", "content": "hi"}]); assert False, "402 应抛错"
        except RuntimeError as e:
            assert "余额" in str(e), str(e)
    finally:
        dsmod.requests.post = orig


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    return passed == len(fns)


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
