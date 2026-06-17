"""配置加载：合并 .env + config.yaml，解析并校验路径。"""
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    raise SystemExit("缺少依赖 PyYAML，请先运行: pip install -r requirements.txt")

# 程序根目录：源码运行=本项目目录；PyInstaller 打包后=exe 所在目录
# （这样 .env / config.yaml / gui_state.json 始终落在用户看得见的位置）
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path):
    """极简 .env 解析，不覆盖已存在的环境变量。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Config:
    def __init__(self, data: dict):
        # API
        self.api_key = (os.environ.get("DEEPSEEK_API_KEY") or data.get("api_key") or "").strip()
        self.base_url = (data.get("base_url") or "https://api.deepseek.com").rstrip("/")
        self.model = data.get("model") or "deepseek-chat"
        self.temperature = float(data.get("temperature", 0.3))
        self.audit_temperature = float(data.get("audit_temperature", 0.2))
        self.max_tokens = int(data.get("max_tokens", 8192))
        self.request_timeout = int(data.get("request_timeout", 300))
        self.max_retries = int(data.get("max_retries", 5))
        self.max_continuations = int(data.get("max_continuations", 8))
        self.retry_backoff = float(data.get("retry_backoff", 3))

        # 路径。source_dir 允许为空（图形界面里再选）；真正使用前由 require_source 校验
        src = (data.get("source_dir") or "").strip()
        self.source_dir = Path(src).expanduser() if src else (ROOT / "_未选择资料文件夹")
        self.outline_file = (data.get("outline_file") or "").strip()
        self.output_dir = Path(data["output_dir"]).expanduser() if data.get("output_dir") \
            else self.source_dir / "output"
        self.work_dir = Path(data["work_dir"]).expanduser() if data.get("work_dir") \
            else self.source_dir / "_recite"

        self.subject = (data.get("subject") or "").strip()
        # 课程说明 / 整理偏好（在不违反铁律的前提下，因地制宜地影响所有章节）
        self.subject_note = (data.get("subject_note") or "").strip()
        self.ignore = list(data.get("ignore") or [])

        # 联网核对（web 检索 → 真实来源补充）
        self.search_provider = (data.get("search_provider") or "bing_cn").strip().lower()
        # 主搜索源无结果时的回退源（国内可直连、免 Key）；设空字符串可关闭回退
        self.search_fallback = (data.get("search_fallback", "pubmed") or "").strip().lower()
        self.search_api_key = (data.get("search_api_key") or "").strip()
        self.trusted_domains = list(data.get("trusted_domains") or [])
        self.search_max_results = int(data.get("search_max_results", 5))
        self.search_fetch_pages = bool(data.get("search_fetch_pages", True))
        self.verify_max_items = int(data.get("verify_max_items", 8))
        self.fetch_timeout = int(data.get("fetch_timeout", 20))
        # 整本电子课本切到单章时的字数上限（防止 prompt 超上下文；细节需求高可调大）
        self.book_slice_max_chars = int(data.get("book_slice_max_chars", 40000))

        # 派生路径
        self.cache_dir = self.work_dir / "cache"
        self.prompts_dir = self.work_dir / "prompts"
        self.audit_path = self.work_dir / "audit.json"

    # ---- 便捷方法 ----
    def set_source(self, path) -> None:
        """切换母文件夹，并按默认布局重算 output/_recite 等派生路径。"""
        self.source_dir = Path(path).expanduser()
        self.output_dir = self.source_dir / "output"
        self.work_dir = self.source_dir / "_recite"
        self.cache_dir = self.work_dir / "cache"
        self.prompts_dir = self.work_dir / "prompts"
        self.audit_path = self.work_dir / "audit.json"

    def ensure_dirs(self):
        for d in (self.work_dir, self.cache_dir, self.prompts_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    def require_api_key(self):
        if not self.api_key:
            raise SystemExit("未提供 DeepSeek API Key：请在 .env 写 DEEPSEEK_API_KEY=...，"
                             "或在 config.yaml 的 api_key 填入。")

    def require_source(self):
        if not self.source_dir.exists():
            raise SystemExit(f"source_dir 不存在: {self.source_dir}")

    def search_key(self) -> str:
        """检索 Key：优先环境变量（按 provider），其次 config 的 search_api_key。"""
        env_name = {"tavily": "TAVILY_API_KEY", "serper": "SERPER_API_KEY",
                    "bing": "BING_API_KEY"}.get(self.search_provider)
        return ((os.environ.get(env_name) if env_name else "") or self.search_api_key or "").strip()

    def require_search_key(self):
        if self.search_provider in ("tavily", "serper", "bing") and not self.search_key():
            raise SystemExit(f"联网核对所选 provider={self.search_provider} 需要检索 Key："
                             f"请在界面“设置检索Key”或 .env 填入对应的 KEY。")


def load_config(config_path: str | None = None) -> Config:
    _load_dotenv(ROOT / ".env")
    if config_path:
        path = Path(config_path)
    else:
        path = ROOT / "config.yaml"
        if not path.exists():
            path = ROOT / "config.example.yaml"     # 退一步用示例
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # 找不到任何配置也能启动（用内置默认 + 图形界面里现选文件夹）
    return Config(data)
