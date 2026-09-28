#!/usr/bin/env python3
"""Benchmark and evaluation suite for V3 lexical search and strict retrieval.

Offline, zero model calls, pure Python standard library.
Measures Recall@1, Recall@3, Recall@5, MRR, latency, and failure distributions
across calibrated search categories on a frozen, sanitized vault corpus.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "template/.claude/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_FIXTURE = ROOT / "tests/fixtures/v3/search_benchmark.json"
DEFAULT_DIGEST = ROOT / "tests/fixtures/v3/search_benchmark.sha256"


def read_fixture(fixture_path: Optional[Path] = None) -> Tuple[Dict[str, Any], str]:
    """Read and verify the frozen search benchmark fixture."""
    path = Path(fixture_path or DEFAULT_FIXTURE).resolve()
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    digest_path = path.with_suffix(".sha256")
    if digest_path.is_file():
        expected = digest_path.read_text(encoding="utf-8").strip()
        if expected and digest != expected:
            raise ValueError(f"Fixture checksum mismatch for {path.name}: {digest} != {expected}")
    data = json.loads(content.decode("utf-8"))
    return data, digest


def load_runtime():
    """Load the V3 runtime module from template scripts."""
    import beyin_v3 as runtime
    return runtime


def seed_store(runtime, temp_dir: Path, fixture: Dict[str, Any]) -> Tuple[Any, float]:
    """Ingest fixture records into an isolated MemoryStore; returns (store, cold_index_ms)."""
    vault = temp_dir / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    runtime_dir = temp_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    store = runtime.MemoryStore(runtime_dir, vault)

    t0 = time.perf_counter()
    for rec in fixture.get("records", []):
        path = vault / rec["source"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rec["text"], encoding="utf-8")
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        store.ingest({
            "id": rec["id"],
            "title": rec.get("title", ""),
            "kind": rec.get("kind", "note"),
            "visibility": rec.get("visibility", "internal"),
            "text": rec["text"],
            "facts": rec.get("facts", {}),
            "source": rec["source"],
            "source_sha256": actual_sha,
            "updated_at": rec.get("updated_at", "2026-09-01T00:00:00Z")
        })
    cold_index_ms = round((time.perf_counter() - t0) * 1000, 2)
    return store, cold_index_ms


def percentile(values: List[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = max(0, math.ceil(len(sorted_vals) * fraction) - 1)
    return round(sorted_vals[idx], 2)


def evaluate_mode(store, cases: List[Dict[str, Any]], mode: str, limit: int = 10) -> Dict[str, Any]:
    """Evaluate a set of benchmark cases under a specific retrieval mode."""
    timings: List[float] = []
    case_results: List[Dict[str, Any]] = []

    category_stats: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        cat = case.get("category", "unclassified")
        if cat not in category_stats:
            category_stats[cat] = {
                "count": 0,
                "r1": 0,
                "r3": 0,
                "r5": 0,
                "reciprocal_ranks": [],
                "misses": []
            }

    for case in cases:
        query = case["query"]
        target_id = case["target_id"]
        category = case.get("category", "unclassified")

        t0 = time.perf_counter()
        if mode == "non_strict":
            res = store._retrieve(query, limit=limit, strict=False)
            records = res.get("records", [])
        elif mode == "strict":
            res = store._retrieve(query, limit=limit, strict=True)
            records = res.get("records", [])
        elif mode == "context":
            ctx = store.context_for("claude", query, strict=True, budget_chars=8000)
            records = ctx.get("records", [])
        else:
            raise ValueError(f"Unknown mode: {mode}")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        timings.append(elapsed_ms)

        retrieved_ids = [r["id"] for r in records]
        rank = None
        if target_id in retrieved_ids:
            rank = retrieved_ids.index(target_id) + 1

        reciprocal_rank = 1.0 / rank if rank else 0.0
        hit_1 = 1 if rank == 1 else 0
        hit_3 = 1 if (rank and rank <= 3) else 0
        hit_5 = 1 if (rank and rank <= 5) else 0

        # Track category stats
        category_stats[category]["count"] += 1
        category_stats[category]["r1"] += hit_1
        category_stats[category]["r3"] += hit_3
        category_stats[category]["r5"] += hit_5
        category_stats[category]["reciprocal_ranks"].append(reciprocal_rank)

        top_id = retrieved_ids[0] if retrieved_ids else None
        top_title = records[0].get("title", "") if records else None

        case_res = {
            "case_id": case["id"],
            "query": query,
            "category": category,
            "target_id": target_id,
            "rank": rank,
            "reciprocal_rank": round(reciprocal_rank, 4),
            "top_retrieved_id": top_id,
            "top_retrieved_title": top_title,
            "elapsed_ms": round(elapsed_ms, 2)
        }
        case_results.append(case_res)

        if rank != 1:
            category_stats[category]["misses"].append(case_res)

    total_cases = len(cases)
    total_r1 = sum(c["rank"] == 1 for c in case_results)
    total_r3 = sum(bool(c["rank"] and c["rank"] <= 3) for c in case_results)
    total_r5 = sum(bool(c["rank"] and c["rank"] <= 5) for c in case_results)
    mrr = sum(c["reciprocal_rank"] for c in case_results) / total_cases if total_cases else 0.0

    cat_breakdown = {}
    for cat, stats in sorted(category_stats.items()):
        c_count = stats["count"]
        cat_breakdown[cat] = {
            "count": c_count,
            "recall_at_1": round(stats["r1"] / c_count, 3) if c_count else 0.0,
            "recall_at_3": round(stats["r3"] / c_count, 3) if c_count else 0.0,
            "recall_at_5": round(stats["r5"] / c_count, 3) if c_count else 0.0,
            "mrr": round(sum(stats["reciprocal_ranks"]) / c_count, 3) if c_count else 0.0,
            "miss_count": len(stats["misses"])
        }

    return {
        "mode": mode,
        "total_cases": total_cases,
        "recall_at_1": round(total_r1 / total_cases, 3) if total_cases else 0.0,
        "recall_at_3": round(total_r3 / total_cases, 3) if total_cases else 0.0,
        "recall_at_5": round(total_r5 / total_cases, 3) if total_cases else 0.0,
        "mrr": round(mrr, 3),
        "median_latency_ms": percentile(timings, 0.50),
        "p95_latency_ms": percentile(timings, 0.95),
        "categories": cat_breakdown,
        "case_results": case_results
    }


def evaluate(fixture_path: Optional[Path] = None, limit: int = 10, modes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Execute complete benchmark across requested modes."""
    fixture, digest = read_fixture(fixture_path)
    runtime = load_runtime()
    modes = modes or ["non_strict", "strict", "context"]

    with tempfile.TemporaryDirectory(prefix="beyin-search-bench-") as tmp:
        store, cold_index_ms = seed_store(runtime, Path(tmp), fixture)

        results = {
            "fixture_digest": digest,
            "corpus_records": len(fixture.get("records", [])),
            "benchmark_cases": len(fixture.get("cases", [])),
            "cold_index_ms": cold_index_ms,
            "modes": {}
        }

        for m in modes:
            results["modes"][m] = evaluate_mode(store, fixture.get("cases", []), mode=m, limit=limit)

        return results


