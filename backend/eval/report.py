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


def mean_range(values: list[float | None]) -> dict | None:
    """Aggregate a small number of repeated-trial point estimates (e.g. a
    P95 latency computed once per trial, or an accuracy ratio computed once
    per trial) into a mean plus the observed min/max range across those
    trials.

    Exists because a fresh audit found this benchmark's own LLM-dependent
    metrics (skill-tagging accuracy, question groundedness, hint-generation
    P95 latency) reported as bare single-run numbers despite real, measured
    run-to-run variance from live Claude calls - e.g. skill-tagging accuracy
    reading 66.7%, 73.3%, and 100% across three otherwise-identical runs.
    `groundedness_eval.py` and `latency_eval.py` now run each such metric
    `NUM_TRIALS` times and pass the resulting list of per-trial numbers
    through here rather than reporting whichever single run happened last.

    `None` entries (e.g. a trial with zero checkable samples) are dropped
    before aggregating; returns `None` outright if nothing is left, so a
    metric with no real data shows up as `null` in the report rather than
    dividing by zero.
    """
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return {
        "mean": round(sum(clean) / len(clean), 4),
        "min": round(min(clean), 4),
        "max": round(max(clean), 4),
        "values": [round(v, 4) for v in clean],
        "n_trials": len(clean),
    }


def render_summary(report: dict) -> str:
    d = report["diagnostic_accuracy_detail"]
    g = report["question_groundedness_detail"]
    lat_detail = report["latency_percentiles_detail"]
    stage = report["latency_by_stage_ms"]

    lines: list[str] = []
    lines.append("ReadCoach Evaluation Benchmark - Summary")
    lines.append("=" * 42)
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    lines.append("DIAGNOSTIC ACCURACY (did the pipeline ID the injected skill/miscue correctly?)")
    lines.append("  Deterministic, no API calls - a single run is exact, not an estimate.")
    lines.append(f"  Overall: {d['accuracy']:.1%}  ({d['passed']}/{d['sample_size']} cases)")
    lines.append("  By category:")
    for category, bucket in sorted(d["by_category"].items(), key=lambda kv: kv[1]["accuracy"] or 0):
        lines.append(f"    {category:28s} {bucket['accuracy']:.1%}  ({bucket['passed']}/{bucket['total']})")
    lines.append("")

    trials_run = g.get("trials_run", 1)
    lines.append("QUESTION GROUNDEDNESS (LLM-judge: is each generated question answerable from the passage text?)")
    lines.append(f"  Real Claude calls, re-run {trials_run}x independently - reported as mean (observed range).")
    lines.append(f"  Overall: {_fmt_stat(g['groundedness'], as_percent=True)}")
    lines.append(f"    ({g['sample_size']} questions/trial, {g['passages_sampled']} passages; most recent "
                  f"trial: {g['grounded_count_last_trial']}/{g['sample_size']} grounded)")
    if g["ungrounded_examples"]:
        lines.append("  Ungrounded questions found (most recent trial):")
        for ex in g["ungrounded_examples"]:
            lines.append(f"    [{ex['passage_id']}] \"{ex['question']}\" - {ex['judge_reasoning']}")
    else:
        lines.append("  No ungrounded questions found in the most recent trial.")
    lines.append("")

    lines.append("SKILL-GAP IDENTIFICATION (did a generated question get tagged with the "
                  "passage's own designed vocabulary/comprehension skill?)")
    if g.get("skill_tagging_accuracy") is not None:
        lines.append(f"  Real Claude calls, re-run {trials_run}x independently - reported as mean (observed range).")
        lines.append(f"  Overall: {_fmt_stat(g['skill_tagging_accuracy'], as_percent=True)}")
        lines.append(f"    ({g['skill_tagging_checkable']} checkable passages/trial, phonics-primary passages "
                      f"excluded as not applicable; most recent trial: "
                      f"{g['skill_tagging_matches_last_trial']}/{g['skill_tagging_checkable']})")
        if g["skill_tagging_misses"]:
            lines.append("  Missed skill tags (most recent trial):")
            for miss in g["skill_tagging_misses"]:
                lines.append(f"    [{miss['passage_id']}] expected '{miss['expected_skill_id']}', "
                              f"got {miss['tagged_skill_ids']}")
    else:
        lines.append("  n/a (no vocabulary/comprehension passages in this sample)")
    lines.append("")

    lines.append("LATENCY (real Claude API calls, timed end-to-end through the real pipeline code)")
    lines.append(f"  Sessions run: {report['latency_sessions_run']} across {lat_detail['trials_run']} independent "
                  f"trials - P50/P95 reported as mean (observed range) across trials, not a single run.")
    lines.append("")
    lines.append("  Per-call (what a real session actually waits for at any one moment):")
    lines.append(f"    llm_ms (pooled)  P50={_fmt_stat(lat_detail['p50_ms_llm'])}")
    lines.append(f"                     P95={_fmt_stat(lat_detail['p95_ms_llm'])}")
    lines.append(f"    stt_ms/tts_ms    n/a ({report['latency_note']})")
    lines.append("  By stage:")
    for name, bucket in stage.items():
        lines.append(f"    {name} (n={bucket['n']} total samples across {bucket['trials_run']} trials)")
        lines.append(f"      P50={_fmt_stat(bucket['p50_ms'])}")
        lines.append(f"      P95={_fmt_stat(bucket['p95_ms'])}")
    lines.append("")
    total = report["session_total_llm_ms_percentiles"]
    lines.append(
        "  Whole-session total (every LLM call in one scripted session, summed "
        "back to back with none of a real session's own reading/thinking/"
        "speaking pauses between them - NOT what a session feels like, see "
        "per-call numbers above for that):"
    )
    lines.append(f"    session_total_llm_ms  P50={_fmt_stat(total['p50_ms'])}")
    lines.append(f"                          P95={_fmt_stat(total['p95_ms'])}")
    lines.append("")

    if report.get("flags"):
        lines.append("FLAGS FOR THE ORCHESTRATOR")
        for flag in report["flags"]:
            lines.append(f"  - {flag}")
        lines.append("")

    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}ms"


def _fmt_stat(stat: dict | None, as_percent: bool = False) -> str:
    """Render a `mean_range()` result as e.g. "90.2% (range: 86.3-94.1% across
    3 runs)" or "11627ms (range: 9800-13500ms across 2 runs)". `n/a` for
    `None` (no data - e.g. zero checkable samples in every trial).
    """
    if stat is None:
        return "n/a"
    if as_percent:
        return (f"{stat['mean']:.1%} (range: {stat['min']:.1%}-{stat['max']:.1%} "
                 f"across {stat['n_trials']} runs)")
    return (f"{stat['mean']:.0f}ms (range: {stat['min']:.0f}-{stat['max']:.0f}ms "
             f"across {stat['n_trials']} runs)")
