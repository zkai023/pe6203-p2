"""读 ALL_RESULTS.json，算 TCR@k 和 HITL，然后把报告要用的图和表都生成出来。

    python src/analyze.py --input runs/final/ALL_RESULTS.json

跑完会得到：
    tcr_at_k.png      主图，三条策略对比
    hitl_table.md     HITL 表
    failure_cases.md  自动挑出来的代表性失败轨迹 
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import typer

app = typer.Typer()


def load_records(path: str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tcr_and_hitl(records: list[dict], policy: str, k: int):
    rows = [r for r in records if r["policy"] == policy and r["k"] == k]
    if not rows:
        return None
    n = len(rows)
    safe = [r for r in rows if r["safe_complete"]]
    tcr = len(safe) / n
    hitl = sum(r["hitl_used"] for r in safe) / len(safe) if safe else 0.0
    return {
        "policy": policy, "k": k, "n": n,
        "tcr": tcr, "hitl_avg": hitl,
        # 作业里写的是 "across the benchmark suite"，所以主口径是全部样本
        "hitl_total": sum(r["hitl_used"] for r in rows),
        # 顺便再算一个"只算成功任务"的，看可用性时更直观
        "hitl_total_on_safe": sum(r["hitl_used"] for r in safe),
        "n_safe": len(safe),
        "n_util_ok": sum(1 for r in rows if r["utility"]),
        "n_attacked": sum(1 for r in rows if r["security"]),
    }


@app.command()
def main(
    input: str = typer.Option("runs/final/ALL_RESULTS.json", "--input"),
    outdir: str = typer.Option("report_out"),
):
    if not Path(input).exists():
        raise typer.BadParameter(f"找不到结果文件: {input}")

    records = load_records(input)
    policies = sorted({r["policy"] for r in records})
    ks = sorted({r["k"] for r in records})
    Path(outdir).mkdir(parents=True, exist_ok=True)

    # ---------- 先把指标表算出来 ----------
    table = []
    for p in policies:
        for k in ks:
            r = tcr_and_hitl(records, p, k)
            if r:
                table.append(r)

    lines = ["## HITL Load / TCR@k 明细表", "",
             "| policy | k | 样本数 | TCR | 安全完成数 | HITL总量(全样本) | HITL总量(安全任务) | HITL均值(每安全任务) | 任务完成数 | 被攻击成功数 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in table:
        lines.append(
            f"| {r['policy']} | {r['k']} | {r['n']} | {r['tcr']:.3f} | {r['n_safe']} | "
            f"{r['hitl_total']} | {r['hitl_total_on_safe']} | {r['hitl_avg']:.2f} | "
            f"{r['n_util_ok']} | {r['n_attacked']} |"
        )
    Path(outdir, "hitl_table.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))

    # ---------- 文字类的产出先跑 ----------
    # 放在前面是因为它们不依赖 matplotlib，就算没装也不会被卡住
    _write_failure_cases(records, policies, Path(outdir, "failure_cases.md"))
    _write_cost_breakdown(records, policies, Path(outdir, "cost_breakdown.md"))
    _write_escalation_value(records, policies, Path(outdir, "escalation_value.md"))

    # ---------- 最后画图 ----------
    # 放最后是因为这里要 import matplotlib，缺了它会直接 return
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n[!] 未安装 matplotlib，跳过画图。其余报告文件已生成。 pip install matplotlib")
        return

    curves = defaultdict(list)
    for r in table:
        curves[r["policy"]].append((r["k"], r["tcr"]))

    plt.figure(figsize=(7.5, 5))
    markers = ["o", "s", "^", "D"]
    for i, p in enumerate(policies):
        pts = sorted(curves[p])
        xs = [x for x, _ in pts]
        ys = [y for _, y in pts]
        plt.plot(xs, ys, marker=markers[i % len(markers)], linewidth=2, label=p)
    plt.xlabel("Human attention budget k")
    plt.ylabel("TCR (Safe Task Completion Rate)")
    plt.title("TCR@k - Approval Policies vs Baselines")
    plt.ylim(-0.02, 1.02)
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    out = Path(outdir, "tcr_at_k.png")
    plt.savefig(out, dpi=200)
    plt.close()
    print(f"\n[OK] 主图已保存 -> {out}")


def _write_failure_cases(records, policies, out: Path):
    """自动挑两条典型的失败轨迹出来：
      A. 太保守，把正常调用也拦了，或者预算空耗导致任务没做成
      B. 太松，被攻击得手（utility 和 security 同时为真）
    """
    lines = [
        "# 代表性失败轨迹（报告需要）", "",
        "## A. 过度保守 Over-conservative",
        "策略把安全调用拦掉 / 或预算被浪费导致任务没完成。", "",
    ]

    conserv = [
        r for r in records
        if (not r["utility"]) and (r.get("n_denied", 0) > 0 or r.get("budget_exhausted_hits", 0) > 0)
    ]
    if not conserv:
        lines.append("_(暂无样本)_")
    for r in conserv[:2]:
        lines += [
            f"**policy={r['policy']} k={r['k']} task={r['user_task']}/{r['injection_task']}**",
            f"- denied={r.get('n_denied')}, budget_exhausted_hits={r.get('budget_exhausted_hits')}, "
            f"hitl_used={r['hitl_used']}, tool_calls={r.get('n_tool_calls')}",
            "```json",
            json.dumps(r["decisions"][:8], ensure_ascii=False, indent=2),
            "```", "",
        ]

    lines += [
        "## B. 过度放行 Over-permissive",
        "策略放行了不安全的调用，导致攻击成功（security=True）。", "",
    ]
    permissive = [r for r in records if r["utility"] and r["security"]]
    if not permissive:
        lines.append("_(暂无样本)_")
    for r in permissive[:2]:
        lines += [
            f"**policy={r['policy']} k={r['k']} task={r['user_task']}/{r['injection_task']}**",
            f"- hitl_used={r['hitl_used']}, denied={r.get('n_denied')}, tool_calls={r.get('n_tool_calls')}",
            "```json",
            json.dumps(r["decisions"][:8], ensure_ascii=False, indent=2),
            "```", "",
        ]

    lines += [
        "---",
        "写报告时别忘了：",
        "- 模拟审稿人只看得到工具调用和任务上下文，没碰过任何标准答案。",
        "- 两类里各留一条这样的具体轨迹。",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 失败案例 -> {out}")


# =====================================================================
# 成本分解：按策略拆成三块
#   policy inference  /  reviewer simulation  /  agent execution
# =====================================================================
def _write_cost_breakdown(records: list[dict], policies: list[str], out: Path):
    COMPONENTS = [
        ("agent execution", "agent_prompt_tokens", "agent_completion_tokens"),
        ("reviewer simulation", "reviewer_prompt_tokens", "reviewer_completion_tokens"),
        ("policy inference", "policy_prompt_tokens", "policy_completion_tokens"),
    ]

    try:
        from token_accounting import estimate_cost_usd
    except Exception:
        estimate_cost_usd = None

    lines = [
        "# Per-strategy API Cost Breakdown（交付物 4.2.3）", "",
        "按题目要求的三个组件拆分："
        "`policy inference` / `reviewer simulation` / `agent execution`。", "",
        "| policy | 组件 | 平均 prompt tokens | 平均 completion tokens | 平均总 tokens | 估算 $ / 次运行 |",
        "|---|---|---|---|---|---|",
    ]

    comp_rows = []  # (policy, 组件, 平均总tokens, usd)
    for p in policies:
        prows = [r for r in records if r["policy"] == p]
        if not prows:
            continue
        n = len(prows)
        sub_total = 0.0
        sub_usd = 0.0
        for comp, pk, ck in COMPONENTS:
            avg_p = sum(r.get(pk, 0) for r in prows) / n
            avg_c = sum(r.get(ck, 0) for r in prows) / n
            usd = estimate_cost_usd(avg_p, avg_c) if estimate_cost_usd else 0.0
            sub_total += avg_p + avg_c
            sub_usd += usd
            comp_rows.append((p, comp, avg_p + avg_c, usd))
            lines.append(
                f"| {p} | {comp} | {avg_p:.0f} | {avg_c:.0f} | {avg_p + avg_c:.0f} | {usd:.6f} |"
            )
        lines.append(
            f"| **{p}** | **合计** | - | - | **{sub_total:.0f}** | **{sub_usd:.6f}** |"
        )

    # ---- 装了这道门到底多花多少 ----
    lines += ["", "## 安全机制的边际开销", ""]
    # 这里有个坑：comp_rows 里每个 policy 有 3 条（三个组件），
    # 所以只能用 sum 求和，用 mean 会把两个 0 也算进分母，基线直接被稀释成三分之一。
    base_rows = [t for pol, _, t, _ in comp_rows if pol == "full_approve"]
    if base_rows:
        base_t = sum(base_rows)
        lines += [
            f"- 没装防护的 `full_approve` 平均 **{base_t:.0f} tokens / 次运行**。",
            "- 别的策略比它多出来的部分，就是装这道门的代价——"
            "答辩被问「这点安全提升值不值这个钱」时就拿这段答。",
            "",
            "| policy | 平均总 tokens | 相对基线增量 | 倍数 |", "|---|---|---|---|",
        ]
        for p in policies:
            tot = sum(t for pol, _, t, _ in comp_rows if pol == p)
            if p == "full_approve":
                lines.append(f"| {p} | {tot:.0f} | — | 1.00× |")
            elif base_t > 0:
                lines.append(f"| {p} | {tot:.0f} | +{tot - base_t:.0f} | {tot / base_t:.2f}× |")
            else:
                lines.append(f"| {p} | {tot:.0f} | — | — |")
    else:
        lines.append("_（本次结果中没有 `full_approve` 基线，无法计算增量）_")

    lines += [
        "",
        "---",
        "写报告时注意：",
        "- 钱是按 gpt-4o-mini 官方价（$0.15/1M input、$0.60/1M output）估的，"
        "走 OpenRouter 的话单价会有出入，报告里要写明。",
        "- `risk_tiered` 的策略推理是 0 token（纯规则），这是有意这么设计的："
        "把推理花销留给真正需要判断力的环节。",
        "- 要是 reviewer 那块花得比 agent 还多，说明「拿 LLM 顶人」本身就贵，"
        "正好呼应「人的注意力稀缺」这个出发点。",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 成本分解表 -> {out}")


# =====================================================================
# 升级价值分析：哪类调用值得叫人，哪类其实可以放心自动放行
# =====================================================================
def _write_escalation_value(records: list[dict], policies: list[str], out: Path):
    # 直接复用运行时那套分类器，保证这里统计的口径跟实际决策一致
    try:
        from policies import _looks_read_only, _looks_write
    except Exception:
        def _looks_read_only(fn): return fn.lower().startswith(("get_", "read_", "search_"))
        def _looks_write(fn): return False

    def kind_of(fn: str) -> str:
        if _looks_read_only(fn):
            return "read-only"
        if _looks_write(fn):
            return "write / side-effecting"
        return "ambiguous"

    # full_approve 从不 escalate，纳入统计没有意义
    esc_policies = [p for p in policies if p != "full_approve"] or list(policies)

    agg: dict[tuple[str, str], dict] = {}
    for r in records:
        if r["policy"] not in esc_policies:
            continue
        for d in r.get("decisions", []):
            a = agg.setdefault((r["policy"], d["tool"]), {
                "n": 0, "auto_approved": 0, "denied_direct": 0, "escalated": 0,
                "human_blocked": 0, "human_allowed": 0, "budget_exhausted": 0,
            })
            a["n"] += 1
            if d.get("escalated"):
                a["escalated"] += 1
                # 升级后仍被判 deny == 人工否决了这次调用 == 真正拦下了东西
                if d["final"] == "deny":
                    a["human_blocked"] += 1
                else:
                    a["human_allowed"] += 1
            elif d["final"] == "deny":
                a["denied_direct"] += 1
            else:
                a["auto_approved"] += 1
            if d.get("budget_exhausted"):
                a["budget_exhausted"] += 1

    lines = [
        "# Escalation-Value Analysis（交付物 4.2.6）", "",
        "核心指标 **Escalation Yield** = `human_blocked / escalated`："
        "升级到人工后，有多少比例被真人否决。", "",
        "- **高 Yield** → 这类调用危险且难以自动判定，**值得消耗稀缺预算**",
        "- **低 Yield** → 人工多半放行，属于**被浪费的注意力**，应改为自动放行", "",
    ]

    for p in esc_policies:
        rows = sorted(
            ((tool, a) for (pol, tool), a in agg.items() if pol == p),
            key=lambda x: -x[1]["escalated"],
        )
        if not rows:
            continue
        lines += [
            f"## policy = `{p}`", "",
            "| tool | 类型 | 调用次数 | 自动放行 | 自动拒绝 | 升级人工 | 人工否决 | Yield |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for tool, a in rows:
            y = a["human_blocked"] / a["escalated"] if a["escalated"] else 0.0
            lines.append(
                f"| `{tool}` | {kind_of(tool)} | {a['n']} | {a['auto_approved']} | "
                f"{a['denied_direct']} | {a['escalated']} | {a['human_blocked']} | **{y:.0%}** |"
            )

    lines += [
        "",
        "---",
        "对着上面的数字写报告：",
        "1. 值得叫人的：挑 Yield 最高的那几个工具，看它们的类型（基本都是写操作、不可逆的），"
        "说明这些正是预算该花的地方。",
        "2. 可以放心自动放行的：挑从没被人否过的（Yield ≈ 0），"
        "说明自动化放行它们不损失安全性，还能省下一大截预算。",
        "3. 预算耗尽最要命：被强制 deny 的次数对应 over-conservative failure，"
        "把预算从低 Yield 的工具挪给高 Yield 的就能缓解。",
        "4. 有句话得说清楚：这张表是按工具名归因的，而 utility/security 是任务级的，"
        "两者不能直接当因果关系用，这里给的是相关性证据。",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 升级价值分析 -> {out}")


if __name__ == "__main__":
    app()
