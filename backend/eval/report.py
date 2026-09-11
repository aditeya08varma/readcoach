"""Shared report-building helpers: percentile math and the human-readable
summary renderer. No pipeline logic lives here - just presentation of
numbers `diagnostic_eval.py`, `groundedness_eval.py`, and `latency_eval.py`
already computed.
"""

from __future__ import annotations

import math


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (same convention as numpy's default),
    e.g. percentile(values, 50) is the median, percentile(values, 95) is P95.
    Returns None for an empty sample rather than raising, so a stage with
    zero real samples shows up as `null` in the report instead of crashing
    the whole run.
    """
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return round(s[0], 1)
    rank = (pct / 100.0) * (len(s) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return round(s[lo], 1)
    frac = rank - lo
    return round(s[lo] + (s[hi] - s[lo]) * frac, 1)


def render_summary(report: dict) -> str:
    d = report["diagnostic_accuracy_detail"]
    g = report["question_groundedness_detail"]
    lat = report["latency_percentiles"]
    stage = report["latency_by_stage_ms"]

    lines: list[str] = []
    lines.append("ReadCoach Evaluation Benchmark - Summary")
    lines.append("=" * 42)
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    lines.append("DIAGNOSTIC ACCURACY (did the pipeline ID the injected skill/miscue correctly?)")
    lines.append(f"  Overall: {d['accuracy']:.1%}  ({d['passed']}/{d['sample_size']} cases)")
    lines.append("  By category:")
    for category, bucket in sorted(d["by_category"].items(), key=lambda kv: kv[1]["accuracy"] or 0):
        lines.append(f"    {category:28s} {bucket['accuracy']:.1%}  ({bucket['passed']}/{bucket['total']})")
    lines.append("")

    lines.append("QUESTION GROUNDEDNESS (LLM-judge: is each generated question answerable from the passage text?)")
    lines.append(f"  Overall: {g['groundedness']:.1%}  ({g['grounded_count']}/{g['sample_size']} questions, "
                  f"{g['passages_sampled']} passages)")
    if g["ungrounded_examples"]:
        lines.append("  Ungrounded questions found:")
        for ex in g["ungrounded_examples"]:
            lines.append(f"    [{ex['passage_id']}] \"{ex['question']}\" - {ex['judge_reasoning']}")
    else:
        lines.append("  No ungrounded questions found in this sample.")
    lines.append("")

    lines.append("LATENCY (real Claude API calls, timed end-to-end through the real pipeline code)")
    lines.append(f"  Sessions run: {report['latency_sessions_run']}")
    lines.append("")
    lines.append("  Per-call (what a real session actually waits for at any one moment):")
    lines.append(f"    llm_ms (pooled)         P50={_fmt(lat['p50_ms']['llm_ms'])}  P95={_fmt(lat['p95_ms']['llm_ms'])}")
    lines.append(f"    stt_ms                  P50={_fmt(lat['p50_ms']['stt_ms'])}  P95={_fmt(lat['p95_ms']['stt_ms'])}  "
                  f"({report['latency_note']})")
    lines.append(f"    tts_ms                  P50={_fmt(lat['p95_ms']['tts_ms'])}  P95={_fmt(lat['p95_ms']['tts_ms'])}  "
                  f"(same note)")
    lines.append("  By stage:")
    for name, bucket in stage.items():
        lines.append(f"    {name:24s} P50={_fmt(bucket['p50_ms'])}  P95={_fmt(bucket['p95_ms'])}  n={bucket['n']}")
    lines.append("")
    total = report["session_total_llm_ms_percentiles"]
    lines.append(
        "  Whole-session total (every LLM call in one scripted session, summed "
        "back to back with none of a real session's own reading/thinking/"
        "speaking pauses between them - NOT what a session feels like, see "
        "per-call numbers above for that):"
    )
    lines.append(f"    session_total_llm_ms    P50={_fmt(total['p50_ms'])}  P95={_fmt(total['p95_ms'])}")
    lines.append("")

    if report.get("flags"):
        lines.append("FLAGS FOR THE ORCHESTRATOR")
        for flag in report["flags"]:
            lines.append(f"  - {flag}")
        lines.append("")

    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}ms"