def format_markdown(report: Dict[str, Any]) -> str:
    """Format benchmark report into GitHub-flavored Markdown tables."""
    lines = []
    lines.append("# V3 Search Benchmark Report (Issue #94)")
    lines.append("")
    lines.append(f"- **Corpus**: {report['corpus_records']} sanitized technical records")
    lines.append(f"- **Test Cases**: {report['benchmark_cases']} queries across 7 failure/salience categories")
    lines.append(f"- **Cold Ingestion Time**: `{report['cold_index_ms']} ms` (SQLite store init & tokenization)")
    lines.append(f"- **Fixture SHA-256**: `{report['fixture_digest'][:16]}...`")
    lines.append("")

    lines.append("## 1. Global Metrics Summary")
    lines.append("")
    lines.append("| Retrieval Mode | Recall@1 | Recall@3 | Recall@5 | MRR | Median Latency | p95 Latency |")
    lines.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|")

    for mode, data in report["modes"].items():
        mode_label = {
            "non_strict": "Standard Search (`strict=False`)",
            "strict": "Strict Retrieval (`strict=True`)",
            "context": "Per-Turn Context Delivery"
        }.get(mode, mode)
        lines.append(f"| {mode_label} | **{data['recall_at_1']:.1%}** | {data['recall_at_3']:.1%} | {data['recall_at_5']:.1%} | **{data['mrr']:.3f}** | {data['median_latency_ms']} ms | {data['p95_latency_ms']} ms |")
    lines.append("")

    # Category breakdown for non-strict and strict
    for mode in ["non_strict", "strict"]:
        if mode not in report["modes"]:
            continue
        data = report["modes"][mode]
        title = "Standard Search (`strict=False`)" if mode == "non_strict" else "Strict Retrieval (`strict=True`)"
        lines.append(f"## 2. Category Breakdown: {title}")
        lines.append("")
        lines.append("| Category | Cases | Recall@1 | Recall@3 | Recall@5 | MRR | Misses | Description |")
        lines.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|---|")

        cat_desc = {
            "title_salience": "Title matches query terms, but 0 field weight causes tie/loss to distractors",
            "rare_vs_common": "Rare domain keyword query overwhelmed by distractor matching multiple common words",
            "distractor_suppression": "Long daily/retro notes matching incidental terms dilute target ranking",
            "term_frequency": "Dense term occurrences in target vs single mention in distractor",
            "single_term_strict": "Single keyword queries (e.g. Flyway, ClickHouse) dropped by STRICT_MIN_SHARED=2",
            "decision_adr": "Architectural decision lookup comparing options/rationale",
            "clean_baseline": "Direct control queries where baseline search works well"
        }

        for cat, stats in data["categories"].items():
            desc = cat_desc.get(cat, "")
            lines.append(f"| `{cat}` | {stats['count']} | **{stats['recall_at_1']:.1%}** | {stats['recall_at_3']:.1%} | {stats['recall_at_5']:.1%} | {stats['mrr']:.3f} | {stats['miss_count']} | {desc} |")
        lines.append("")

    # Detailed Misses Section for non_strict
    if "non_strict" in report["modes"]:
        non_strict_data = report["modes"]["non_strict"]
        misses = [c for c in non_strict_data["case_results"] if c["rank"] != 1]
        lines.append("## 3. Standard Search (`strict=False`) Sub-optimal Rankings (Where current search fails)")
        lines.append("")
        lines.append("| Case ID | Category | Query | Target Doc | Actual Rank | Top Returned Doc (Winner) |")
        lines.append("|---|---|---|---|:---:|---|")
        for m in misses:
            rank_str = str(m["rank"]) if m["rank"] else "Not Found"
            lines.append(f"| `{m['case_id']}` | `{m['category']}` | *{m['query']}* | `{m['target_id']}` | **{rank_str}** | `{m['top_retrieved_id']}` ({m['top_retrieved_title']}) |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help="Path to benchmark fixture JSON")
    parser.add_argument("--limit", type=int, default=10, help="Retrieval candidate limit")
    parser.add_argument("--modes", nargs="+", default=["non_strict", "strict", "context"], help="Modes to evaluate")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    report = evaluate(fixture_path=args.fixture, limit=args.limit, modes=args.modes)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
