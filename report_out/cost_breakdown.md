# Per-strategy API Cost Breakdown（交付物 4.2.3）

按题目要求的三个组件拆分：`policy inference` / `reviewer simulation` / `agent execution`。

| policy | 组件 | 平均 prompt tokens | 平均 completion tokens | 平均总 tokens | 估算 $ / 次运行 |
|---|---|---|---|---|---|
| full_approve | agent execution | 5133 | 168 | 5301 | 0.000871 |
| full_approve | reviewer simulation | 0 | 0 | 0 | 0.000000 |
| full_approve | policy inference | 0 | 0 | 0 | 0.000000 |
| **full_approve** | **合计** | - | - | **5301** | **0.000871** |
| full_escalate | agent execution | 5389 | 169 | 5558 | 0.000910 |
| full_escalate | reviewer simulation | 1211 | 50 | 1261 | 0.000212 |
| full_escalate | policy inference | 0 | 0 | 0 | 0.000000 |
| **full_escalate** | **合计** | - | - | **6818** | **0.001121** |
| risk_tiered | agent execution | 7137 | 218 | 7354 | 0.001201 |
| risk_tiered | reviewer simulation | 822 | 29 | 851 | 0.000141 |
| risk_tiered | policy inference | 0 | 0 | 0 | 0.000000 |
| **risk_tiered** | **合计** | - | - | **8206** | **0.001342** |

## 安全机制的边际开销

- 无防护基线 `full_approve` 平均 **5301 tokens / 次运行**。
- 其余策略相对它的增量，就是**上这道审批门的代价**——答辩时用来回答「is the safety gain worth the cost?」。

| policy | 平均总 tokens | 相对基线增量 | 倍数 |
|---|---|---|---|
| full_approve | 5301 | — | 1.00× |
| full_escalate | 6818 | +1517 | 1.29× |
| risk_tiered | 8206 | +2904 | 1.55× |

---
📝 报告撰写要点：
- 美元估算按 gpt-4o-mini 官方定价（$0.15/1M input, $0.60/1M output）下限估算；若经 OpenRouter 计费，实际单价可能不同，报告中需如实声明。
- 本项目 `risk_tiered` 的 **policy inference = 0 tokens**（rule-based），这是刻意的设计取舍：把预算留给真正需要判断的地方（reviewer simulation）。
- 若 reviewer simulation 开销显著高于 agent execution，说明「用 LLM 模拟人」本身很贵——这正呼应题目背景中「人类注意力稀缺」的动机，可写进 Insight 章节。