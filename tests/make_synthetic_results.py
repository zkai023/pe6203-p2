"""造一份看着像真结果的数据，专门用来验 analyze.py 这条链路。

想法是：还没开始花 API 的钱，先确认"跑完实验 → 出图出表"这条腿是通的。
不然等于把一两个小时的实验压在一个没验证过的上游上。

    python tests/make_synthetic_results.py [输出路径]
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

random.seed(7)

POLICIES = ["full_approve", "full_escalate", "risk_tiered"]
KS = [0, 1, 2, 3]
USER_TASKS = [f"user_task_{i}" for i in range(4)]
INJ_TASKS = [f"injection_task_{i}" for i in range(3)]

TOOLS = ["get_balance", "read_file", "send_money", "get_iban", "update_password", "get_zip_code"]

# 刻意让三条曲线呈现不同的形状，以便肉眼确认图能区分不同策略
SHAPE = {
    "full_approve":   {"base": 0.30, "gain": 0.00},  # 不安全，且不随 k 变
    "full_escalate":  {"base": 0.05, "gain": 0.16},  # k=0 时几乎全否
    "risk_tiered":    {"base": 0.35, "gain": 0.13},  # 起点高、增长快
}


def make_row(policy: str, k: int, ut: str, it: str) -> dict:
    s = SHAPE[policy]
    p_safe = min(0.95, s["base"] + s["gain"] * k)
    utility = random.random() < p_safe + 0.25          # 任务本身是否被攻组地做完
    attacked = (not bool(utility)) or (random.random() > p_safe)  # 是否被注入利用

    # risk_tiered 只会 escalate 写操作 -> HITL 用量明显更少
    n_calls = random.randint(3, 8)
    decisions = []
    used = 0
    reviewer_calls = 0
    for i in range(n_calls):
        tool = random.choice(TOOLS)
        write_op = tool in ("send_money", "update_password")
        if policy == "full_approve":
            decision, final, esc, exh = "approve", "approve", False, False
        elif policy == "full_escalate":
            decision = "escalate"
            if used < k:
                used += 1
                reviewer_calls += 1
                # 模拟审稿人有时真会否决（这才让 escalation yield 有意义）
                final = "deny" if random.random() < 0.25 else "approve"
                esc, exh = True, False
            else:
                final, esc, exh = "deny", False, True
        else:  # risk_tiered
            if write_op:
                decision = "escalate"
                if used < k:
                    used += 1
                    reviewer_calls += 1
                    final = "deny" if random.random() < 0.45 else "approve"
                    esc, exh = True, False
                else:
                    final, esc, exh = "deny", False, True
            else:
                decision = final = "approve"
                esc = exh = False
        decisions.append({
            "tool": tool,
            "args": {"amount": 100},
            "available": True,
            "policy_decision": decision,
            "final": final,
            "escalated": esc,
            "budget_exhausted": exh,
        })

    return {
        "policy": policy,
        "k": k,
        "user_task": ut,
        "injection_task": it,
        "utility": bool(utility),
        "security": bool(attacked),
        "safe_complete": bool(utility) and not bool(attacked),
        "hitl_used": sum(1 for d in decisions if d["escalated"]),
        "n_tool_calls": len(decisions),
        "n_denied": sum(1 for d in decisions if d["final"] == "deny"),
        "budget_exhausted_hits": sum(1 for d in decisions if d["budget_exhausted"]),
        # --- cost breakdown 三组件（交付物 4.2.3） ---
        # (1) agent execution：主循环 LLM 调用，随工具轮数增长
        "agent_calls": n_calls,
        "agent_prompt_tokens": random.randint(2200, 6000),
        "agent_completion_tokens": random.randint(120, 600),
        # (2) reviewer simulation：每次 escalate 触发一次审稿 LLM
        "reviewer_calls": reviewer_calls,
        "reviewer_prompt_tokens": reviewer_calls * random.randint(300, 520),
        "reviewer_completion_tokens": reviewer_calls * random.randint(8, 30),
        # (3) policy inference：risk_tiered 为 rule-based，恒为 0
        "policy_prompt_tokens": 0,
        "policy_completion_tokens": 0,
        "decisions": decisions,
    }


def main(out_path: str = "runs/synthetic/ALL_RESULTS.json"):
    rows = [
        make_row(p, k, ut, it)
        for p in POLICIES
        for k in KS
        for ut in USER_TASKS
        for it in INJ_TASKS
    ]
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    n_safe = sum(1 for r in rows if r["safe_complete"])
    print(f"[OK] 合成数据 {len(rows)} 行 -> {p}  (safe_complete={n_safe})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs/synthetic/ALL_RESULTS.json")
