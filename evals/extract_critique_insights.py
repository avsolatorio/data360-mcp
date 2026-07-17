#!/usr/bin/env python3
"""
extract_critique_insights.py
============================

Reads all eval report JSONs in evals/reports/, extracts critique themes
and actionable improvement observations, and writes a Markdown file:
  evals/critique_recommendations.md

Usage:
    uv run python evals/extract_critique_insights.py
    uv run python evals/extract_critique_insights.py --min-score 0 --max-score 7
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

REPORTS_DIR = Path(__file__).parent / "reports"
OUT_FILE = Path(__file__).parent / "critique_recommendations.md"

ISSUE_PATTERNS: dict[str, str] = {
    "wrong_chart_type": (
        r"wrong (chart|type)|should (be|use) a? ?(bar|line|scatter|map|heatmap|choropleth)"
        r"|mismatches? the (intent|request|question)|incorrect chart|used .* instead of"
    ),
    "correlation_routed_as_small_multiples": (
        r"small.multiples.*(instead|rather|should|correct)"
        r"|should.*scatter|scatter.*(not|instead)"
        r"|does not.*scatter|not a.*scatter|fails.*scatter"
    ),
    "axis_issues": (
        r"axis.*(missing|label|title|format|unclear|wrong|not labeled|unlabeled)"
        r"|y-?axis|x-?axis.*(missing|unlabeled|wrong|no label)"
    ),
    "title_missing_or_weak": (
        r"(no |missing |without |lacks? )(title|heading)|title.*(missing|absent|unclear|generic|not present)"
    ),
    "legend_suppressed": (
        r"legend.*(missing|unclear|absent|not|confus|suppress|hidden)"
        r"|missing legend|no legend|suppresses? (the )?legend"
    ),
    "tooltip_incomplete": (
        r"tooltip.*(missing|unclear|absent|not|incomplete|no|lacks?)"
        r"|no tooltip|missing tooltip"
    ),
    "color_encoding_weak": (
        r"color.*(not|unclear|hard|poor|confus|distinguish|no contrast|monochro)"
        r"|can.t distinguish|hard to tell.*color|colors? are.*same"
    ),
    "unit_missing": (
        r"(no |missing |without )(unit|scale|percent|%)|unit.*(missing|not shown|absent|no label)"
    ),
    "year_gap_lines": (
        r"(missing|gap).*(year|period|data)|broken.*(line|series)|year.*(gap|missing)"
        r"|data gap|gaps? in (the )?(line|series|chart)"
    ),
    "source_attribution_missing": (
        r"(no |missing )(source|attribution|citation)|source.*(missing|not shown|absent|unlabeled)"
    ),
    "country_label_missing": (
        r"missing.*(country|economy|countr)|country.*(not labeled|missing|absent|not shown)"
        r"|countr.*(name|label).*(missing|not)"
    ),
    "empty_or_sparse_data": (
        r"no (usable )?data|rankings? is empty|total_with_data.{0,5}0"
        r"|empty (result|response|chart)|no (values|records|rows)"
    ),
    "data_mismatch": (
        r"wrong (country|indicator|data|year|period)"
        r"|incorrect (country|indicator|data|year|period)"
        r"|data.*(mismatch|wrong|incorrect|not.*intended)"
        r"|not the (right|correct) (data|indicator)"
    ),
    "sort_order_missing": (
        r"(not sorted|unsorted|no sort|missing sort)"
        r"|should be sorted|sorted (by|descend|ascend)"
        r"|order.*(missing|wrong|not applied)"
    ),
    "zero_line_missing": (
        r"(no |missing )(zero.?line|baseline|reference.?line)"
        r"|zero.?line.*(missing|absent|not shown)"
    ),
}

SENTENCE_PATTERNS: dict[str, str] = {
    "tooltip":  r"[Tt]ooltip[^.!?]{0,200}[.!?]",
    "axis":     r"[Aa]xis[^.!?]{0,200}[.!?]",
    "legend":   r"[Ll]egend[^.!?]{0,200}[.!?]",
    "title":    r"[Tt]itle[^.!?]{0,200}[.!?]",
    "color":    r"[Cc]olor[^.!?]{0,200}[.!?]",
    "sort":     r"sort[^.!?]{0,200}[.!?]",
    "unit":     r"unit[^.!?]{0,200}[.!?]",
    "source":   r"source[^.!?]{0,200}[.!?]",
    "zero":     r"zero.?line[^.!?]{0,200}[.!?]",
    "data_gap": r"(gap|missing).{0,20}(year|data|period)[^.!?]{0,200}[.!?]",
}

THEME_META: dict[str, dict] = {
    "wrong_chart_type":                     {"pri": "HIGH",   "fix": "Improve routing rules or add explicit chart_type hints to callers"},
    "correlation_routed_as_small_multiples":{"pri": "HIGH",   "fix": "TwoIndicatorRule: prefer CORRELATION_TEMPORAL for 2-ind + ≤8 countries + ≤6 years without hint"},
    "axis_issues":                          {"pri": "HIGH",   "fix": "Ensure axis titles set via unit metadata; run FixValueAxisEncodingRule on all strategies"},
    "legend_suppressed":                    {"pri": "HIGH",   "fix": "Audit all strategies for unintentional legend=None; only suppress for truly single-series charts"},
    "tooltip_incomplete":                   {"pri": "MEDIUM", "fix": "Standardize tooltip template: country, year, value+unit, indicator_name"},
    "title_missing_or_weak":               {"pri": "MEDIUM", "fix": "Always set chart title using indicator_name + country context template; never leave None"},
    "color_encoding_weak":                 {"pri": "MEDIUM", "fix": "Use WB palette with ≥8 distinct colors; apply ApplyWBStyleRule to all strategies"},
    "unit_missing":                        {"pri": "MEDIUM", "fix": "Propagate UNIT_MULT from metadata through to axis labelExpr and tooltip format string"},
    "year_gap_lines":                      {"pri": "MEDIUM", "fix": "Ensure LineYearGapStrokeDashRule applies to ALL temporal strategies, not only temporal_single"},
    "sort_order_missing":                  {"pri": "MEDIUM", "fix": "Cross-sectional and chained-rank bars must have sort: {field: value, order: descending} by default"},
    "zero_line_missing":                   {"pri": "LOW",    "fix": "ZeroLineRule: ensure applied to all signed-value strategies (temporal, cross-sectional)"},
    "source_attribution_missing":          {"pri": "LOW",    "fix": "Footer source line must always include indicator_id · database_id · data360"},
    "country_label_missing":              {"pri": "LOW",    "fix": "End-of-line country labels for multi-series lines via labelExpr on countryName field"},
    "empty_or_sparse_data":              {"pri": "INFO",   "fix": "Pre-flight: return user-facing error if row_count=0 before calling viz pipeline"},
    "data_mismatch":                      {"pri": "INFO",   "fix": "Verify indicator_id in viz call matches search result; add assertion in run_viz_pipeline"},
}

PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}


def load_records(min_score: float, max_score: float) -> list[dict]:
    records = []
    for path in sorted(glob.glob(str(REPORTS_DIR / "*.json"))):
        try:
            d = json.loads(Path(path).read_text())
            critique = d.get("critique") or d.get("eval_critique")
            score_raw = d.get("score_out_of_10") or d.get("score")
            if not critique or score_raw is None:
                continue
            if "fail" in str(critique).lower()[:30]:
                continue
            score = float(score_raw)
            if not (min_score <= score <= max_score):
                continue
            strategy = d.get("strategy") or (d.get("viz_result") or {}).get("strategy")
            records.append({"id": d.get("scenario_id", os.path.basename(path)),
                            "score": score, "critique": critique,
                            "strategy": strategy, "file": path})
        except Exception:
            pass
    return records


def bucket_by_theme(records: list[dict]) -> dict[str, dict]:
    buckets = {t: {"count": 0, "scores": [], "examples": []} for t in ISSUE_PATTERNS}
    for r in records:
        c_lower = r["critique"].lower()
        for theme, pattern in ISSUE_PATTERNS.items():
            if re.search(pattern, c_lower, re.IGNORECASE):
                b = buckets[theme]
                b["count"] += 1
                b["scores"].append(r["score"])
                if len(b["examples"]) < 3:
                    b["examples"].append(r)
    return buckets


def extract_sentences(records: list[dict]) -> dict[str, list[tuple[float, str]]]:
    seen: set[str] = set()
    out: dict[str, list] = defaultdict(list)
    for r in records:
        for label, pattern in SENTENCE_PATTERNS.items():
            # Use finditer so .group(0) always gives the full match string,
            # even when the pattern contains capture groups.
            for match in re.finditer(pattern, r["critique"]):
                m = match.group(0).strip()
                key = m[:60].lower()
                if len(m) > 20 and key not in seen:
                    seen.add(key)
                    out[label].append((r["score"], m))
    for label in out:
        out[label].sort(key=lambda x: x[0])
    return out


def render_markdown(records: list[dict], buckets: dict[str, dict],
                    sentences: dict[str, list]) -> str:
    total = len(records)
    avg = sum(r["score"] for r in records) / total if records else 0
    lines: list[str] = []
    lines.append("# Viz Engine Critique Recommendations\n")
    lines.append(f"> Auto-generated from **{total} eval reports** (avg score: **{avg:.1f}/10**).\n")
    lines.append("> Use these to prioritize improvements in `viz_config.py` and `visualization.py`.\n")

    lines.append("\n## Score Distribution\n")
    dist = Counter(int(r["score"]) for r in records)
    lines.append("| Score | Count | Bar |\n|---|---|---|")
    for s in sorted(dist):
        bar = "▓" * dist[s]
        lines.append(f"| {s}/10 | {dist[s]} | {bar} |")

    lines.append("\n## Issue Frequency Table\n")
    lines.append("| Priority | Issue | Count | % Reports | Avg Score | Fix |")
    lines.append("|---|---|---|---|---|---|")
    sorted_themes = sorted(
        buckets.items(),
        key=lambda kv: (
            PRIORITY_ORDER.get(THEME_META.get(kv[0], {}).get("pri", "INFO"), 9),
            -kv[1]["count"],
        ),
    )
    for theme, b in sorted_themes:
        if b["count"] == 0:
            continue
        meta = THEME_META.get(theme, {"pri": "INFO", "fix": "—"})
        avg_s = sum(b["scores"]) / len(b["scores"]) if b["scores"] else 0
        pct = 100 * b["count"] / total
        lines.append(
            f"| **{meta['pri']}** | `{theme}` | {b['count']} | {pct:.1f}% "
            f"| {avg_s:.1f} | {meta['fix']} |"
        )

    lines.append("\n---\n\n## Detailed Recommendations\n")
    for theme, b in sorted_themes:
        if b["count"] == 0:
            continue
        meta = THEME_META.get(theme, {"pri": "INFO", "fix": "—"})
        avg_s = sum(b["scores"]) / len(b["scores"]) if b["scores"] else 0
        lines.append(f"### `{theme}` — [{meta['pri']}]")
        lines.append(f"**Frequency**: {b['count']}/{total} ({100*b['count']/total:.1f}%)  ")
        lines.append(f"**Avg score when flagged**: {avg_s:.1f}/10  ")
        lines.append(f"**Fix**: {meta['fix']}\n")
        if b["examples"]:
            lines.append("**Representative critiques**:\n")
            for ex in sorted(b["examples"], key=lambda x: x["score"])[:3]:
                excerpt = ex["critique"][:350].replace("\n", " ")
                lines.append(f"> [{ex['score']:.1f}/10] *{excerpt}*\n")
        lines.append("")

    lines.append("---\n\n## Verbatim Judge Observations by Topic\n")
    for label in ["tooltip","axis","legend","title","color","sort","unit","source","zero","data_gap"]:
        hits = sentences.get(label, [])
        if not hits:
            continue
        lines.append(f"### {label.replace('_', ' ').title()}\n")
        for score, sentence in hits[:6]:
            lines.append(f"- [{score:.1f}] {sentence}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--max-score", type=float, default=10.0)
    parser.add_argument("--output", default=str(OUT_FILE))
    args = parser.parse_args()

    print(f"Loading reports from {REPORTS_DIR} ...")
    records = load_records(args.min_score, args.max_score)
    print(f"  Found {len(records)} reports (score {args.min_score}–{args.max_score})")
    buckets = bucket_by_theme(records)
    sentences = extract_sentences(records)
    md = render_markdown(records, buckets, sentences)
    Path(args.output).write_text(md, encoding="utf-8")

    print("\nTop issues by frequency:")
    for theme, b in sorted(buckets.items(), key=lambda kv: -kv[1]["count"])[:8]:
        if b["count"] == 0:
            continue
        avg_s = sum(b["scores"]) / len(b["scores"])
        meta = THEME_META.get(theme, {})
        print(f"  [{meta.get('pri','?'):6}] {theme:<42} n={b['count']:3}  avg={avg_s:.1f}")

    print(f"\nWritten: {args.output}")


if __name__ == "__main__":
    main()
