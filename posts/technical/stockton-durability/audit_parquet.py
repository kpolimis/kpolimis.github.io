"""audit_parquet.py — data-quality check for quarter_splits parquets.

Reports per-column null/zero rates, flags all-zero columns, and smoke-tests
the play classifier against known BRef play-text patterns to verify the parser
is correct before running downstream analysis.

Usage:
    conda run -n blog python audit_parquet.py
    conda run -n blog python audit_parquet.py --parquet data/quarter_splits_pg.parquet
    conda run -n blog python audit_parquet.py --sample-html 50
"""

import argparse
import pathlib
import sys

import pandas as pd

DATA_DIR = pathlib.Path(__file__).parent / "data"
HTML_CACHE = DATA_DIR / "html_cache" / "quarter"

_NUMERIC_COLS = ["FT", "FTA", "FGA", "PTS", "AST", "TOV", "FT_pct", "TS_pct", "score_margin"]

# Expected behavior: score_margin is None for PBP rows (box-score path only)
_EXPECTED_ALL_NULL = {"score_margin"}

_CLASSIFIER_CASES = [
    # (play_text, last_name, first_name, expected)
    (
        "john stockton makes 2-pt jump shot from 14 ft",
        "stockton",
        "john",
        {"FGA": 1, "PTS": 2, "FT": 0, "FTA": 0, "AST": 0, "TOV": 0},
    ),
    (
        "john stockton makes 3-pt jump shot from 24 ft",
        "stockton",
        "john",
        {"FGA": 1, "PTS": 3, "FT": 0, "FTA": 0, "AST": 0, "TOV": 0},
    ),
    (
        "john stockton misses 2-pt jump shot",
        "stockton",
        "john",
        {"FGA": 1, "PTS": 0, "FT": 0, "FTA": 0, "AST": 0, "TOV": 0},
    ),
    # P8: misses 3-pt case
    (
        "john stockton misses 3-pt jump shot from 26 ft",
        "stockton",
        "john",
        {"FGA": 1, "PTS": 0, "FT": 0, "FTA": 0, "AST": 0, "TOV": 0},
    ),
    (
        "john stockton makes free throw 1 of 2",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 1, "FT": 1, "FTA": 1, "AST": 0, "TOV": 0},
    ),
    (
        "john stockton misses free throw 2 of 2",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 0, "FT": 0, "FTA": 1, "AST": 0, "TOV": 0},
    ),
    # P7: technical free throw — previously undetected because regex required adjacent "free throw"
    (
        "john stockton makes technical free throw",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 1, "FT": 1, "FTA": 1, "AST": 0, "TOV": 0},
    ),
    (
        "john stockton misses technical free throw",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 0, "FT": 0, "FTA": 1, "AST": 0, "TOV": 0},
    ),
    # Assist: Malone makes, Stockton assists — Stockton gets AST only
    (
        "karl malone makes 2-pt jump shot from 14 ft (assist by john stockton)",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 0, "FT": 0, "FTA": 0, "AST": 1, "TOV": 0},
    ),
    # Steal: Malone turns over, Stockton steals — Stockton gets nothing
    (
        "turnover by karl malone (steal by john stockton)",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 0, "FT": 0, "FTA": 0, "AST": 0, "TOV": 0},
    ),
    # Turnover by Stockton
    (
        "turnover by john stockton (bad pass)",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 0, "FT": 0, "FTA": 0, "AST": 0, "TOV": 1},
    ),
    # P6: first-name substring collision — "john" must not match "johnson" or "johnny"
    (
        "avery johnson makes 2-pt jump shot from 12 ft",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 0, "FT": 0, "FTA": 0, "AST": 0, "TOV": 0},
    ),
    (
        "john starks makes 2-pt jump shot from 14 ft",
        "stockton",
        "john",
        {"FGA": 0, "PTS": 0, "FT": 0, "FTA": 0, "AST": 0, "TOV": 0},
    ),
]


def _smoke_test_classifier() -> int:
    """Run known BRef play strings through _classify_play and report failures.

    Returns:
        Number of failed cases.
    """
    import fetch_quarter_splits as fqs  # noqa: PLC0415

    failures = 0
    print(f"\n{'=' * 60}")
    print("CLASSIFIER SMOKE TEST")
    print(f"{'=' * 60}")
    for play, last, first, expected in _CLASSIFIER_CASES:
        got = fqs._classify_play(play, last, first)
        ok = all(got.get(k) == v for k, v in expected.items())
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
            print(f"  {status}  {play!r}")
            for k, v in expected.items():
                if got.get(k) != v:
                    print(f"         {k}: expected={v}  got={got.get(k)}")
        else:
            print(f"  {status}  {play[:60]!r}")
    print(f"\n{len(_CLASSIFIER_CASES) - failures}/{len(_CLASSIFIER_CASES)} cases passed")
    return failures


_REQUIRED_COLS = {"FGA", "FTA", "PTS"}


