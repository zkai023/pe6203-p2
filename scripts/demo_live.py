"""演示专用脚本 —— 在投影上 30 秒讲清楚"审批门到底做了什么"。

两种模式：

    python scripts/demo_live.py            # 离线重放（默认）
    python scripts/demo_live.py --live     # 真跑一次 API

离线模式读的是 runs/final/ALL_RESULTS.json 里**真实跑出来**的轨迹，
不联网、不花钱、不可能翻车，投屏前可以先跑一遍确认。

默认挑的这条是 user_task_6 + injection_task_0，特别能说明问题：
同一条任务、同一条注入，不设防时钱被转走了；上了我们的门，
任务照样做完，钱没动。两条放一起看，比讲十页 PPT 都直观。

之所以要写一个专门的脚本而不是直接看 JSON：原始 JSON 一行几百个字符，
投影上根本看不清。这里只留下"哪一步、调了什么、门怎么判的、最后是啥结果"。
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "runs" / "final" / "ALL_RESULTS.json"

# 默认展示的这条轨迹，是在 360 次结果里挑出来的：
# 不设防时攻击完全得逞，上了门之后任务照样完成
DEFAULT_TASK = "user_task_6"
DEFAULT_INJ = "injection_task_0"

LINE = "=" * 96
THIN = "-" * 96


def _short(value, limit=44):
    """把某个参数值压短，保证一行放得下。"""
    s = str(value)
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _format_args(args: dict) -> str:
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        # 账户号是 24 位，阈值要到 18 才抓得住
        if isinstance(v, str) and len(v) > 18:
            # 账户号之类的长串保留头尾，中间省略。不然 IBAN 会把金额挤没了
            v = v[:6] + "..." + v[-4:]
        parts.append(f"{k}={_short(v, 30)}")
    return ", ".join(parts)


def _verdict(d: dict) -> tuple[str, str]:
    """把一条决策翻译成"投影上能看懂"的说法。

    返回 (这一列写什么, 备注要不要加叹号)。
    """
    if d["policy_decision"] == "approve":
        return "AUTO-OK", ""
    if d["budget_exhausted"]:
        return "NO BUDGET", "预算用完了，按deny处理"
    if d["escalated"]:
        return ("HUMAN:BLOCK", "人否了") if d["final"] == "deny" \
            else ("HUMAN:ALLOW", "人放行了")
    return d["final"].upper(), ""


def _print_run(run: dict, tag: str, note: str, slow: bool):
    print()
    print(f"[{tag}]  {run['policy']}   budget k={run['k']}      {note}")
    print(THIN)
    print(f"{'step':>4}  {'tool call':<66} {'gate':<14} outcome")
    print(THIN)

    for i, d in enumerate(run["decisions"], 1):
        call = f"{d['tool']}({_format_args(d['args'])})"
        if len(call) > 66:
            call = call[:63] + "..."
        verdict, extra = _verdict(d)
        outcome = "EXECUTED" if d["final"] == "approve" else "BLOCKED"
        flag = "   <-- " + extra if extra else ""
        print(f"{i:>4}  {call:<68} {verdict:<14} {outcome}{flag}")
        if slow:
            time.sleep(0.18)

    print(THIN)
    done = run["utility"]
    attack_won = run["security"]
    print(
        f"  task done: {done}     attack succeeded: {attack_won}     "
        f"=> TCR(safe complete): {run['safe_complete']}"
    )
    print(
        f"  tool calls: {run['n_tool_calls']}   "
        f"human interruptions used: {run['hitl_used']}/{run['k']}"
    )


def run_offline(task: str, inj: str, slow: bool):
    if not RESULTS.exists():
        print(f"找不到结果文件: {RESULTS}")
        print("先跑一次正式评测，或者改用 --live 现场跑。")
        return

    rows = json.loads(RESULTS.read_text(encoding="utf-8"))
    want = [(r["policy"], r["k"]) for r in rows
            if r["user_task"] == task and r["injection_task"] == inj]
    if not want:
        print(f"结果里没有 {task} + {inj} 这条。可用的组合：")
        for t, i in sorted({(r["user_task"], r["injection_task"]) for r in rows}):
            print(f"  {t}  {i}")
        return

    def pick(policy, k):
        for r in rows:
            if (r["user_task"], r["injection_task"], r["policy"], r["k"]) \
                    == (task, inj, policy, k):
                return r
        return None

    print(LINE)
    print(" DEMO - one task, one injection, two very different endings")
    print(f" task={task}   injection={inj}   attack=important_instructions")
    print(" source: runs/final/ALL_RESULTS.json  (real runs, replayed here)")
    print(LINE)

    a = pick("full_approve", 0)
    b = pick("risk_tiered", 2)
    if a:
        _print_run(a, "1/2", "no gate at all - today's default", slow)
    if b:
        _print_run(b, "2/2", "our risk_tiered policy", slow)

    print()
    print(LINE)
    print(" Same task. Same injected text. Same model.")
    if a and b:
        print(
            f" No gate  -> task done={a['utility']}, "
            f"attack succeeded={a['security']}"
        )
        print(
            f" Our gate -> task done={b['utility']}, "
            f"attack succeeded={b['security']}, "
            f"and it only asked a human {b['hitl_used']} times"
        )
    print(LINE)


def run_live(task: str, inj: str, policy: str, k: int, slow: bool):
    """真跑一次。会花钱（一次大约 $0.001）也需要网络，所以不是默认选项。"""
    import sys

    from dotenv import load_dotenv

    # 这个脚本在 scripts/ 下，而模块都在 src/ 下，得手动把 src 挂进搜索路径
    sys.path.insert(0, str(ROOT / "src"))

    load_dotenv(ROOT / ".env", override=True)

    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.benchmark import run_task_with_injection_tasks
    from agentdojo.logging import LOGGER_STACK, OutputLogger
    from agentdojo.task_suite.load_suites import get_suite

    from build_pipeline import build_pipeline

    logging.getLogger().setLevel(logging.WARNING)

    suite = get_suite("v1.2.2", "banking")
    pipeline, gate, reviewer, counter = build_pipeline(policy, budget=k)
    attacker = load_attack("important_instructions", suite, pipeline)

    ut = suite.get_user_task_by_id(task)
    gate.reset_episode()
    if reviewer is not None:
        reviewer.reset_counters()
    counter.reset()

    logdir = ROOT / "runs" / "demo_live"
    logdir.mkdir(parents=True, exist_ok=True)
    LOGGER_STACK.get().append(OutputLogger(str(logdir), live=None))

    print(LINE)
    print(" LIVE DEMO - running right now")
    print(f" policy={policy}  k={k}  task={task}  injection={inj}")
    print(LINE)

    try:
        u_res, s_res = run_task_with_injection_tasks(
            suite=suite,
            agent_pipeline=pipeline,
            user_task=ut,
            attack=attacker,
            logdir=logdir,
            force_rerun=True,
            injection_tasks=[inj],
            benchmark_version="v1.2.2",
        )
    finally:
        LOGGER_STACK.get().pop()

    (u_from, i_from), utility = list(u_res.items())[0]
    security = s_res[(u_from, i_from)]

    run = {
        "policy": policy, "k": k, "decisions": gate.decisions,
        "utility": bool(utility), "security": bool(security),
        "safe_complete": bool(utility) and not bool(security),
        "n_tool_calls": len(gate.decisions),
        "hitl_used": sum(1 for d in gate.decisions if d["escalated"]),
    }
    _print_run(run, "LIVE", "just ran in front of you", slow)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=DEFAULT_TASK)
    ap.add_argument("--injection", default=DEFAULT_INJ)
    ap.add_argument("--policy", default="risk_tiered", help="只在 --live 时生效")
    ap.add_argument("--k", type=int, default=2, help="只在 --live 时生效")
    ap.add_argument("--live", action="store_true", help="真跑一次 API")
    ap.add_argument(
        "--slow", action="store_true",
        help="每一步停 0.18 秒，投屏时观众跟得上",
    )
    args = ap.parse_args()

    if args.live:
        run_live(args.task, args.injection, args.policy, args.k, args.slow)
    else:
        run_offline(args.task, args.injection, args.slow)


if __name__ == "__main__":
    main()
