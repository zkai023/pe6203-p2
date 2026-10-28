"""自检脚本，不花一分钱。

主要帮你避开两个坑：
  1) 模型已经下线（gpt-4o / gpt-4-turbo / gpt-3.5 在 2026-10-23 停服了，白跑半天才发现）
  2) 依赖、导入路径跟你装的 agentdojo 版本对不上

    python scripts/selfcheck.py
    python scripts/selfcheck.py --deep   # 会顺带加载 suite，需要包是完整的
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# 跟其他脚本一样也读 .env，不然明明配好了却报"Key 没设置"，白紧张一场
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 兼容不同的调用位置：优先用调用者 cwd 下的 .env，否则退到项目根的 .env
_env_path = Path(".env")
if not _env_path.exists():
    _env_path = _PROJECT_ROOT / ".env"
try:
    from dotenv import load_dotenv

    load_dotenv(_env_path, override=True)
except ImportError:
    pass

OK, BAD, WARN = "[OK]", "[!!]", "[?]"
results: list[tuple[str, str, str]] = []


def check(label: str, fn) -> None:
    try:
        status, msg = fn()
    except Exception as e:  # 任何异常都不能让自检崩掉
        status, msg = BAD, f"{type(e).__name__}: {e}"
    results.append((status, label, msg))


# ---------------- 1. Python 版本 ----------------
def py_version():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return (OK if ok else BAD), f"{v.major}.{v.minor}.{v.micro}"


# ---------------- 2. agentdojo 已安装且版本 ----------------
def agentdojo_installed():
    import agentdojo
    ver = getattr(agentdojo, "__version__", "unknown")
    return OK, f"agentdojo {ver}"


# ---------------- 3. 核心 import 路径是否仍然有效 ----------------
IMPORTS = [
    ("agentdojo.agent_pipeline.base_pipeline_element", "BasePipelineElement"),
    ("agentdojo.agent_pipeline.tool_execution", "tool_result_to_str"),
    ("agentdojo.agent_pipeline.tool_execution", "ToolsExecutor"),
    ("agentdojo.agent_pipeline", "ToolsExecutionLoop"),
    ("agentdojo.agent_pipeline", "AgentPipeline"),
    ("agentdojo.agent_pipeline", "SystemMessage"),
    ("agentdojo.agent_pipeline", "InitQuery"),
    ("agentdojo.agent_pipeline.llms.openai_llm", "OpenAILLM"),
    ("agentdojo.functions_runtime", "FunctionsRuntime"),
    ("agentdojo.types", "ChatToolResultMessage"),
    ("agentdojo.types", "text_content_block_from_string"),
    ("agentdojo.attacks.attack_registry", "load_attack"),
    # ATTACKS 藏在 attack_registry 子模块里，从 agentdojo.attacks 顶层 import 会失败
    ("agentdojo.attacks.attack_registry", "ATTACKS"),
    ("agentdojo.task_suite.load_suites", "get_suites"),
    ("agentdojo.task_suite.load_suites", "get_suite"),
    ("agentdojo.benchmark", "run_task_with_injection_tasks"),
]


def check_imports():
    missing = []
    for mod, attr in IMPORTS:
        try:
            m = importlib.import_module(mod)
            if not hasattr(m, attr):
                missing.append(f"{mod}.{attr}")
        except Exception as e:
            missing.append(f"{mod} ({type(e).__name__})")
    if missing:
        return BAD, "缺失: " + ", ".join(missing[:6])
    return OK, f"{len(IMPORTS)} 个关键符号全部可导入"


# ---------------- 4. 模型还能不能用 ----------------
# 这几个已经停服了，用了才发现就白跑一轮
DEAD_MODELS = {
    "gpt-4o-2024-05-13": "2026-10-23 停服",
    "gpt-4-turbo-2024-04-09": "2026-10-23 停服",
    "gpt-3.5-turbo-0125": "2026-10-23 停服",
    "gpt-4-0125-preview": "2026-03-26 停服",
}
RECOMMENDED = "gpt-4o-mini-2024-07-18"


def model_availability():
    """列出本版本支持的模型，并标出哪些已下线。"""
    try:
        from agentdojo.models import MODEL_NAMES  # type: ignore
    except Exception:
        try:
            from agentdojo.models import MODEL_PROVIDERS  # type: ignore
            MODEL_NAMES = list(MODEL_PROVIDERS)
        except Exception as e:
            return WARN, f"未能自动读取模型清单({e})，请手动跑 CLI --help"

    names = list(MODEL_NAMES)
    dead = [m for m in names if m in DEAD_MODELS or any(d in m for d in DEAD_MODELS)]
    alive_ok = RECOMMENDED in names or any("4o-mini" in m for m in names)

    if not alive_ok:
        return BAD, f"推荐模型 {RECOMMENDED} 不在清单里！可用前 8 个: {names[:8]}"
    msg = f"共 {len(names)} 个模型；推荐模型可用；检测到已下线条目 {len(dead)} 个"
    if dead:
        msg += f" -> {dead[:3]}"
    return OK, msg


# ---------------- 5. API Key 是否设置 ----------------
def api_key():
    k = os.environ.get("OPENAI_API_KEY", "")
    if not k:
        return BAD, "OPENAI_API_KEY 未设置（跑实验前必须设置，且不要提交进 git）"
    return OK, f"已设置 (长度 {len(k)}, 尾部 ...{k[-4:]})"


# ---------------- 6. 本地项目模块能否导入 ----------------
def local_modules():
    src = Path(__file__).resolve().parent.parent / "src"
    if not src.exists():
        return BAD, f"未找到 src 目录: {src}"
    sys.path.insert(0, str(src))
    try:
        import policies  # noqa
        from reviewer import LLMSimulatedReviewer  # noqa
        from approval_gate import ApprovalGate  # noqa
        from policies import FullApprovePolicy, FullEscalatePolicy, RiskTieredPolicy  # noqa
    except Exception as e:
        return BAD, f"本地模块导入失败: {type(e).__name__}: {e}"
    # 策略是否返回合法的三选一
    p = RiskTieredPolicy()
    class _TC:
        function = "get_balance"
        args = {}
        id = "1"
    d = p.decide(tool_call=_TC(), messages=[], runtime=None, env=None, task_goal="t")
    if d not in ("approve", "deny", "escalate"):
        return BAD, f"策略返回非法值: {d}"
    return OK, f"policies/reviewer/approval_gate 均可导入；只读工具决策={d}"


# get_suites 要传版本字符串（"v1.2.2"），不能传 None。
# 里面 _SUITES 是个 defaultdict，传 None 会静默返回一个空 dict，
# 症状是"别的检查都过，但 suites 是空的"，特别不好查。
BENCHMARK_VERSION = "v1.2.2"


def suites_load():
    try:
        from agentdojo.task_suite.load_suites import get_suites
        s = get_suites(BENCHMARK_VERSION)
    except Exception as e:
        return BAD, f"suite 加载失败: {type(e).__name__}: {e}"
    if not s:
        return BAD, f"suites 为空！多半是 get_suites() 传了 None 或版本号写错（应为 {BENCHMARK_VERSION}）"
    detail = ", ".join(f"{k}({len(v.user_tasks)}ut)" for k, v in s.items())
    return OK, f"版本 {BENCHMARK_VERSION}；suites: {list(s)}；详细 {detail}"


# ---------------- 8. (可选) attack 名单 ----------------
def attack_names():
    try:
        from agentdojo.attacks.attack_registry import ATTACKS
    except Exception as e:
        return BAD, f"{type(e).__name__}: {e}（注意 ATTACKS 在 agentdojo.attacks.attack_registry，不在顶层）"
    return OK, f"共 {len(ATTACKS)} 个: {list(ATTACKS)}"


# ---------------- 9. (可选) 跑批规模提醒 ----------------
def scale_estimate():
    try:
        from agentdojo.task_suite.load_suites import get_suite
        b = get_suite(BENCHMARK_VERSION, "banking")
    except Exception as e:
        return WARN, f"无法估算: {type(e).__name__}: {e}"
    n = len(b.user_tasks) * len(b.injection_tasks)
    return WARN, (
        f"banking 全量 = {len(b.user_tasks)} user × {len(b.injection_tasks)} injection = {n} 组合/策略；"
        f"× policies × k 才是总运行数，务必先用 --limit-tasks / --limit-injections 试跑"
    )


def main(deep: bool = False):
    check("Python >= 3.11", py_version)
    check("agentdojo 已安装", agentdojo_installed)
    check("关键 import 路径", check_imports)
    check("模型可用性(停服陷阱)", model_availability)
    check("OPENAI_API_KEY", api_key)
    check("本地项目模块", local_modules)
    if deep:
        check("suite 加载", suites_load)
        check("attack 名单", attack_names)
        check("跑批规模提醒", scale_estimate)

    width = max(len(l) for _, l, _ in results) + 2
    print("\n" + "=" * 70)
    print("PE6203 P2 环境自检")
    print("=" * 70)
    for status, label, msg in results:
        print(f"{status} {label:<{width}} {msg}")
    print("=" * 70)

    n_bad = sum(1 for s, _, _ in results if s == BAD)
    if n_bad:
        print(f"\n{n_bad} 项未通过，请先修复上面标 [!!] 的条目。")
        print("提示: pip install agentdojo && export OPENAI_API_KEY=...")
        sys.exit(1)
    print("\n全部通过 —— 可以开始跑实验了。")


if __name__ == "__main__":
    deep = "--deep" in sys.argv
    main(deep=deep)
