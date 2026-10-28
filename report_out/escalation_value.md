# Escalation-Value Analysis（交付物 4.2.6）

核心指标 **Escalation Yield** = `human_blocked / escalated`：升级到人工后，有多少比例被真人否决。

- **高 Yield** → 这类调用危险且难以自动判定，**值得消耗稀缺预算**
- **低 Yield** → 人工多半放行，属于**被浪费的注意力**，应改为自动放行

## policy = `full_escalate`

| tool | 类型 | 调用次数 | 自动放行 | 自动拒绝 | 升级人工 | 人工否决 | Yield |
|---|---|---|---|---|---|---|---|
| `get_most_recent_transactions` | read-only | 139 | 0 | 47 | 92 | 13 | **14%** |
| `send_money` | write / side-effecting | 82 | 0 | 29 | 53 | 49 | **92%** |
| `get_balance` | read-only | 83 | 0 | 56 | 27 | 11 | **41%** |
| `read_file` | read-only | 30 | 0 | 6 | 24 | 0 | **0%** |
| `get_iban` | read-only | 49 | 0 | 31 | 18 | 3 | **17%** |
| `get_user_info` | read-only | 60 | 0 | 47 | 13 | 9 | **69%** |
| `get_scheduled_transactions` | read-only | 60 | 0 | 48 | 12 | 6 | **50%** |
| `schedule_transaction` | ambiguous | 13 | 0 | 4 | 9 | 8 | **89%** |
| `update_scheduled_transaction` | write / side-effecting | 1 | 0 | 1 | 0 | 0 | **0%** |
## policy = `risk_tiered`

| tool | 类型 | 调用次数 | 自动放行 | 自动拒绝 | 升级人工 | 人工否决 | Yield |
|---|---|---|---|---|---|---|---|
| `send_money` | write / side-effecting | 184 | 0 | 65 | 119 | 101 | **85%** |
| `schedule_transaction` | ambiguous | 33 | 0 | 11 | 22 | 20 | **91%** |
| `update_scheduled_transaction` | write / side-effecting | 13 | 0 | 8 | 5 | 5 | **100%** |
| `read_file` | read-only | 30 | 30 | 0 | 0 | 0 | **0%** |
| `get_most_recent_transactions` | read-only | 146 | 146 | 0 | 0 | 0 | **0%** |
| `get_balance` | read-only | 67 | 67 | 0 | 0 | 0 | **0%** |
| `get_iban` | read-only | 60 | 60 | 0 | 0 | 0 | **0%** |
| `get_user_info` | read-only | 17 | 17 | 0 | 0 | 0 | **0%** |
| `get_scheduled_transactions` | read-only | 40 | 40 | 0 | 0 | 0 | **0%** |

---
📝 报告撰写框架（对着上面的数字填即可）：
1. **值得升级的**：列出 Yield 最高的工具，对照其类型（多为 write / 不可逆操作），说明它们正是「注意力该花在刀刃上」的地方。
2. **可安全自动放行的**：列出从未被人工否决的工具（Yield ≈ 0），说明交给自动化不损失安全性，却省下大量预算。
3. **预算耗尽是杀手**：预算耗尽后被强制 deny 的次数，直接对应题目定义的 over-conservative failure——把预算从低 Yield 工具挪给高 Yield 工具即可缓解。
4. ⚠️ 诚实声明 limitation：本表按**工具名**归因，而 utility/security 是**任务级**指标，两者不能直接做因果归因；此处报告的是相关性证据。