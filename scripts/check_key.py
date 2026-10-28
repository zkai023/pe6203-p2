"""Key 体检：看看你的 Key 到底该走哪条路。基本不花钱，只发一个最小请求。

为什么要有这个脚本：当时一直报
    401 Incorrect API key provided: sk-or-v1****3994
可请求明明是打向 https://api.openai.com/v1 的。
`sk-or-v1-` 是 OpenRouter 的前缀，OpenAI 官方端点不认它。
Key 没毛病，是网关走错了。

能改过来是因为 openai SDK 的 _client.py 里有这么一句：
    base_url = os.environ.get("OPENAI_BASE_URL")
设了这个变量，openai.OpenAI() 就会打到你要的网关。

脚本按顺序做这几件事：
    1. 读 key，按前缀猜是哪家
    2. 挨个探测 OpenAI 和 OpenRouter
    3. 列一下上面有哪些 gpt-4o-mini 系列的模型 id
    4. 发一个极小的请求，确认余额还能用
    5. 把你应该写进 .env 的内容直接打出来

    python scripts/check_key.py
"""
from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv
    # override=True: 让 .env 覆盖系统里可能残留的旧变量
    load_dotenv(".env", override=True)
except Exception:
    pass

KEY = os.environ.get("OPENAI_API_KEY", "").strip()
CURRENT_BASE = os.environ.get("OPENAI_BASE_URL", "(未设置 -> 默认 api.openai.com)")

CANDIDATES = [
    ("🅰 OpenAI 官方", "https://api.openai.com/v1"),
    ("🅾 OpenRouter", "https://openrouter.ai/api/v1"),
]

print("=" * 72)
print("API Key 体检")
print("=" * 72)
print(f"OPENAI_API_KEY    = {KEY[:8]}...{KEY[-4:]}" if KEY else "OPENAI_API_KEY    = (未设置)")
print(f"OPENAI_BASE_URL   = {CURRENT_BASE}")
print(f"当前进程认为的发往  = {os.environ.get('OPENAI_BASE_URL') or 'https://api.openai.com/v1'}")
print()

# ---------- 1. 按前缀猜服务商 ----------
if not KEY:
    print("[!!] 没有 Key。请先在项目根目录建 .env 并写入 OPENAI_API_KEY=...")
    sys.exit(1)

guess = "未知"
if KEY.startswith("sk-or-v1-"):
    guess = "OpenRouter（注意，这个不能直接打 OpenAI 官方端点）"
elif KEY.startswith("sk-proj-"):
    guess = "OpenAI 官方（项目 Key）"
elif KEY.startswith("sk-ant-"):
    guess = "Anthropic（本项目不支持，agentdojo 走 OpenAI 协议）"
elif KEY.startswith("sk-"):
    guess = "可能是 OpenAI 官方（旧式 Key）"
print(f"Key 前缀服务商判断: {guess}")
print("=" * 72)

try:
    from openai import OpenAI
except Exception as e:
    print(f"[!!] 缺少 openai 包: {e}")
    sys.exit(1)


def probe(label: str, base_url: str) -> tuple[bool, list[str], str]:
    """返回 (是否可用, 匹配的模型id列表, 说明)。"""
    try:
        client = OpenAI(api_key=KEY, base_url=base_url, timeout=30.0)
        models = client.models.list()
        ids = sorted(m.id for m in models.data)
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:160]}"
        return False, [], msg

    hits = [i for i in ids if "gpt-4o-mini" in i or "gpt-4o" in i]
    if not hits:
        hits = [i for i in ids if "mini" in i][:8]
    return True, ids, f"连通，共 {len(ids)} 个模型"


results: dict[str, tuple[bool, list[str], str]] = {}
for label, url in CANDIDATES:
    print(f"\n--- 探测 {label}: {url}")
    ok, ids, msg = probe(label, url)
    results[label] = (ok, ids, msg)
    if ok:
        print(f"    [OK] {msg}")
    else:
        print(f"    [!!] {msg}")

print("\n" + "=" * 72)
working = [lbl for lbl, (ok, _, _) in results.items() if ok]
if not working:
    print("[!!] 两个端点都不通。请检查 Key 是否正确 / 是否过期 / 网络是否可达。")
    sys.exit(1)

# ---------- 2. 对可用端点，列出候选模型并做一次极小聊天调用 ----------
recommended: list[tuple[str, str, str]] = []  # (label, base_url, model_id)

for lbl in working:
    _, ids, _ = results[lbl]
    base = dict(CANDIDATES)[lbl]
    hits = [i for i in ids if "gpt-4o-mini" in i]
    print(f"\n### {lbl} 上可用的 4o-mini 系列模型:")
    for h in hits[:10]:
        print(f"    {h}")
    if not hits:
        print("    (没找到 gpt-4o-mini 系列)")

    # 选一个最稳的进行测试调用
    prefer = None
    for cand in ("gpt-4o-mini-2024-07-18", "openai/gpt-4o-mini", "gpt-4o-mini"):
        if cand in ids:
            prefer = cand
            break
    if prefer is None and hits:
        prefer = hits[0]
    if prefer is None:
        print("    [!!] 没有可测的模型")
        continue

    print(f"\n    用 '{prefer}' 做一次极小调用（约 $0.0001）...")
    try:
        client = OpenAI(api_key=KEY, base_url=base, timeout=60.0)
        r = client.chat.completions.create(
            model=prefer,
            messages=[{"role": "user", "content": "Reply with OK"}],
            max_tokens=5,
        )
        print(f"    [OK] 调用成功，回复: {r.choices[0].message.content!r}")
        recommended.append((lbl, base, prefer))
    except Exception as e:
        print(f"    [!!] 调用失败 -> {type(e).__name__}: {str(e)[:200]}")
        print("        常见原因: 账号无余额 / 该模型未在你的账户白名单里")

print("\n" + "=" * 72)
if not recommended:
    print("[!!] 没有任何端点完成真实调用。通常是余额问题 —— 请充值后重跑本脚本。")
    sys.exit(1)

lbl, base, model = recommended[0]
print("推荐配置 —— 把下面这段写进项目根目录的 .env：")
print("-" * 72)
print("OPENAI_API_KEY=" + KEY)
if "openrouter" in base:
    print("OPENAI_BASE_URL=https://openrouter.ai/api/v1")
    print("# OpenRouter 的模型 id 需要带厂商前缀，如 openai/gpt-4o-mini")
else:
    print("# OpenAI 官方无需设置 OPENAI_BASE_URL")
print(f"AGENTDOJO_MODEL={model}")
print("-" * 72)
print("写完后重新跑 Step 1（本脚本）确认，再跑 Step 4 冒烟。")
print("=" * 72)
