"""联网核对可选来源（provider）的唯一清单。

三套界面（gui_web / gui_ctk / gui）与 config / websearch 都从这里取值，
避免各处各写一份、出现“默认来源不在下拉选项里”这类不一致。"""

# 下拉展示顺序：默认的 bing_cn（＝ authoritative“权威来源聚合”的旧名，见 websearch._dispatch）
# 在最前，其后是免 Key 的国内直连源，最后是需自备 Key 的国际接口。
PROVIDERS = [
    "bing_cn", "authoritative", "wikipedia", "pubmed", "so360", "sogou", "ddg",
    "tavily", "serper", "bing",
]

# 需检索 Key 的 provider → 对应环境变量名。
KEYED_PROVIDER_ENV = {
    "tavily": "TAVILY_API_KEY",
    "serper": "SERPER_API_KEY",
    "bing": "BING_API_KEY",
}

# 免 Key（国内可直连）—— 由 PROVIDERS 推导得到，天然不会与上表漂移。
KEYLESS_PROVIDERS = [p for p in PROVIDERS if p not in KEYED_PROVIDER_ENV]

# 界面与 config 的默认来源（与 config.yaml / README 保持一致）。必须是 PROVIDERS 成员。
DEFAULT_PROVIDER = "bing_cn"
