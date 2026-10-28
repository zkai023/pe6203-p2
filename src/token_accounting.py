"""token 计量，包一层就够，不动 agentdojo 的源码。

为什么要写这个：AgentDojo 的 OpenAILLM 调完 client.chat.completions.create 之后
把 response.usage 直接扔了，官方压根不统计 token。但作业要求把成本按三块拆开报：
策略推理、审稿人、agent 执行。只能自己记。

好在 OpenAILLM.__init__(client, model) 收的是外面传进来的 client，
所以我们塞一个包装对象进去就行，agentdojo 那边完全不用改。

三块的来源：
    policy inference     我们的 risk_tiered 是纯规则，恒为 0（这也是它的优点）
    reviewer simulation  reviewer.py 自己记
    agent execution      这个文件记
"""
from __future__ import annotations

from typing import Any


class TokenCounter:
    """一个加法器而已，把每次调用的 token 累加起来。"""

    def __init__(self, label: str = "agent"):
        self.label = label
        self.reset()

    def reset(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def record(self, usage: Any) -> None:
        """从 response.usage 里累加。usage 没有就跳过，别把实验搞崩。"""
        self.calls += 1
        if usage is None:
            return
        # openai >=1.0 用的是 prompt_tokens / completion_tokens 这两个名字
        self.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class _MeteredCompletions:
    """把 client.chat.completions 包住，只拦 create()。"""

    def __init__(self, inner: Any, counter: TokenCounter):
        self._inner = inner
        self._counter = counter

    def create(self, *args, **kwargs):
        resp = self._inner.create(*args, **kwargs)
        try:
            self._counter.record(getattr(resp, "usage", None))
        except Exception:
            # 记账失败也不能连累实验本身
            pass
        return resp

    def __getattr__(self, item):
        # 别的（比如 with_streaming_response）原样转过去
        return getattr(self._inner, item)


class _MeteredChat:
    def __init__(self, inner: Any, counter: TokenCounter):
        self._inner = inner
        self.completions = _MeteredCompletions(inner.completions, counter)

    def __getattr__(self, item):
        return getattr(self._inner, item)


class MeteredOpenAI:
    """直接顶掉 openai.OpenAI() 传给 OpenAILLM 就行。

        llm = OpenAILLM(MeteredOpenAI(), model)
        跑完之后看 llm_client.counter.summary()
    """

    def __init__(self, client: Any | None = None, counter: TokenCounter | None = None):
        import openai

        self._client = client or openai.OpenAI()
        self.counter = counter or TokenCounter("agent_execution")
        self.chat = _MeteredChat(self._client.chat, self.counter)

    def __getattr__(self, item):
        return getattr(self._client, item)


# ---------------- 把 token 折成美元，报告里用 ----------------
# 按 OpenAI 官方 gpt-4o-mini 的公开价算。
# 走 OpenRouter 的话实际可能有点出入，报告里说一句"按官方定价估算"就行。
DEFAULT_PRICING = {
    # 模型前缀 -> (input $/1M, output $/1M)
    "gpt-4o-mini": (0.15, 0.60),
}


def estimate_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "gpt-4o-mini",
    pricing: dict | None = None,
) -> float:
    pricing = pricing or DEFAULT_PRICING
    in_p, out_p = pricing.get(model, pricing["gpt-4o-mini"])
    return prompt_tokens * in_p / 1_000_000 + completion_tokens * out_p / 1_000_000
