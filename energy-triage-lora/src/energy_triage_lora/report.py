"""Charts and a results table, built only from metrics.json.

The report can therefore never disagree with a real run.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK = "#1f2a30"
SOFT = "#6b7780"
COLOURS = {
    "majority": "#c9ced2",
    "keyword rules": "#9aa5ad",
    "TF-IDF + logistic regression": "#5b6b75",
    "head": "#e0a43c",
    "lora": "#1f77b4",
    "full": "#2c9a6a",
    "int8 LoRA": "#7a5bb5",
    "lora, no unlabelled": "#9cc3e0",
    "full, no unlabelled": "#9fd2b8",
}
LABELS = {
    "head": "Head only (label rows)",
    "lora": "LoRA r=8 (q, v) + label rows",
    "full": "Full fine-tune",
    "int8 LoRA": "LoRA merged, int8",
    "lora, no unlabelled": "LoRA, pre-trained without unlabelled traffic",
    "full, no unlabelled": "Full, pre-trained without unlabelled traffic",
}


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(SOFT)
    ax.spines["bottom"].set_color(SOFT)
    ax.tick_params(colors=INK, labelsize=9)
    ax.yaxis.grid(True, color="#e6e8ea", linewidth=0.8)
    ax.set_axisbelow(True)


def rows(metrics: dict) -> list[tuple[str, dict]]:
    out = [(name, entry) for name, entry in metrics["baselines"].items()]
    t = metrics.get("transformer")
    if t:
        out += [(f"{n}, no unlabelled", e) for n, e in t.get("without_unlabelled", {}).items()]
        out += [(name, entry) for name, entry in t["methods"].items()]
        out.append(("int8 LoRA", t["quantized_lora"]))
    return out


SHORT = {
    "majority": "Majority class",
    "keyword rules": "Keyword rules",
    "TF-IDF + logistic regression": "TF-IDF + logistic regression",
    "lora, no unlabelled": "LoRA, no unlabelled pre-training",
    "full, no unlabelled": "Full, no unlabelled pre-training",
    "head": "Head only",
    "lora": "LoRA r=8",
    "full": "Full fine-tune",
    "int8 LoRA": "LoRA merged, int8",
}


def exact_match_chart(metrics: dict, path: Path) -> None:
    data = rows(metrics)[::-1]
    fig, ax = plt.subplots(figsize=(8.5, 5), dpi=120)
    height = 0.38
    ys = range(len(data))
    seen = [e["test_seen"]["exact_match"] for _, e in data]
    unseen = [e["test_unseen"]["exact_match"] for _, e in data]
    colours = [COLOURS[n] for n, _ in data]
    ax.barh([y + height / 2 for y in ys], seen, height, color=colours, alpha=0.4)
    bars = ax.barh([y - height / 2 for y in ys], unseen, height, color=colours)
    for bar, value in zip(bars, unseen, strict=True):
        ax.text(
            value + 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.0%}",
            va="center",
            fontsize=8,
            color=INK,
        )
    ax.set_yticks(list(ys), [SHORT.get(n, n) for n, _ in data], fontsize=9)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("Exact match (all three fields right)", color=INK)
    ax.set_title(
        "Pale: phrasings seen in training. Solid, labelled: held-out phrasings.",
        fontsize=10,
        color=INK,
        loc="left",
    )
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color="#e6e8ea", linewidth=0.8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def params_chart(metrics: dict, path: Path) -> None:
    t = metrics["transformer"]["methods"]
    fig, ax = plt.subplots(figsize=(6.5, 4), dpi=120)
    for name, e in t.items():
        ax.scatter(
            e["trainable_parameters"],
            e["test_unseen"]["exact_match"],
            s=90,
            color=COLOURS[name],
            zorder=3,
        )
        ax.annotate(
            f"{LABELS[name]}\n{e['trainable_parameters']:,} params, {e['seconds']:.0f} s",
            (e["trainable_parameters"], e["test_unseen"]["exact_match"]),
            textcoords="offset points",
            xytext=(8, -4),
            fontsize=8,
            color=INK,
        )
    tfidf = metrics["baselines"]["TF-IDF + logistic regression"]["test_unseen"]["exact_match"]
    ax.axhline(tfidf, color=COLOURS["TF-IDF + logistic regression"], linestyle="--", linewidth=1)
    ax.text(1.2e3, tfidf + 0.01, "TF-IDF + logistic regression", fontsize=8, color=SOFT)
    ax.set_xscale("log")
    ax.set_xlim(1e3, 3e6)
    ax.set_xlabel("Trainable parameters (log scale)", color=INK)
    ax.set_ylabel("Exact match, unseen phrasings", color=INK)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def coverage_chart(metrics: dict, path: Path) -> None:
    t = metrics["transformer"]["methods"]
    fig, ax = plt.subplots(figsize=(6.5, 4), dpi=120)
    for name in ("lora", "full", "head"):
        curve = t[name]["coverage_curve_unseen"]
        ax.plot(
            [c for _, c, _ in curve],
            [a for _, _, a in curve],
            color=COLOURS[name],
            label=LABELS[name],
            linewidth=2,
        )
        chosen = t[name]["abstention"]["test_unseen"]
        ax.scatter(
            [chosen["coverage"]],
            [chosen["accuracy_answered"]],
            color=COLOURS[name],
            s=50,
            zorder=3,
            edgecolor="white",
        )
    ax.set_xlabel("Share of messages answered automatically", color=INK)
    ax.set_ylabel("Exact match on the answered ones", color=INK)
    ax.set_title(
        "Unseen phrasings. Dots: threshold chosen on validation.",
        fontsize=10,
        color=INK,
        loc="left",
    )
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def loss_chart(metrics: dict, path: Path) -> None:
    t = metrics["transformer"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), dpi=120)
    steps, loss = zip(*t["pretrain"]["curve"], strict=True)
    axes[0].plot(steps, loss, color=INK, linewidth=2)
    axes[0].set_title("Pre-training (next token)", fontsize=10, color=INK, loc="left")
    for name, e in t["methods"].items():
        s, l_ = zip(*e["curve"], strict=True)
        axes[1].plot(s, l_, color=COLOURS[name], label=LABELS[name], linewidth=2)
    axes[1].set_title("Fine-tuning (answer tokens only)", fontsize=10, color=INK, loc="left")
    axes[1].legend(frameon=False, fontsize=8)
    for ax in axes:
        ax.set_xlabel("Step", color=INK)
        ax.set_ylabel("Smoothed loss", color=INK)
        _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def table(metrics: dict) -> str:
    header = (
        "| Model | Trainable params | Train time | Exact match (seen) | Exact match (unseen) "
        "| Category macro-F1 (unseen) | Vulnerable recall (unseen) | High-urgency recall (unseen) |"
    )
    lines = [header, "|---|---:|---:|---:|---:|---:|---:|---:|"]
    tr = metrics.get("transformer", {})
    t = dict(tr.get("methods", {}))
    t.update({f"{n}, no unlabelled": e for n, e in tr.get("without_unlabelled", {}).items()})
    for name, e in rows(metrics):
        params = (
            f"{t[name]['trainable_parameters']:,}"
            if name in t
            else ("none (post-training)" if name == "int8 LoRA" else "–")
        )
        secs = t[name]["seconds"] if name in t else e.get("fit_seconds")
        when = "–" if secs is None else f"{secs:.1f} s"
        u = e["test_unseen"]
        lines.append(
            f"| {LABELS.get(name, name)} | {params} | {when} "
            f"| {e['test_seen']['exact_match']:.1%} | {u['exact_match']:.1%} | "
            f"{u['category_macro_f1']:.3f} | {u['vulnerable_recall']:.1%} "
            f"| {u['high_urgency_recall']:.1%} |"
        )
    return "\n".join(lines)


def build(metrics_path: Path, out_dir: Path) -> list[Path]:
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    if "transformer" in metrics:
        for fn, name in (
            (exact_match_chart, "exact_match.png"),
            (params_chart, "params_vs_accuracy.png"),
            (coverage_chart, "coverage.png"),
            (loss_chart, "loss.png"),
        ):
            fn(metrics, out_dir / name)
            made.append(out_dir / name)
    (out_dir / "results.md").write_text(table(metrics) + "\n", encoding="utf-8")
    made.append(out_dir / "results.md")
    return made
