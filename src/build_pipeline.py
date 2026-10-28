"""把审批门塞进原本放 ToolsExecutor 的那个坑里。

官方长这样：
    AgentPipeline([SystemMessage, InitQuery, llm,
                   ToolsExecutionLoop([ToolsExecutor(), llm])])

我们把它换成：
    AgentPipeline([SystemMessage, InitQuery, llm,
                   ToolsExecutionLoop([ApprovalGate(...), llm])])
                                        ^^^^^^^^^^^^ 就换了这一处

另外提醒一句：模型名在 Python API 里是 dashed 写法，
CLI 那边却是大写枚举名（GPT_4O_MINI_2024_07_18），两个别搞混。
"""
from __future__ import annotations

import os

import openai
from dotenv import load_dotenv

from agentdojo.agent_pipeline import (
    AgentPipeline,
    InitQuery,
    SystemMessage,
    ToolsExecutionLoop,
)
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM

from approval_gate import ApprovalGate
from policies import FullApprovePolicy, FullEscalatePolicy, RiskTieredPolicy
from reviewer import LLMSimulatedReviewer
from token_accounting import MeteredOpenAI

# override=True 是怕系统里留着旧变量，不然改了 .env 也白改
load_dotenv(".env", override=True)

# 模型名从 AGENTDOJO_MODEL 读。
# 走 OpenAI 官方就用 "gpt-4o-mini-2024-07-18"；走 OpenRouter 得带前缀 "openai/gpt-4o-mini"。
MODEL = os.environ.get("AGENTDOJO_MODEL") or "gpt-4o-mini-2024-07-18"

# 这里坚持用官方默认的 system message，两个原因：
# 一是公平性，我们只换了 ToolsExecutor，别的地方都得跟官方默认对齐，
#   不然曲线上的差别说不清是策略带来的还是提示词带来的；
# 二是实测过，自己手写几句短指令会明显把 utility 拉下来。
SYSTEM_MSG = load_system_message(None)


def build_pipeline(policy_name: str, budget: int = 0, model: str = MODEL):
    """policy_name 取 full_approve / full_escalate / risk_tiered 三者之一。

    返回 (pipeline, gate, reviewer, agent_counter)，
    最后那个 counter 用来记 agent 主循环烧了多少 token（报告里算钱要用）。
    """
    model = model or MODEL  # 传 None 或空字符串就是"用默认的"

    # 包一层 MeteredOpenAI，这样不用改 agentdojo 源码也能记 token。
    # 官方把 response.usage 直接扔了，这笔账只能自己来。
    agent_client = MeteredOpenAI()
    agent_counter = agent_client.counter

    llm = OpenAILLM(agent_client, model)

    if policy_name == "full_approve":
        policy = FullApprovePolicy()
    elif policy_name == "full_escalate":
        policy = FullEscalatePolicy()
    elif policy_name == "risk_tiered":
        policy = RiskTieredPolicy()
    else:
        raise ValueError(f"unknown policy: {policy_name}")

    # full_approve 压根不会叫人，给它配审稿人纯属浪费钱
    reviewer = LLMSimulatedReviewer(model=model) if policy_name != "full_approve" else None

    gate = ApprovalGate(policy=policy, reviewer=reviewer, budget=budget)

    tools_loop = ToolsExecutionLoop([gate, llm])
    pipeline = AgentPipeline([SystemMessage(SYSTEM_MSG), InitQuery(), llm, tools_loop])

    # 官方的攻击器（比如 important_instructions）会拿 pipeline.name 去反推模型名写攻击提示词，
    # 它是 None 的话直接抛 ValueError: Pipeline name is `None`。
    # 官方 from_config 也是构造完手动赋值的，这里照做。
    # 注意名字里得包含 agentdojo.models.MODEL_NAMES 的 key：
    # "openai/gpt-4o-mini-2024-07-18" 里有 "gpt-4o-mini-2024-07-18"，能命中，映射到 "GPT-4"。
    pipeline.name = model

    return pipeline, gate, reviewer, agent_counter
