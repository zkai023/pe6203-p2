# PE6203 Group Project 2 — Safety Approval Policies for Agent Harnesses

NTU PE6203（Instructor: Bo An, CCDS）的小组项目。

简单说就是一件事：AI 智能体要去调工具干活，哪些该让它直接做、哪些得先问人、
哪些干脆别做。我们把这件事做成一个可替换的模块，塞进 AgentDojo 里跑了一遍，
看看不同的"叫人策略"到底差多少。

---

## 结果先摆这儿（360 次真实运行）

| | full_approve | full_escalate | risk_tiered（我们提的） |
|---|---|---|---|
| 被打穿的比例 | 54%–67% | 0% | 0% |
| k=4 时的 TCR | 29.2% | 37.5% | **45.8%** |
| k=8 时叫人的总次数 | 0 | 98 | **47** |

TCR 就是"任务做成了、同时没被打穿"的比例。k 是每个任务最多能打扰人几次。

三条比较实在的结论：

- **一样安全，人力减半**。k=8 时 risk_tiered 和 full_escalate 的 TCR 都是 37.5%，
  但 risk_tiered 只叫了 47 次人，full_escalate 叫了 98 次。
  k=4 时 risk_tiered 更狠：TCR 更高（45.8% vs 37.5%），叫人还更少（41 vs 80）。
- **完全不许叫人，分级也还是有用**。k=0 时 risk_tiered 拿到 41.7%，
  full_escalate 只有 25%——后者连读个文件都要拦，直接把自己卡死了。
- **叫人这件事，值不值看对象**。risk_tiered 每一次叫人，有 85% 以上会被否掉；
  full_escalate 那边 248 次叫人里有 149 次（60%）是"问了也白问"，
  光是只读工具就白问了 144 次（读文件那类一次都没被否过）。

怎么跑的：AgentDojo v1.2.2 的 banking suite，用 `important_instructions` 注入攻击，
模型 `openai/gpt-4o-mini-2024-07-18`（走的 OpenRouter）。
8 个 user task × 3 个 injection × k 取 {0,1,2,4,8} × 3 个策略 = 360 次，差不多 45 分钟，一两块美金。

图和表都在 `report_out/` 下面，完整报告看 **`REPORT.md`**（含摘要、方法、9 个章节与复现说明）。

---

## 怎么做的

官方 AgentDojo 的 tool 执行这块是这样：

```
AgentPipeline([SystemMessage, InitQuery, llm,
               ToolsExecutionLoop([ToolsExecutor(), llm])])
```

我们只把 `ToolsExecutor` 换成自己写的 `ApprovalGate`，位置一点没动：

```
AgentPipeline([SystemMessage, InitQuery, llm,
               ToolsExecutionLoop([ApprovalGate(policy, reviewer, k), llm])])
```

`ApprovalGate` 对每次工具调用三选一：

| 决策 | 干什么 |
|---|---|
| `approve` | 真跑，`runtime.run_function(env, fn, args)` |
| `escalate` | 还有预算就问审稿人，照它的裁决办；预算没了就只能拒 |
| `deny` | 不跑，回一条"被拒了"的消息给模型 |

被拒的时候我们是回一条消息，不是抛异常。这样模型知道自己被拒了，还能换个办法继续做，
不会直接卡死或者反复重试。

**策略这块我们提的是 `risk_tiered`**：看工具名就知道该不该问人。
读操作直接放行，写操作（转账、删除这种）叫人，拿不准的一律叫人。
纯规则，一个 token 都不花。

另外有一条线不能碰：模拟审稿人只能看到真人审批时也看得到的东西
（工具名、参数、对话历史、任务描述），标准答案和攻击标注一律不给它看。
给它看答案就等于作弊，安全率就成了刷出来的。

---

## 踩过的坑，先看能省不少事

1. **模型停服了**。`gpt-4o-2024-05-13`、`gpt-4-turbo`、`gpt-3.5-turbo` 在 2026-10-23 停服，
   Claude 3.x 更早，2026-02-19 就退役了。统一用 `gpt-4o-mini-2024-07-18`。
   还有个容易混的：CLI 那边写的是大写枚举名 `GPT_4O_MINI_2024_07_18`，
   Python API 里是 dashed 字符串，两个长不一样。

2. **`security=True` 是"被打穿了"，不是"安全"**。
   安全完成是 `utility=True AND security=False`。搞反的话 TCR 全是错的。

3. **`get_suites()` 要传版本字符串**，比如 `"v1.2.2"`。
   里面 `_SUITES` 是个 defaultdict，传 None 会静默返回一个空 dict，
   症状是"自检说没问题，但 suites 是空的"，然后报 `suite='banking' 不存在`。
   排查过一次，挺费时间。

4. **`ATTACKS` 不在顶层**。`from agentdojo.attacks import ATTACKS` 会 ImportError，
   得写 `from agentdojo.attacks.attack_registry import ATTACKS`。
   `load_attack` 倒是顶层就有，很容易搞混。

---

## API Key 怎么配

靠环境变量 `OPENAI_BASE_URL` 决定请求发哪儿（openai SDK 的 `_client.py` 会读它）。
两种配法：

**OpenAI 官方 Key**（`sk-` / `sk-proj-` 开头）

```ini
OPENAI_API_KEY=sk-...
AGENTDOJO_MODEL=gpt-4o-mini-2024-07-18
```

