"""离线冒烟测试：不依赖 agentdojo、不需要 API key。

验证三选一策略逻辑是否按预期工作。
    python tests/test_policies_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from policies import (  # noqa: E402
    FullApprovePolicy,
    FullEscalatePolicy,
    RiskTieredPolicy,
)

VALID = {"approve", "deny", "escalate"}


class FakeToolCall:
    def __init__(self, fn, args=None, cid="c1"):
        self.function = fn
        self.args = args or {}
        self.id = cid


def decide(policy, tool_name):
    return policy.decide(
        tool_call=FakeToolCall(tool_name),
        messages=[],
        runtime=None,
        env=None,
        task_goal="do the task",
    )


failed = 0


def expect(label, got, want):
    global failed
    ok = got == want
    if got not in VALID:
        ok = False
    print(f"[{'OK' if ok else 'FAIL'}] {label:<52} got={got:<9} want={want}")
    if not ok:
        failed += 1


print("=" * 78)
print("policies 冒烟测试")
print("=" * 78)

# ---- 基线 A: 全通过，任何工具都放行 ----
pa = FullApprovePolicy()
for fn in ["get_balance", "send_money", "delete_file", "search_inbox"]:
    expect(f"full_approve / {fn}", decide(pa, fn), "approve")

# ---- 基线 B: 全升级，任何工具都叫人 ----
pb = FullEscalatePolicy()
for fn in ["get_balance", "send_money"]:
    expect(f"full_escalate / {fn}", decide(pb, fn), "escalate")

# ---- 自研: 只读放行，写操作升级 ----
pr = RiskTieredPolicy()
expect("risk_tiered / get_balance   (只读)", decide(pr, "get_balance"), "approve")
expect("risk_tiered / search_inbox  (只读)", decide(pr, "search_inbox"), "approve")
expect("risk_tiered / send_money    (写)", decide(pr, "send_money"), "escalate")
expect("risk_tiered / delete_file   (写)", decide(pr, "delete_file"), "escalate")
expect("risk_tiered / update_calendar(写)", decide(pr, "update_calendar"), "escalate")

print("=" * 78)
if failed:
    print(f"{failed} 项失败 —— 修好再往下走。")
    sys.exit(1)
print("全部通过 —— 策略层逻辑正确，可以进入跑实验阶段。")
