"""跑实验的主脚本：策略 × 预算 k，把原始结果存成 JSON。

    # 调试用，省钱：2 个 user task，3 个 k
    python src/run_experiments.py --suite-name banking --limit-tasks 2 --k-values 0,2,5

    # 正式跑
    python src/run_experiments.py --suite-name banking --k-values 0,1,2,3,5,8,12

结果落在 --logdir 底下（默认 runs/v1）。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import typer

from dotenv import load_dotenv

from agentdojo.attacks.attack_registry import ATTACKS, load_attack
from agentdojo.benchmark import run_task_with_injection_tasks
from agentdojo.logging import LOGGER_STACK, OutputLogger
from agentdojo.task_suite.load_suites import get_suite, get_suites

from build_pipeline import MODEL as PIPELINE_MODEL
from build_pipeline import build_pipeline

app = typer.Typer()

# 默认用这个攻击。到底能用哪些，看你装的版本的 ATTACKS 名单，脚本启动时也会打出来
DEFAULT_ATTACK = "important_instructions"

# get_suites 得传版本字符串。传 None 会因为 defaultdict 静默返回空 dict，
# 表现是"自检说没问题，但 suites 是空的"，排查起来很费时间
DEFAULT_VERSION = "v1.2.2"


@app.command()
def main(
    suite_name: str = typer.Option("banking", help=" bankingsuite 任务最少，适合起步"),
    k_values: str = typer.Option("0,1,2,3,5,8", help="预算 k 的取值列表，逗号分隔"),
    policies: str = typer.Option(
        "full_approve,full_escalate,risk_tiered", help="要跑的策略，逗号分隔"
    ),
    attack: str = typer.Option(DEFAULT_ATTACK, help="攻击名；不在 ATTACKS 里会报错"),
    limit_tasks: int = typer.Option(0, help=">0 时只跑前 N 个 user task（强烈建议调试时用）"),
    limit_injections: int = typer.Option(0, help=">0 时只跑前 N 个 injection task（控制成本最有效）"),
    benchmark_version: str = typer.Option(DEFAULT_VERSION, help="benchmark 版本字符串，如 v1.2.2"),
    model: str = typer.Option("", help="覆盖模型名；留空则用 .env 的 AGENTDOJO_MODEL"),
    logdir: str = typer.Option("runs/v1", help="日志与结果根目录"),
    force_rerun: bool = typer.Option(True, help="True=忽略已有日志重跑"),
):
    print("=" * 60)
    print(f"可用攻击名单 ATTACKS（共 {len(ATTACKS)}）:", list(ATTACKS))
    print("=" * 60)
    if attack not in ATTACKS:
        raise typer.BadParameter(
            f"attack='{attack}' 不在名单里。请从上面 ATTACKS 中选一个。"
        )

    load_dotenv(".env", override=True)

    ks = [int(x) for x in k_values.split(",") if x.strip()]
    policy_list = [p.strip() for p in policies.split(",")]
    logdir_root = Path(logdir)
    logdir_root.mkdir(parents=True, exist_ok=True)

    suites = get_suites(benchmark_version)
    if not suites:
        raise typer.BadParameter(
            f"版本 '{benchmark_version}' 下 suites 为空！请检查 --benchmark-version"
        )
    if suite_name not in suites:
        raise typer.BadParameter(f"suite='{suite_name}' 不存在。可选: {list(suites)}")
    suite = get_suite(benchmark_version, suite_name)

    user_task_ids = list(suite.user_tasks.keys())
    if limit_tasks > 0:
        user_task_ids = user_task_ids[:limit_tasks]

    injection_ids = list(suite.injection_tasks.keys())
    if limit_injections > 0:
        injection_ids = injection_ids[:limit_injections]

    n_combo = len(user_task_ids) * len(injection_ids)
    print(f"\nsuite={suite_name} (benchmark v{benchmark_version})")
    print(f"使用的模型 = {model or PIPELINE_MODEL}")
    print(f"user_tasks={len(user_task_ids)}  injection_tasks={len(injection_ids)}")
    print(f"policies={policy_list}  attack={attack}  k={ks}")
    print(f"每个 (policy,k) 要跑 {n_combo} 个组合；一共 {n_combo * len(ks) * len(policy_list)} 次 agent 运行\n")

    all_out = []
    cost_rows = []

    # 官方 benchmark 自己会往控制台刷一堆逐轮日志，关掉它，
    # 只留我们自己的进度行。跑久了不然会被 PyCharm 的控制台拖慢。
    logging.getLogger().setLevel(logging.WARNING)

    # 中途 Ctrl-C 或者报错，也得把已经跑出来的部分存下来
    try:
        for policy_name in policy_list:
            for k in ks:
                # 每个 (policy,k) 用独立子目录，避免官方 TraceLogger 不同配置互相覆盖
                logdir_p = logdir_root / f"{policy_name}_k{k}"
                logdir_p.mkdir(parents=True, exist_ok=True)

                pipeline, gate, reviewer, agent_counter = build_pipeline(
                    policy_name, budget=k, model=(model or None)
                )
                attacker = load_attack(attack, suite, pipeline)

                print(f"\n=== policy={policy_name}  k={k} ===")
                t0 = time.time()

                # 官方 benchmark 是把运行包在 with OutputLogger(logdir) 里面的。
                # 不包的话 Logger.get() 会退化成 NullLogger（没有 logdir），
                # 一进 TraceLogger 就报 'NullLogger' object has no attribute 'logdir'。
                # 这里直接压栈，效果跟 with 一样，好处是每个 (policy,k) 能换自己的 logdir，
                # 不用把整段循环再缩进一层。
                LOGGER_STACK.get().append(OutputLogger(str(logdir_p), live=None))

                for ut_id in user_task_ids:
                    ut = suite.get_user_task_by_id(ut_id)
                    for it_id in injection_ids:
                        # k 是按任务算的，所以每个任务实例开始前都要重置预算
                        gate.reset_episode()
                        if reviewer is not None:
                            reviewer.reset_counters()
                        # token 也按任务清零，不然成本分解里的账是混的
                        agent_counter.reset()

                        u_res, s_res = run_task_with_injection_tasks(
                            suite=suite,
                            agent_pipeline=pipeline,
                            user_task=ut,
                            attack=attacker,
                            logdir=logdir_p,
                            force_rerun=force_rerun,
                            injection_tasks=[it_id],
                            benchmark_version=benchmark_version,
                        )

                        # 这一轮烧了多少 token，拆成 agent 和 reviewer 两块
                        agent_usage = agent_counter.summary()
                        if reviewer is not None:
                            reviewer_usage = reviewer.summary()
                        else:
                            reviewer_usage = {
                                "calls": 0, "prompt_tokens": 0, "completion_tokens": 0
                            }

                        # 通常 injection_tasks 只传了 1 个，故 u_res 只有 1 项，账目干净
                        n_runs = max(1, len(u_res))

                        for (u_from, i_from), utility in u_res.items():
                            security = s_res[(u_from, i_from)]
                            all_out.append({
                                "policy": policy_name,
                                "k": k,
                                "user_task": u_from,
                                "injection_task": i_from,
                                # 这里特别容易搞反：security=True 是"攻击得手了"，不是"安全"
                                "utility": bool(utility),
                                "security": bool(security),
                                "safe_complete": bool(utility) and not bool(security),
                                "hitl_used": sum(1 for d in gate.decisions if d["escalated"]),
                                "n_tool_calls": len(gate.decisions),
                                "n_denied": sum(1 for d in gate.decisions if d["final"] == "deny"),
                                "budget_exhausted_hits": sum(
                                    1 for d in gate.decisions if d["budget_exhausted"]
                                ),
                                # --- 成本拆三块 ---
                                # (1) agent execution：LLM 主循环
                                "agent_prompt_tokens": agent_usage["prompt_tokens"] // n_runs,
                                "agent_completion_tokens": agent_usage["completion_tokens"] // n_runs,
                                "agent_calls": agent_usage["calls"] // n_runs,
                                # (2) reviewer simulation：模拟人工审稿人
                                "reviewer_calls": reviewer_usage["calls"] // n_runs,
                                "reviewer_prompt_tokens": reviewer_usage["prompt_tokens"] // n_runs,
                                "reviewer_completion_tokens": reviewer_usage["completion_tokens"] // n_runs,
                                # (3) policy inference：risk_tiered 是纯规则，恒为 0
                                "policy_prompt_tokens": 0,
                                "policy_completion_tokens": 0,
                                "decisions": gate.decisions,
                            })

                        cost_rows.append({
                            "policy": policy_name, "k": k, "task": ut_id,
                            "injection": it_id,
                            "agent_prompt_tokens": agent_usage["prompt_tokens"],
                            "agent_completion_tokens": agent_usage["completion_tokens"],
                            "agent_calls": agent_usage["calls"],
                            "reviewer_calls": reviewer_usage["calls"],
                            "reviewer_prompt_tokens": reviewer_usage["prompt_tokens"],
                            "reviewer_completion_tokens": reviewer_usage["completion_tokens"],
                            "policy_prompt_tokens": 0,
                            "policy_completion_tokens": 0,
                        })

                # 弹出本轮 logger（与上面的压栈配对）
                LOGGER_STACK.get().pop()

                (logdir_p / f"{policy_name}_k{k}.json").write_text(
                    json.dumps(all_out, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                print(f"  ...done in {time.time() - t0:.0f}s （已累积 {len(all_out)} 条）")

    except KeyboardInterrupt:
        print("\n[!] 收到 Ctrl-C，正在保存已跑完的部分结果...")
    finally:
        (logdir_root / "ALL_RESULTS.json").write_text(
            json.dumps(all_out, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (logdir_root / "COST.json").write_text(
            json.dumps(cost_rows, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    n = len(all_out)
    print(f"\n{'=' * 60}")
    print(f"Done. {n} rows -> {logdir_root / 'ALL_RESULTS.json'}")
    print(f"成本明细 -> {logdir_root / 'COST.json'}")
    n_safe = sum(1 for r in all_out if r["safe_complete"])
    print(f"总样本 {n}，其中 safe_complete={n_safe}")


if __name__ == "__main__":
    app()
