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

# Zero-rate thresholds below 100% for columns where a partial regression is
# plausible (issue #72): a broken "makes 3-pt" branch drives FGA zero-rate to
# ~40–90% without ever reaching 100%, which the all-zero check misses.
_ZERO_PCT_MAX = {"FGA": 90.0, "PTS": 90.0}


def _check_invariants(df: pd.DataFrame) -> int:
    """Check row-level cross-column invariants (issue #72).

    Invariants:
        FT <= FTA               (can't make more free throws than attempted)
        PTS <= 3*FGA + FT       (max 3 points per field-goal attempt)
        0 <= TS_pct <= 1.5      (1.5 = mathematical max: a made 3 on one FGA
                                 gives 3 / (2*1); per-quarter rows can hit it)

    Args:
        df: Parquet contents under audit.

    Returns:
        Number of violated invariants (one per invariant, not per row).
    """
    checks: list[tuple[str, pd.Series]] = []
    if {"FT", "FTA"} <= set(df.columns):
        checks.append(("FT <= FTA", df["FT"] > df["FTA"]))
    if {"PTS", "FGA", "FT"} <= set(df.columns):
        checks.append(("PTS <= 3*FGA + FT", df["PTS"] > 3 * df["FGA"] + df["FT"]))
    if "TS_pct" in df.columns:
        ts = df["TS_pct"]
        checks.append(("0 <= TS_pct <= 1.5", (ts < 0) | (ts > 1.5)))

    issues = 0
    for name, violated in checks:
        count = int(violated.fillna(False).sum())
        if count:
            print(f"*** INVARIANT VIOLATION  {name}: {count} row(s)")
            issues += 1
    return issues


def _column_flag(
    col: str, null_pct: float, zero_pct: float, expected_all_null: set[str]
) -> tuple[str, int]:
    """Classify one column's null/zero rates into a display flag and issue count.

    Args:
        col: Column name.
        null_pct: Percent of null values (0–100).
        zero_pct: Percent of zero values among non-null (0–100, or NaN).
        expected_all_null: Columns where 100% null is expected.

    Returns:
        Tuple of (flag string for the report row, issue count 0 or 1).
    """
    if null_pct == 100:
        if col not in expected_all_null:
            return "*** UNEXPECTED ALL-NULL", 1
        return "(expected — PBP path only)", 0
    if zero_pct == 100:
        return "*** ALL ZERO", 1
    if col in _ZERO_PCT_MAX and zero_pct > _ZERO_PCT_MAX[col]:
        return f"*** ZERO RATE {zero_pct:.1f}% > {_ZERO_PCT_MAX[col]:.0f}% threshold", 1
    return "", 0


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

        flag, col_issues = _column_flag(col, null_pct, zero_pct, expected_all_null)
        issues += col_issues

        print(
            f"{col:<16} {null_pct:>6.1f}% {zero_pct:>6.1f}% {mean_v:>10.3f} {p50_v:>10.3f}  {flag}"
        )

    issues += _check_invariants(df)
    return issues


def _sample_triples(paths: list[pathlib.Path], n: int) -> pd.DataFrame:
    """Sample (player_id, player_name, game_id) triples from the audited parquets.

    Only PBP-derived rows (quarter != 'full') whose cached ``*_pbp.html`` exists
    are eligible — a box-fallback row has no PBP HTML to round-trip. The sample
    is deterministic and round-robins across players so every cohort's
    name-matching is exercised, not just Stockton's (issue #71).

    Args:
        paths: Parquet files under audit.
        n: Maximum number of triples to return.

    Returns:
        DataFrame with columns player_id, player_name, game_id, season,
        age_regime; at most n rows (may be empty).
    """
    cols = ["player_id", "player_name", "game_id", "season", "age_regime"]
    frames = []
    for p in paths:
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not {"player_id", "player_name", "game_id"} <= set(df.columns):
            continue
        if "quarter" in df.columns:
            df = df[df["quarter"].astype(str) != "full"]
        df = df.copy()
        if "season" not in df.columns:
            df["season"] = 0
        if "age_regime" not in df.columns:
            df["age_regime"] = "audit"
        frames.append(df[cols].drop_duplicates(subset=["player_id", "game_id"]))

    if not frames:
        return pd.DataFrame(columns=cols)

    triples = pd.concat(frames, ignore_index=True)
    triples = triples.drop_duplicates(subset=["player_id", "game_id"])
    triples = triples[triples["game_id"].map(lambda g: (HTML_CACHE / f"{g}_pbp.html").exists())]
    if triples.empty:
        return triples

    triples = triples.sort_values(["player_id", "game_id"])
    per_player = max(1, n // triples["player_id"].nunique())
    return triples.groupby("player_id", sort=True).head(per_player).head(n)


def _parse_sampled(sampled: pd.DataFrame) -> tuple[dict[str, int], int, list[tuple[str, str]]]:
    """Re-parse cached PBP HTML for each sampled (player, game) triple.

    Args:
        sampled: Output of _sample_triples.

    Returns:
        Tuple of (stat totals, quarter-row count, list of (player_name,
        game_id) pairs that produced zero rows — a name-matching/parser
        regression signal, since the parquet has PBP rows for those games).
    """
    import fetch_quarter_splits as fqs  # noqa: PLC0415

    totals: dict[str, int] = {"FT": 0, "FTA": 0, "FGA": 0, "PTS": 0, "AST": 0, "TOV": 0}
    row_count = 0
    zero_row_games: list[tuple[str, str]] = []
    for t in sampled.itertuples(index=False):
        html = (HTML_CACHE / f"{t.game_id}_pbp.html").read_text(encoding="utf-8")
        season = int(t.season) if pd.notna(t.season) else 0
        rows = fqs.parse_pbp_quarters(
            html, t.player_id, t.player_name, t.game_id, season, None, str(t.age_regime)
        )
        if not rows:
            zero_row_games.append((t.player_name, t.game_id))
        for r in rows:
            for k in totals:
                totals[k] += int(r.get(k) or 0)
            row_count += 1
    return totals, row_count, zero_row_games


def _sample_html_parse(n: int, paths: list[pathlib.Path]) -> int:
    """Round-trip-parse cached PBP HTML for players sampled from the audited parquets.

    Args:
        n: Number of cached files to parse.
        paths: Parquet files under audit — the sample is drawn from these so
            each audited player's own name is used for play-text matching.

    Returns:
        Number of issues found (0 = clean, >0 = issues).
    """
    sampled = _sample_triples(paths, n)
    if sampled.empty:
        print("\nNo cached PBP HTML matching the audited parquets — skipping HTML sample parse.")
        return 0

    totals, row_count, zero_row_games = _parse_sampled(sampled)
    players = sorted(sampled["player_name"].unique())
    print(f"\n{'=' * 60}")
    print(f"HTML SAMPLE PARSE  ({len(sampled)} PBP files, {len(players)} player(s))")
    print(f"Players: {', '.join(players)}")
    print(f"{'=' * 60}")
    print(f"Quarter rows produced: {row_count}")

    issues = 0
    for name, gid in zero_row_games:
        print(f"*** ZERO ROWS for {name} in {gid} — name matching or parser regression")
        issues += 1

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
        html_issues = _sample_html_parse(args.sample_html, paths)

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