**OpenRouter Key**（`sk-or-v1-` 开头）

```ini
OPENAI_API_KEY=sk-or-v1-...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
AGENTDOJO_MODEL=openai/gpt-4o-mini-2024-07-18
```

报错 `401 Incorrect API key provided: sk-or-v1****` 但请求打的是 `api.openai.com`——
Key 没问题，是网关没指过去，加上 `OPENAI_BASE_URL` 就好。

还有一点：官方的 CLI（`python -m agentdojo.scripts.benchmark`）在 OpenRouter 下用不了，
它会把模型映射成不带厂商前缀的 id，OpenRouter 上找不到。用我们自己的
`src/run_experiments.py` 就行，效果一样。

不知道自己手上的是哪种 Key，跑 `python scripts/check_key.py`，它会探测一遍并告诉你该填什么。

---

## 用 PyCharm 跑（不用开终端也行）

打开项目的时候**直接开 `pe6203-p2` 这一层**，不然路径会错位。

1. File → Open → 选到 `pe6203-p2`
2. 建虚拟环境：Settings → Project → Python Interpreter → 齿轮 → Add Local Interpreter →
   Virtualenv Environment → New（Python 选 ≥3.11）
3. 装依赖：底部 Python Packages 搜 `agentdojo`；或者开 Terminal（`Alt+F12`）跑
   `pip install -r requirements.txt`
4. 配 Key：推荐加到 Windows 系统环境变量里（改完要重启 PyCharm 才生效），
   别写进代码里
5. 直接点右上角下拉框选预置好的 Run Configuration：

| 名字 | 干什么 | 花钱吗 |
|---|---|---|
| `0-检查API Key` | 判断 Key 类型、探测端点、告诉你 .env 该填啥 | 几乎不花 |
| `1-自检 selfcheck` | 排掉停服模型、import 失效、suite 为空这些坑 | 0 |
| `2-官方CLI冒烟` | 只有 OpenAI 官方 Key 能用 | 极少 |
| `2b-自研pipeline冒烟` | OpenRouter 用这条，跑 1 次验证链路 | 约 $0.01 |
| `3-小规模跑通三策略` | 72 次运行，跑通全链路 | 小 |
| `4-正式评测` | 正式出 TCR@k 曲线 | 中 |
| `4b-极限全量` | 144 组合全跑，非必要别点 | 大 |
| `5-出图出表 analyze` | 生成图和表 | 0 |

---

## 命令行版

```bash
python -m venv .venv
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

export OPENAI_API_KEY="sk-..."

# 先跑这个，不花钱，顺便会告诉你规模有多大
python scripts/selfcheck.py --deep

# 调试用，省钱：3 × 2 × 4 个 k × 3 策略 = 72 次
python src/run_experiments.py --suite-name banking --limit-tasks 3 --limit-injections 2 --k-values 0,1,2,3

# 正式跑（出这份 README 里的数据用的就是它）
python src/run_experiments.py --suite-name banking --limit-tasks 8 --limit-injections 3 \
       --k-values 0,1,2,4,8 --policies full_approve,full_escalate,risk_tiered --logdir runs/final

python src/analyze.py --input runs/final/ALL_RESULTS.json
```

banking 全量是 16 个 user task × 9 个 injection = 144 个组合，
再乘策略数和 k 的取值数。全跑一次（3 策略 × 7 个 k）是 3024 次，又贵又慢，
务必先用 `--limit-tasks` / `--limit-injections` 试。
（注意参数名是 `--limit-injections`，传 0 表示不限制。）

---

## 代码都在哪

```
src/policies.py          三个策略：full_approve / full_escalate / risk_tiered
src/approval_gate.py     审批门，顶掉官方 ToolsExecutor 的那个
src/reviewer.py          模拟人工审稿人（不给它看标准答案）
src/token_accounting.py  记 token 用的（官方把 usage 扔了，只能自己来）
src/build_pipeline.py    组装 pipeline，唯一改动就是把 ToolsExecutor 换成 ApprovalGate
src/run_experiments.py   跑实验的主脚本
src/analyze.py           算 TCR@k / HITL，出图和表
scripts/selfcheck.py     离线自检
scripts/check_key.py     Key 和网关体检
tests/                   离线测试，不花钱
```

`analyze.py` 跑完会生成：

- `tcr_at_k.png` — TCR@k 曲线
- `hitl_table.md` — HITL 表
- `cost_breakdown.md` — 成本拆成策略推理 / 审稿人 / agent 执行三块
- `failure_cases.md` — 两类失败，每类带具体轨迹
- `escalation_value.md` — 哪类调用叫人最值

---

## 不花钱也能验

```bash
python tests/test_policies_smoke.py      # 策略逻辑，11 项
python tests/test_accounting_smoke.py    # token 计量 + 报告产出，9 项
```

---

## 说清楚哪些地方还不够

- 分级靠工具名猜，本基准里工具名是平台定的、攻击者改不了，所以评测范围内没问题；
  换到开放工具集就可能被绕过去。更稳的做法是读工具的类型签名，
  代码里留了个 `ConstraintAwarePolicy` 的接口没写完。
- 规模是控制过的（双向限流），所以结论按趋势讲，不硬吹具体百分点。
- 审稿人是 LLM 不是真人，没考虑人会疲劳、会习惯性点同意。
- 只用了一个攻击家族、一个 suite。