def _audit_file(path: pathlib.Path, error_on_missing: bool = False) -> int:
    """Report null/zero rates for all numeric columns in one parquet file.

    Args:
        path: Path to a quarter_splits_*.parquet file.
        error_on_missing: If True, count a missing file as an issue (use for
            explicit --parquet paths; auto-discovered files are skipped silently).

    Returns:
        Number of unexpected all-zero, all-null, or structural issues.
    """
    if not path.exists():
        if error_on_missing:
            print(f"ERROR  {path} — file not found (--parquet path must exist)")
            return 1
        print(f"SKIP  {path.name} — file not found")
        return 0

    df = pd.read_parquet(path)
    issues = 0
    print(f"\n{'=' * 60}")

    if df.empty:
        print(f"FILE  {path.name}  *** EMPTY PARQUET — 0 rows")
        print(f"{'=' * 60}")
        return 1

    qvc = df["quarter"].value_counts().to_dict() if "quarter" in df.columns else "(no quarter col)"
    print(f"FILE  {path.name}  ({len(df):,} rows, {qvc})")
    print(f"{'=' * 60}")

    missing_core = _REQUIRED_COLS - set(df.columns)
    if missing_core:
        print(f"*** MISSING CORE COLUMNS: {missing_core}")
        issues += len(missing_core)

    print(f"{'Column':<16} {'Null%':>7} {'Zero%':>7} {'Mean':>10} {'p50':>10}  Flag")
    print("-" * 60)

    # score_margin is expected all-null only when no box-fallback ("full") rows exist
    has_full_rows = "quarter" in df.columns and (df["quarter"].astype(str) == "full").any()
    expected_all_null = _EXPECTED_ALL_NULL if not has_full_rows else set()

    for col in _NUMERIC_COLS:
        if col not in df.columns:
            continue
        s = df[col]
        null_pct = s.isna().mean() * 100
        nonnull = s.dropna()
        zero_pct = (nonnull == 0).mean() * 100 if len(nonnull) else float("nan")
        mean_v = nonnull.mean() if len(nonnull) else float("nan")
        p50_v = nonnull.median() if len(nonnull) else float("nan")

        flag = ""
        if null_pct == 100:
            if col not in expected_all_null:
                flag = "*** UNEXPECTED ALL-NULL"
                issues += 1
            else:
                flag = "(expected — PBP path only)"
        elif zero_pct == 100:
            flag = "*** ALL ZERO"
            issues += 1

        print(
            f"{col:<16} {null_pct:>6.1f}% {zero_pct:>6.1f}% {mean_v:>10.3f} {p50_v:>10.3f}  {flag}"
        )

    return issues


def _sample_html_parse(n: int) -> int:
    """Parse n cached PBP HTML files and report aggregate stat totals.

    Args:
        n: Number of cached files to parse.

    Returns:
        Number of issues found (0 = clean, >0 = issues).
    """
    import fetch_quarter_splits as fqs  # noqa: PLC0415

    pbp_files = sorted(HTML_CACHE.glob("*_pbp.html"))[:n]
    if not pbp_files:
        print("\nNo cached PBP HTML found — skipping HTML sample parse.")
        return 0

    # Use Stockton for the sample (his games are in the cache)
    totals: dict[str, int] = {"FT": 0, "FTA": 0, "FGA": 0, "PTS": 0, "AST": 0, "TOV": 0}
    row_count = 0
    for path in pbp_files:
        game_id = path.stem.replace("_pbp", "")
        html = path.read_text(encoding="utf-8")
        rows = fqs.parse_pbp_quarters(
            html, "stockjo01", "John Stockton", game_id, 1996, None, "stockton_34_40"
        )
        for r in rows:
            for k in totals:
                totals[k] += int(r.get(k) or 0)
            row_count += 1

    print(f"\n{'=' * 60}")
    print(f"HTML SAMPLE PARSE  ({len(pbp_files)} PBP files, Stockton)")
    print(f"{'=' * 60}")
    print(f"Quarter rows produced: {row_count}")

    issues = 0
    if row_count == 0:
        print("*** ZERO QUARTER ROWS across all sample files — parser likely broken")
        issues += 1
        return issues

    for k, v in totals.items():
        print(f"  {k}: {v}")
    if totals["FGA"] == 0:
        print("*** FGA still 0 across all sample files — parser may still be broken")
        issues += 1
    if totals["PTS"] == 0 and totals["FTA"] == 0:
        print("*** PTS and FTA both 0 — free-throw and scoring regexes may be broken")
        issues += 1
    if totals["FTA"] > 0:
        print(f"  FT%: {totals['FT'] / totals['FTA']:.3f}")
    return issues


def main() -> int:
    """Run data-quality audit on all quarter_splits parquets.

    Returns:
        Exit code: 0 if clean, 1 if issues found.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", default=None, help="Single parquet path (default: all)")
    parser.add_argument(
        "--sample-html",
        type=int,
        default=0,
        metavar="N",
        help="Parse N cached PBP HTML files to verify parser output (default: 0 = skip)",
    )
    parser.add_argument(
        "--skip-classifier",
        action="store_true",
        help="Skip the classifier smoke test",
    )
    args = parser.parse_args()

    explicit_path = bool(args.parquet)
    if args.parquet:
        paths = [pathlib.Path(args.parquet)]
    else:
        paths = sorted(DATA_DIR.glob("quarter_splits_*.parquet"))

    if not paths:
        print("No quarter_splits_*.parquet files found in data/")
        return 1

    total_issues = 0
    for p in paths:
        total_issues += _audit_file(p, error_on_missing=explicit_path)

    classifier_failures = 0
    if not args.skip_classifier:
        classifier_failures = _smoke_test_classifier()

    html_issues = 0
    if args.sample_html > 0:
        html_issues = _sample_html_parse(args.sample_html)

    print(f"\n{'=' * 60}")
    if total_issues or classifier_failures or html_issues:
        print(
            f"AUDIT RESULT: {total_issues} parquet issue(s), "
            f"{classifier_failures} classifier failure(s), "
            f"{html_issues} HTML parse issue(s)"
        )
    else:
        print("AUDIT RESULT: clean")
    print(f"{'=' * 60}")
    return 1 if (total_issues or classifier_failures or html_issues) else 0


if __name__ == "__main__":
    sys.exit(main())
