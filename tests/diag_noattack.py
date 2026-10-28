"""诊断用：不加攻击，拿我们自己的 pipeline 跑几个任务，看看 utility 本来有多少。

是为了把两件事分开：
  A) 我们的 pipeline / 审批门自己有问题 —— 那没攻击时 utility 也该低，得修
  B) pipeline 没问题，低是因为攻击太狠 —— 那就对了，这正是我们想展示的场景
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

import json

from agentdojo.benchmark import run_task_without_injection_tasks
from agentdojo.logging import LOGGER_STACK, OutputLogger
from agentdojo.task_suite.load_suites import get_suite

from build_pipeline import build_pipeline

N_TASKS = int(sys.argv[1]) if len(sys.argv) > 1 else 4
POLICY = sys.argv[2] if len(sys.argv) > 2 else "full_approve"
K = int(sys.argv[3]) if len(sys.argv) > 3 else 0
VERSION = "v1.2.2"

suite = get_suite(VERSION, "banking")
logdir = Path("runs/diag_noattack")
logdir.mkdir(parents=True, exist_ok=True)

LOGGER_STACK.get().append(OutputLogger(str(logdir), live=None))

pipeline, gate, reviewer, counter = build_pipeline(POLICY, budget=K)

print(f"\n=== 无攻击诊断: policy={POLICY} k={K} tasks={N_TASKS} ===")
rows = []
for ut_id in list(suite.user_tasks.keys())[:N_TASKS]:
    ut = suite.get_user_task_by_id(ut_id)
    gate.reset_episode()
    if reviewer is not None:
        reviewer.reset_counters()
    counter.reset()
    try:
        utility, security = run_task_without_injection_tasks(
            suite, pipeline, ut, logdir=logdir, force_rerun=True,
            benchmark_version=VERSION,
        )
    except Exception as e:
        print(f"  {ut_id}: 异常 {type(e).__name__}: {e}")
        continue
    rows.append({"user_task": ut_id, "utility": bool(utility), "security": bool(security)})
    print(f"  {ut_id:14s} utility={utility} security={security} tool_calls={len(gate.decisions)}")

n = len(rows)
nu = sum(1 for r in rows if r["utility"])
print(f"\n>>> 无攻击 utility 成功率 = {nu}/{n} = {nu / n:.0%}")

Path(logdir, "noattack_result.json").write_text(
    json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
)
