"""DeepSeek（OpenAI 兼容）聊天客户端：重试、限流退避、JSON 模式、长度续写。"""
import time
import json
import requests


class ChatResult:
    def __init__(self, content: str, finish_reason: str, usage: dict):
        self.content = content
        self.finish_reason = finish_reason
        self.usage = usage or {}


class LongResult:
    """chat_long 的结果。complete=False 表示用尽续写后仍被截断。"""
    def __init__(self, text: str, usage: dict, complete: bool,
                 finish_reason: str, continuations: int):
        self.text = text
        self.usage = usage or {}
        self.complete = complete
        self.finish_reason = finish_reason
        self.continuations = continuations


class DeepSeek:
    def __init__(self, cfg):
        self.cfg = cfg
        self.url = f"{cfg.base_url}/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, payload: dict) -> dict:
        last_err = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = requests.post(self.url, headers=self.headers,
                                     data=json.dumps(payload),
                                     timeout=self.cfg.request_timeout)
                if resp.status_code == 200:
                    return resp.json()
                # 限流 / 服务端错误：退避重试
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    if attempt >= self.cfg.max_retries:      # 最后一次失败：不再退避白等，直接报错
                        break
                    wait = self.cfg.retry_backoff * attempt
                    print(f"    · API {resp.status_code}，{wait:.0f}s 后重试 ({attempt}/{self.cfg.max_retries})")
                    time.sleep(wait)
                    continue
                # 鉴权 / 计费类错误：重试无用，给出可操作的中文提示（用户最常见的“apikey 错误”）
                if resp.status_code in (401, 403):
                    raise RuntimeError(
                        f"DeepSeek API Key 无效或无权限（HTTP {resp.status_code}）："
                        "请点界面『设置 / 修改密钥』填入正确的、以 sk- 开头的 Key。")
                if resp.status_code == 402:
                    raise RuntimeError(
                        "DeepSeek 账户余额不足（HTTP 402）：请到 platform.deepseek.com 充值后重试。")
                # 其它错误：直接抛
                raise RuntimeError(f"DeepSeek API 错误 HTTP {resp.status_code}: {resp.text[:500]}")
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = str(e)
                if attempt >= self.cfg.max_retries:          # 最后一次失败：不再退避白等，直接报错
                    break
                wait = self.cfg.retry_backoff * attempt
                print(f"    · 网络异常({type(e).__name__})，{wait:.0f}s 后重试 ({attempt}/{self.cfg.max_retries})")
                time.sleep(wait)
        raise RuntimeError(f"DeepSeek API 多次重试仍失败: {last_err}")

    def chat(self, messages: list[dict], *, temperature=None, max_tokens=None,
             json_mode=False) -> ChatResult:
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post(payload)
        choice = data["choices"][0]
        return ChatResult(
            content=choice["message"]["content"] or "",
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
        )

    def chat_long(self, system: str, user: str, *, reminder: str = "",
                  on_progress=None) -> "LongResult":
        """一次问答；若因 max_tokens 被截断(finish_reason=='length')则自动续写拼接。
        reminder：每段续写都重申的硬性要求（如名词标英文等），防止长章节中途遗忘。
        返回 LongResult(text, usage, complete, finish_reason, continuations)；
        complete=False 表示用尽续写后仍被截断，调用方不应当作正式成品保存。"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        cont = ("继续：从上次中断处接着输出，不要重复已输出的任何内容，"
                "继续严格遵守全部铁律与排版金标准")
        if reminder and reminder.strip():
            cont += "，尤其是本课程硬性要求：" + reminder.strip()
        cont += "，直到本章结束。"

        full = []
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0}
        rounds = 0
        last_finish = ""
        while True:
            res = self.chat(messages, temperature=self.cfg.temperature)
            full.append(res.content)
            last_finish = res.finish_reason
            usage_total["prompt_tokens"] += res.usage.get("prompt_tokens", 0)
            usage_total["completion_tokens"] += res.usage.get("completion_tokens", 0)
            if on_progress:
                on_progress(rounds + 1, res.finish_reason, res.usage)
            if res.finish_reason != "length" or rounds >= self.cfg.max_continuations:
                break
            messages.append({"role": "assistant", "content": res.content})
            messages.append({"role": "user", "content": cont})
            rounds += 1
        complete = (last_finish != "length")
        return LongResult("".join(full), usage_total, complete, last_finish, rounds)
