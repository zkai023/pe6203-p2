"""画演示用的架构图（p.4 审批门 + p.2 动机对比）。

出图不需要再跑实验，只要有 matplotlib 就行，不花 API 钱。

用法:  python scripts/make_architecture_figure.py
产出:  report_out/architecture.png
       report_out/motivation.png
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "report_out"
OUT.mkdir(parents=True, exist_ok=True)

C_TEXT = "#222222"
C_LLM = "#DCE7F5"
C_GATE = "#FCE9C8"
C_ROUTE_A = "#D8EFD8"
C_ROUTE_E = "#FFF2CC"
C_ROUTE_D = "#F6D6D6"
C_TOOL = "#E8E2F2"
C_REVIEW = "#EAEAEA"


def box(ax, x, y, w, h, text, fc, fs=11, bold=False, tc=C_TEXT):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=1.4, edgecolor="#888888", facecolor=fc,
        )
    )
    ax.text(
        x + w / 2, y + h / 2, text,
        ha="center", va="center", fontsize=fs,
        fontweight="bold" if bold else "normal", color=tc,
        linespacing=1.5,
    )


def arrow(ax, x1, y1, x2, y2, label=None, color="#444444", style="-", lw=1.4, ls=(-0.4, 0, 0.4)):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1), (x2, y2),
            arrowstyle="-|>", mutation_scale=14,
            linewidth=lw, color=color, linestyle=style,
            shrinkA=2, shrinkB=2,
            connectionstyle="arc3,rad=0",
        )
    )
    if label:
        ax.text(
            (x1 + x2) / 2, (y1 + y2) / 2 + 0.09, label,
            ha="center", va="bottom", fontsize=9, color=color,
        )


def draw_architecture():
    fig, ax = plt.subplots(figsize=(13, 6.4), dpi=150)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 6.4)
    ax.axis("off")

    ax.text(0.15, 6.18, "ApprovalGate: a drop-in replacement for ToolsExecutor",
            fontsize=15, fontweight="bold", color=C_TEXT)
    ax.text(0.15, 5.85, "Interception happens after the model emits tool_calls, before anything executes",
            fontsize=10, color="#666666")
    ax.text(12.85, 0.13, "AgentDojo v1.2.2 - banking - the only element we swap is ToolsExecutor",
            fontsize=9, color="#888888", ha="right")

    # 主链：LLM -> Gate -> Tools（三者同一水平线 y=4.3）
    box(ax, 0.4, 3.7, 2.3, 1.2, "LLM\n(gpt-4o-mini)", C_LLM, fs=11.5, bold=True)
    box(ax, 8.8, 3.7, 2.8, 1.2, "Banking tools\n(real execution)", C_TOOL, fs=11.5, bold=True)

    # 门的外框（高度压到 5.1，给上方的回流弧线让出通道）
    ax.add_patch(
        FancyBboxPatch(
            (3.4, 3.35), 4.6, 1.75,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=2.0, edgecolor="#B07A2E", facecolor=C_GATE, alpha=0.55,
        )
    )
    ax.text(5.7, 4.72, "ApprovalGate", ha="center", va="center",
            fontsize=13, fontweight="bold", color="#8A5A15")

    # 门内三路
    box(ax, 3.6, 3.5, 1.3, 0.6, "approve", C_ROUTE_A, fs=11, bold=True)
    box(ax, 5.1, 3.5, 1.3, 0.6, "escalate", C_ROUTE_E, fs=11, bold=True)
    box(ax, 6.6, 3.5, 1.15, 0.6, "deny", C_ROUTE_D, fs=11, bold=True)

    arrow(ax, 2.7, 4.3, 3.4, 4.3, "tool_calls")
    arrow(ax, 8.0, 4.3, 8.8, 4.3, "approved")

    # escalate 向下到审稿人
    box(ax, 4.2, 1.55, 3.0, 1.0,
        "Human review\n(LLM-simulated, budget k)", C_REVIEW, fs=10.5, bold=True)
    arrow(ax, 5.75, 3.5, 5.75, 2.55)
    ax.text(5.95, 3.05, "if budget left", ha="left", va="center", fontsize=9,
            color="#555555", bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none"))

    # 审稿人裁决
    box(ax, 1.9, 0.28, 2.5, 0.62, "ALLOW -> executes", C_ROUTE_A, fs=9.5)
    box(ax, 7.3, 0.28, 2.5, 0.62, "BLOCK -> refusal returned", C_ROUTE_D, fs=9.5)
    arrow(ax, 5.35, 1.55, 3.4, 0.9)
    arrow(ax, 6.05, 1.55, 8.0, 0.9)

    # 工具结果回到 LLM：走上方弧线，避开中间的门
    ax.annotate(
        "", xy=(1.5, 4.9), xytext=(10.2, 4.9),
        arrowprops=dict(arrowstyle="-|>", color="#444444", lw=1.4,
                        connectionstyle="arc3,rad=0.18"),
    )
    ax.text(5.9, 5.45, "tool results (or a refusal message) -> the loop continues",
            ha="center", va="center", fontsize=9.5, color="#555555")

    # 预算耗尽：放在右下空白，虚线指向门内
    ax.text(10.4, 1.95, "Budget exhausted:\nescalate degrades\nto auto-deny",
            ha="center", va="center", fontsize=9.5, color="#A33", linespacing=1.4,
            bbox=dict(boxstyle="round,pad=0.4", fc="#FBEDED", ec="#D9A0A0", lw=1.0))
    arrow(ax, 8.6, 1.95, 8.05, 3.55, style=":", color="#A33", lw=1.2)

    fig.tight_layout()
    fig.savefig(OUT / "architecture.png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def draw_motivation():
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 5.2)
    ax.axis("off")

    ax.text(0.15, 4.85, "The core tension: useful agents are dangerous agents",
            fontsize=15, fontweight="bold", color=C_TEXT)
    ax.text(0.15, 4.5, "Human attention is scarce - approval is a budget allocation problem",
            fontsize=10.5, color="#666666")

    # 左：什么都问。卡片加高到 2.6，底部给结论文字留出独立一行
    ax.add_patch(FancyBboxPatch((0.5, 1.6), 4.4, 2.6,
                                boxstyle="round,pad=0.02,rounding_size=0.08",
                                linewidth=1.5, edgecolor="#888888", facecolor="#F6D6D6"))
    ax.text(2.7, 3.88, "Ask about everything", ha="center", fontsize=13,
            fontweight="bold", color="#8A2A2A")
    for i, t in enumerate([
        "read_file        -> ask",
        "get transactions -> ask",
        "send_money       -> ask",
        "budget exhausted -> refuse",
    ]):
        ax.text(1.0, 3.42 - i * 0.4, t, ha="left", va="center",
                fontsize=10.5, family="monospace", color="#5A2A2A")
    ax.text(2.7, 1.82, "nobody has time for this", ha="center", fontsize=11,
            fontweight="bold", color="#A33")

    # 右：什么都不问
    ax.add_patch(FancyBboxPatch((6.1, 1.6), 4.4, 2.6,
                                boxstyle="round,pad=0.02,rounding_size=0.08",
                                linewidth=1.5, edgecolor="#888888", facecolor="#F6D6D6"))
    ax.text(8.3, 3.88, "Ask about nothing", ha="center", fontsize=13,
            fontweight="bold", color="#8A2A2A")
    for i, t in enumerate([
        "read_file        -> ok",
        "get transactions -> ok",
        "send_money       -> ok (attacker)",
        "54-67% of tasks compromised",
    ]):
        ax.text(6.6, 3.42 - i * 0.4, t, ha="left", va="center",
                fontsize=10.5, family="monospace",
                color="#A33" if i == 2 else "#5A2A2A",
                fontweight="bold" if i == 2 else "normal")
    ax.text(8.3, 1.82, "the money is already gone", ha="center", fontsize=11,
            fontweight="bold", color="#A33")

    # 中间：我们
    ax.add_patch(FancyBboxPatch((4.25, 0.3), 2.5, 1.0,
                                boxstyle="round,pad=0.02,rounding_size=0.08",
                                linewidth=2.0, edgecolor="#3E8E3E", facecolor="#D8EFD8"))
    ax.text(5.5, 0.8, "Spend the budget\nwhere it can matter", ha="center", va="center",
            fontsize=11, fontweight="bold", color="#2E6B2E", linespacing=1.4)

    arrow(ax, 4.9, 1.6, 3.7, 1.3, style="-", color="#3E8E3E")
    arrow(ax, 6.1, 1.6, 7.3, 1.3, style="-", color="#3E8E3E")

    fig.tight_layout()
    fig.savefig(OUT / "motivation.png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    draw_architecture()
    draw_motivation()
    print(f"architecture.png -> {OUT / 'architecture.png'}")
    print(f"motivation.png   -> {OUT / 'motivation.png'}")


if __name__ == "__main__":
    main()
