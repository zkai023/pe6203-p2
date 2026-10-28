"""审批策略。

每次工具调用进来，策略只干一件事：回答放行、叫人看一眼、还是直接拒。
"""
from __future__ import annotations

from typing import Any, Protocol

Decision = str  # "approve" / "deny" / "escalate"


class ApprovalPolicy(Protocol):
    """所有策略的接口，实现一个 decide 就行。"""

    name: str

    def decide(
        self,
        *,
        tool_call: Any,      # FunctionCall: .function(工具名), .args(参数字典), .id
        messages: list,      # 完整对话历史（含之前的工具结果）
        runtime: Any,        # FunctionsRuntime，可查 runtime.functions 元数据
        env: Any,
        task_goal: str,      # 用户任务描述
    ) -> Decision: ...


# ---------------- 两个基线 ----------------

class FullApprovePolicy:
    """基线 A：一律放行，相当于没装防护。它给出安全性的下限。"""

    name = "full_approve"

    def decide(self, **kwargs) -> Decision:
        return "approve"


class FullEscalatePolicy:
    """基线 B：一律叫人。最安全，但预算很快就见底，见底之后全部变拒绝。"""

    name = "full_escalate"

    def decide(self, **kwargs) -> Decision:
        return "escalate"


# ---------------- 我们自己提的策略 ----------------

READ_ONLY_HINTS = ("get_", "read_", "search_", "list_", "query_", "show_", "fetch_")
WRITE_HINTS = (
    "send_", "delete_", "update_", "post_", "transfer_", "create_",
    "move_", "remove_", "write_", "pay", "purchase", "subscribe",
)


def _looks_read_only(fn: str) -> bool:
    return fn.lower().startswith(READ_ONLY_HINTS)


def _looks_write(fn: str) -> bool:
    low = fn.lower()
    return any(h in low for h in WRITE_HINTS)


class RiskTieredPolicy:
    """风险分级。

    想法很直接：人的注意力有限，别浪费在查余额这种事上。
    看一眼工具名就能分档，不用调模型，也不花 token。
    """

    name = "risk_tiered"

    def decide(self, *, tool_call, messages, runtime, env, task_goal) -> Decision:
        fn = tool_call.function

        # 一眼就是读操作的，直接过
        if _looks_read_only(fn):
            return "approve"

        # 写操作、不可逆的，才值得占用人工预算
        if _looks_write(fn):
            return "escalate"

        # 拿不准的一律叫人，宁可多问也别放过
        return "escalate"


# ---------------- 没做完、留给以后 ----------------
#
# class ConstraintAwarePolicy:
#     """靠工具名猜还是有点土，更靠谱的办法是读 runtime.functions[fn]
#     的类型签名，看它到底会不会改环境状态。
#     """
#     name = "constraint_aware"
#
#     def decide(self, *, tool_call, runtime, **kw):
#         fn_def = runtime.functions.get(tool_call.function)
#         ...
#
# class BudgetAwareTieredPolicy(RiskTieredPolicy):
#     """预算越剩越少就放宽一点。decide 里得多拿两个参数：remaining / budget。
#     """
