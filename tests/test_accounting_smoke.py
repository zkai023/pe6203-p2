"""离线的冒烟测试，验 token 计量和报告生成两块，不花一分钱。

为什么要单独测：
    1. MeteredOpenAI 是新写的，它要包住 AgentDojo 的 client 干活。
       它要是坏了，成本分解那块就彻底没了。
    2. 算"相对基线倍数"的时候手滑用过 mean，结果基线被两个 0 稀释成三分之一。
       这里专门拿一组能整除的数字把这类错误钉死。

    python tests/test_accounting_smoke.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

PASS, FAIL = [], []


def check(label, fn):
    try:
        fn()
        PASS.append(label)
        print(f"[OK]   {label}")
    except Exception as e:
        FAIL.append((label, f"{type(e).__name__}: {e}"))
        print(f"[FAIL] {label} -> {type(e).__name__}: {e}")


# ---------------- 假 response / 假 client ----------------
class FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c


class FakeResp:
    def __init__(self, p, c):
        self.usage = FakeUsage(p, c)


class FakeCompletions:
    def __init__(self):
        self.seen = []

    def create(self, **kw):
        self.seen.append(kw)
        return FakeResp(1000, 100)

    def bonus(self):
        return "bonus-ok"


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()

    def completions_alt(self):
        return "alt-ok"


class FakeOpenAIClient:
    def __init__(self):
        self.chat = FakeChat()
        self.marker = "real-client"


def _1_token_accumulate():
    from token_accounting import MeteredOpenAI

    meter = MeteredOpenAI(client=FakeOpenAIClient())
    for _ in range(3):
        meter.chat.completions.create(model="x", messages=[], tools=None)
    s = meter.counter.summary()
    assert s["calls"] == 3, s
    assert s["prompt_tokens"] == 3000, s
    assert s["completion_tokens"] == 300, s
    assert s["total_tokens"] == 3300, s


def _2_reset_works():
    from token_accounting import MeteredOpenAI

    meter = MeteredOpenAI(client=FakeOpenAIClient())
    meter.chat.completions.create(model="x")
    meter.counter.reset()
    s = meter.counter.summary()
    assert s["calls"] == 0 and s["total_tokens"] == 0, s


def _3_transparent_forwarding():
    """包装不能吞掉真实 client 的其他属性，否则 AgentDojo 可能取不到东西。"""
    from token_accounting import MeteredOpenAI

    real = FakeOpenAIClient()
    meter = MeteredOpenAI(client=real)
    assert meter.marker == "real-client", "未转发真实 client 属性"
    assert meter.chat.completions.bonus() == "bonus-ok", "未转发 completions 方法"
    assert meter.chat.completions_alt() == "alt-ok", "未转发 chat 方法"


def _4_usage_missing_is_safe():
    """usage 为 None 时不能崩（某些网关不返回 usage）。"""
    from token_accounting import MeteredOpenAI, TokenCounter

    class NoUsageClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    class R:
                        usage = None
                    return R()

    meter = MeteredOpenAI(client=NoUsageClient())
    meter.chat.completions.create(model="x")
    assert meter.counter.calls == 1
    assert meter.counter.total_tokens == 0

    c = TokenCounter()
    c.record(None)
    assert c.calls == 1 and c.total_tokens == 0


def _5_cost_formula():
    from token_accounting import estimate_cost_usd

    # 1M input @0.15 + 1M output @0.60 = 0.75
    got = estimate_cost_usd(1_000_000, 1_000_000)
    assert abs(got - 0.75) < 1e-9, got
    assert abs(estimate_cost_usd(0, 0)) < 1e-12


def _6_build_pipeline_returns_counter():
    """build_pipeline 必须返回 4 元组，第 4 项是 counter，且内部真的用了 MeteredOpenAI。"""
    import inspect

    import build_pipeline

    src = inspect.getsource(build_pipeline.build_pipeline)
    assert "agent_counter" in src, "build_pipeline 未返回 counter"
    assert "MeteredOpenAI" in src, "build_pipeline 未接入计量"
    assert "OpenAILLM(openai" not in src, "还在使用未计量的裸 client"


def _7_cost_breakdown_baseline_math():
    """钉死 '相对基线倍数'：曾经误用 mean 导致基线被算成 1/3。"""
    import analyze

    rows = []
    for pol, p_tok in (("full_approve", 3000), ("full_escalate", 4500)):
        for _ in range(4):
            rows.append({
                "policy": pol, "k": 1,
                "agent_prompt_tokens": p_tok, "agent_completion_tokens": 0,
                "reviewer_prompt_tokens": 0, "reviewer_completion_tokens": 0,
                "policy_prompt_tokens": 0, "policy_completion_tokens": 0,
                "utility": True, "security": False, "safe_complete": True,
                "hitl_used": 0, "decisions": [],
            })

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "cost.md"
        analyze._write_cost_breakdown(rows, ["full_approve", "full_escalate"], out)
        text = out.read_text(encoding="utf-8")
    assert "3000 tokens / 次运行" in text, f"基线数字不对:\n{text}"
    assert "1.50×" in text, f"倍数不对（应为 4500/3000=1.50）:\n{text}"


def _8_escalation_yield_math():
    """验证 Yield = human_blocked / escalated，且 write 工具被正确分类。"""
    import analyze

    rows = [{
        "policy": "risk_tiered", "k": 2,
        "decisions": [
            # update_password: escalate x2, 其中 1 次被人工否决 -> 50%
            {"tool": "update_password", "escalated": True, "final": "deny", "budget_exhausted": False},
            {"tool": "update_password", "escalated": True, "final": "approve", "budget_exhausted": False},
            # read_file: 自动放行 -> 不进 escalate 统计
            {"tool": "read_file", "escalated": False, "final": "approve", "budget_exhausted": False},
        ],
    }]

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "esc.md"
        analyze._write_escalation_value(rows, ["risk_tiered"], out)
        text = out.read_text(encoding="utf-8")
    assert "**50%**" in text, f"Yield 计算不对:\n{text}"
    assert "write / side-effecting" in text, "写操作分类失败"
    assert "read-only" in text, "只读分类失败"


def _9_analyze_end_to_end():
    """用合成数据实跑一次 analyze.py，确认 5 份交付物全部产出且不为空。"""
    synth = ROOT / "runs" / "synthetic" / "ALL_RESULTS.json"
    gen = ROOT / "tests" / "make_synthetic_results.py"
    with tempfile.TemporaryDirectory() as td:
        # 先生成合成数据到临时目录
        target = Path(td) / "ALL_RESULTS.json"
        r = subprocess.run(
            [sys.executable, str(gen), str(target)],
            capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        outdir = Path(td) / "out"
        r = subprocess.run(
            [sys.executable, str(ROOT / "src" / "analyze.py"),
             "--input", str(target), "--outdir", str(outdir)],
            capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr or r.stdout

        expected = {
            "tcr_at_k.png": "交付物 4.2.1 TCR@k 曲线",
            "hitl_table.md": "交付物 4.2.2 HITL Load 表",
            "cost_breakdown.md": "交付物 4.2.3 成本分解",
            "failure_cases.md": "交付物 4.2.4/4.2.5 失败分类与轨迹",
            "escalation_value.md": "交付物 4.2.6 升级价值分析",
        }
        for fname, desc in expected.items():
            f = outdir / fname
            assert f.exists(), f"缺少产出: {fname} ({desc})"
            if fname.endswith(".md"):
                body = f.read_text(encoding="utf-8").strip()
                assert len(body) > 80, f"{fname} 内容过短，可能异常"
            else:
                assert f.stat().st_size > 1000, f"{fname} 图片过小"
        print(f"       └─ 5 份交付物产出齐全")


print("=" * 70)
print("PE6203 P2 离线冒烟测试（token 计量 + 报告产出）")
print("=" * 70)
for label, fn in [
    ("token 累加正确", _1_token_accumulate),
    ("reset 生效", _2_reset_works),
    ("包装透明转发（不吞属性）", _3_transparent_forwarding),
    ("usage 缺失时不崩", _4_usage_missing_is_safe),
    ("成本换算公式", _5_cost_formula),
    ("build_pipeline 返回 counter", _6_build_pipeline_returns_counter),
    ("成本基线倍数算法已钉死", _7_cost_breakdown_baseline_math),
    ("Escalation Yield 算法", _8_escalation_yield_math),
    ("analyze 端到端产出 5 份交付物", _9_analyze_end_to_end),
]:
    check(label, fn)

print()
print("=" * 70)
print(f"通过 {len(PASS)} / 失败 {len(FAIL)}")
for f, e in FAIL:
    print(f"  [FAIL] {f} -> {e}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
