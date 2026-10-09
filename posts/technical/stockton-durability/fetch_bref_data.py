"""
fetch_bref_data.py — scrape BRef game logs for Stockton durability cohort.

Fetches one page per player-season; writes data/game_logs.parquet.
Run this before building the analysis notebook.

Rate-limited to ~4 sec/request.
Expected wall time: ~3 hours for full PG+PF cohort from scratch. Cache
skips players already present; re-runs are incremental.

Usage:
    python fetch_bref_data.py              # full cohort (PG + PF)
    python fetch_bref_data.py --player stockjo01  # single player
    python fetch_bref_data.py --cohort pg  # PG cohort only
    python fetch_bref_data.py --cohort pf  # PF cohort only
    python fetch_bref_data.py --summary    # print/save threshold table
    python fetch_bref_data.py --population-fetch  # fetch population cohort
    python fetch_bref_data.py --population-fetch --limit 5  # quick subset test
"""

import argparse
import logging
import pathlib
import time
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

DATA_DIR = pathlib.Path(__file__).parent / "data"
HTML_CACHE = DATA_DIR / "html_cache"
DATA_DIR.mkdir(exist_ok=True)
HTML_CACHE.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

RATE_LIMIT_SEC = 4  # stay well under BRef's soft limit

# BRef player IDs: first-5-lastname + first-2-firstname + 01
# Tuple: (initial, player_id, first_season, last_season, cohort_type)
COHORT: dict[str, tuple[str, str, int, int, str]] = {
    # PG cohort — selection: debuted 1984–2000, ≥600 career games, ≥28 MPG
    "John Stockton":   ("s", "stockjo01",  1985, 2003, "pg"),
    "Isiah Thomas":    ("t", "thomais01",  1982, 1994, "pg"),
    "Kevin Johnson":   ("j", "johnske02",  1988, 2000, "pg"),
    "Tim Hardaway":    ("h", "hardati01",  1990, 2003, "pg"),
    "Gary Payton":     ("p", "paytoga01",  1991, 2007, "pg"),
    "Mark Jackson":    ("j", "jacksma01",  1988, 2004, "pg"),
    "Terry Porter":    ("p", "portete01",  1986, 2003, "pg"),
    "Rod Strickland":  ("s", "stricro01",  1989, 2005, "pg"),
    "Muggsy Bogues":   ("b", "boguesmu01", 1988, 2001, "pg"),  # borderline MPG (~28)
    "Sherman Douglas": ("d", "douglsh01",  1990, 1999, "pg"),  # borderline MPG
    "Jason Kidd":      ("k", "kiddja01",   1995, 2013, "pg"),
    "Derek Harper":    ("h", "harped01",   1984, 1999, "pg"),
    "Mookie Blaylock": ("b", "blaylmo01",  1990, 2002, "pg"),
    "Kenny Anderson":  ("a", "anderke01",  1992, 2005, "pg"),
    "Steve Nash":      ("n", "nashst01",   1997, 2014, "pg"),
    # PF cohort — Diaw case study + 5 era comparators (verified BRef IDs, issue #20)
    "Boris Diaw":        ("d", "diawbo01",   2004, 2017, "pf"),
    "Dirk Nowitzki":     ("n", "nowitdi01",  1999, 2019, "pf"),
    "Carlos Boozer":     ("b", "boozeca01",  2003, 2015, "pf"),
    "Antawn Jamison":    ("j", "jamisna01",  1999, 2014, "pf"),
    "Shawn Marion":      ("m", "mariosh01",  2000, 2015, "pf"),
    "Rashard Lewis":     ("l", "lewisra02",  1999, 2009, "pf"),  # 02 not 01 — disambiguation
}

# Cohort selection thresholds (applied after scrape)
MIN_CAREER_GAMES = 600
MIN_CAREER_MPG   = 28.0

KEEP_COLS = ["Date", "Age", "Tm", "Opp", "GmSc", "MP",
             "FG", "FGA", "3P", "3PA", "FT", "FTA",
             "AST", "TOV", "PTS", "GS"]


def parse_mp_seconds(mp_str: str) -> float | None:
    """'34:21' → 34.35. Returns None for non-playing rows."""
    if not isinstance(mp_str, str) or ":" not in mp_str:
        return None
    try:
        mins, secs = mp_str.split(":")
        return int(mins) + int(secs) / 60
    except ValueError:
        return None


def _get_html(url: str, cache_key: str, cache_subdir: str = "") -> str | None:
    """Return HTML for url, reading from disk cache when available."""
    cache_dir = HTML_CACHE / cache_subdir if cache_subdir else HTML_CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{cache_key}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    resp = requests.get(url, headers={"User-Agent": "stockton-research/1.0"}, timeout=20)
    if resp.status_code != 200:
        logger.warning("HTTP %s for %s", resp.status_code, url)
        return None
    cache_path.write_text(resp.text, encoding="utf-8")
    time.sleep(RATE_LIMIT_SEC)
    return resp.text


def fetch_gamelog(initial: str, player_id: str, season: int) -> pd.DataFrame | None:
    """Fetch one player-season game log. Returns None on HTTP error or missing table."""
    url = (f"https://www.basketball-reference.com/players/"
           f"{initial}/{player_id}/gamelog/{season}/")
    html = _get_html(url, f"{player_id}_{season}")
    if html is None:
        return None

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "player_game_log_reg"})
    if table is None:
        return None

    df = pd.read_html(StringIO(str(table)))[0]

    # Drop mid-table repeated header rows
    df = df[df["Rk"] != "Rk"].copy()
    df = df[pd.to_numeric(df["Rk"], errors="coerce").notna()].copy()

    df["player_id"] = player_id
    df["season"] = season

    # Active = MP is a parseable time string
    df["mp_float"] = df["MP"].apply(parse_mp_seconds)
    df["active"] = df["mp_float"].notna().astype(int)

    # Numeric coercions for stat columns
    for col in ["FG", "FGA", "3P", "3PA", "FT", "FTA", "AST", "TOV", "PTS"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Parse date; derive rest days
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.sort_values("Date").reset_index(drop=True)
    df["rest_days"] = df["Date"].diff().dt.days.fillna(3)   # season opener → 3
    df["b2b"] = (df["rest_days"] == 1).astype(int)

    return df[df["active"] == 1].copy()   # drop DNPs here; keep for counting separately


def load_existing() -> pd.DataFrame | None:
    out = DATA_DIR / "game_logs.parquet"
    if out.exists():
        return pd.read_parquet(out)
    return None


def save(df: pd.DataFrame) -> None:
    df.to_parquet(DATA_DIR / "game_logs.parquet", index=False)
    print(f"  → saved {len(df):,} rows to data/game_logs.parquet")


def fetch_cohort(
    player_filter: str | None = None,
    cohort_filter: str | None = None,
) -> None:
    """Fetch game logs for all cohort players not already in the parquet cache."""
    existing = load_existing()
    done_keys: set[tuple[str, int]] = set()
    if existing is not None:
        done_keys = set(zip(existing["player_id"], existing["season"]))
        logger.info("Cache: %s rows, %d (player, season) pairs already fetched.",
                    f"{len(existing):,}", len(done_keys))

    all_frames = [existing] if existing is not None else []
    notes: list[str] = []

    for name, (initial, pid, first, last, cohort_type) in COHORT.items():
        if player_filter and pid != player_filter:
            continue
        if cohort_filter and cohort_type != cohort_filter:
            continue
        logger.info("%s  (%s)  %d–%d:", name, pid, first, last)
        for season in range(first, last + 1):
            if (pid, season) in done_keys:
                continue
            logger.info("  %d...", season)
            df = fetch_gamelog(initial, pid, season)
            if df is not None:
                df["player_name"] = name
                df["cohort"] = cohort_type
                all_frames.append(df)
                logger.info("  %d active games", len(df))
            else:
                msg = f"{name} ({pid}) season {season}: no table returned"
                logger.warning(msg)
                notes.append(msg)

    if notes:
        notes_path = DATA_DIR / "fetch_notes.md"
        existing_notes = notes_path.read_text() if notes_path.exists() else ""
        notes_path.write_text(existing_notes + "\n".join(notes) + "\n")
        logger.info("Wrote %d fetch notes to data/fetch_notes.md", len(notes))

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        save(combined)
    else:
        logger.info("Nothing new fetched.")


def cohort_summary(save_csv: bool = True) -> pd.DataFrame:
    """Print career games and MPG to check selection thresholds; save cohort_summary.csv."""
    existing = load_existing()
    if existing is None:
        logger.error("No data yet — run fetch first.")
        return pd.DataFrame()

    existing["mp_float"] = existing["MP"].apply(parse_mp_seconds)

    # Build cohort type lookup from COHORT dict
    cohort_lookup = {pid: ctype for _, (_, pid, _, _, ctype) in COHORT.items()}
    # Fallback for players in parquet but not in COHORT dict (e.g. population)
    existing["cohort"] = existing["player_id"].map(cohort_lookup).fillna("population")

    summary = (existing.groupby(["player_name", "player_id", "cohort"])
               .agg(career_games=("Date", "count"),
                    career_mpg=("mp_float", "mean"))
               .reset_index()
               .sort_values("career_games", ascending=False))
    summary["meets_threshold"] = (
        (summary["career_games"] >= MIN_CAREER_GAMES) &
        (summary["career_mpg"] >= MIN_CAREER_MPG)
    )

    print(summary.to_string(index=False))

    # Document borderline cases
    borderline = summary[
        (summary["career_games"] >= MIN_CAREER_GAMES) &
        (summary["career_mpg"] < MIN_CAREER_MPG)
    ]
    if not borderline.empty:
        logger.info("\nBorderline (games OK, MPG below %.1f):", MIN_CAREER_MPG)
        for _, row in borderline.iterrows():
            logger.info("  %s (%s): %.1f MPG — included as borderline; "
                        "MPG below threshold noted in post Limitations",
                        row["player_name"], row["player_id"], row["career_mpg"])

    if save_csv:
        out = DATA_DIR / "cohort_summary.csv"
        summary.to_csv(out, index=False)
        logger.info("Saved cohort_summary.csv (%d players)", len(summary))

    # Assert Stockton row count is correct
    stockton_rows = existing[existing["player_id"] == "stockjo01"]
    assert len(stockton_rows) == 1504, (
        f"Expected 1504 Stockton rows, got {len(stockton_rows)}"
    )

    return summary


def fetch_population_cohort(limit: int | None = None) -> None:
    """Fetch game logs for population cohort players listed in data/population_cohort.csv."""
    pop_csv = DATA_DIR / "population_cohort.csv"
    if not pop_csv.exists():
        logger.error("data/population_cohort.csv not found — run build_population_cohort() first.")
        return

    pop = pd.read_csv(pop_csv)
    logger.info("Population cohort: %d candidates", len(pop))

    existing = load_existing()
    done_ids: set[str] = set()
    if existing is not None:
        done_ids = set(existing["player_id"].unique())
        logger.info("Already fetched: %d player_ids", len(done_ids))

    players = [row for _, row in pop.iterrows() if row["player_id"] not in done_ids]
    if limit:
        players = players[:limit]
    logger.info("Fetching %d new players", len(players))

    all_frames = [existing] if existing is not None else []
    for row in players:
        pid = row["player_id"]
        initial = row["initial"]
        first = int(row["debut_year"]) + 1  # BRef season = year+1 for rookie year
        last = int(row["final_year"])
        name = row["player_name"]
        logger.info("%s (%s) %d–%d", name, pid, first, last)
        for season in range(first, last + 1):
            df = fetch_gamelog(initial, pid, season)
            if df is not None:
                df["player_name"] = name
                df["cohort"] = "population"
                all_frames.append(df)

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        save(combined)


def build_population_cohort() -> None:
    """Scrape BRef player index (A–Z) and build data/population_cohort.csv.

    Scope: guards (G, PG, SG) who debuted 1980–2010;
           forwards (F, PF, SF) who debuted 1995–2010.
    Writes population_cohort.csv with columns:
        player_name, player_id, initial, position, debut_year, final_year, era
    """
    import re
    import string

    rows = []
    for letter in string.ascii_lowercase:
        url = f"https://www.basketball-reference.com/players/{letter}/"
        html = _get_html(url, f"_index_{letter}", cache_subdir="index")
        if html is None:
            continue
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", {"id": "players"})
        if table is None:
            continue
        try:
            df = pd.read_html(StringIO(str(table)))[0]
        except Exception:
            continue

        # Normalise column names (BRef table header varies by letter page)
        df.columns = [str(c).strip() for c in df.columns]
        if "Player" not in df.columns:
            continue

        for _, r in df.iterrows():
            name = str(r.get("Player", "")).strip()
            pos = str(r.get("Pos", "")).strip()
            from_yr = r.get("From", None)
            to_yr = r.get("To", None)
            if not name or not pos:
                continue
            try:
                debut = int(from_yr)
                final = int(to_yr)
            except (ValueError, TypeError):
                continue

            is_guard = any(p in pos for p in ("G", "PG", "SG"))
            is_forward = any(p in pos for p in ("F", "PF", "SF"))
            guard_era = 1980 <= debut <= 2010
            forward_era = 1995 <= debut <= 2010

            if not ((is_guard and guard_era) or (is_forward and forward_era)):
                continue

            # Extract player_id from the href
            href = ""
            for tag in soup.find_all("a", href=re.compile(rf"/players/{letter}/\w+\.html")):
                if tag.get_text(strip=True) == name:
                    href = tag["href"]
                    break
            if not href:
                continue
            pid = href.split("/")[-1].replace(".html", "")
            era = f"{(debut // 10) * 10}s"
            rows.append({
                "player_name": name,
                "player_id": pid,
                "initial": letter,
                "position": pos,
                "debut_year": debut,
                "final_year": final,
                "era": era,
            })

    pop = pd.DataFrame(rows).drop_duplicates("player_id")
    logger.info("Population candidates: %d (before career threshold)", len(pop))
    pop.to_csv(DATA_DIR / "population_cohort.csv", index=False)
    logger.info("Saved data/population_cohort.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", default=None,
                        help="BRef player_id to fetch only one player")
    parser.add_argument("--cohort", default=None, choices=["pg", "pf"],
                        help="Restrict fetch to one cohort type")
    parser.add_argument("--summary", action="store_true",
                        help="Print cohort summary and save cohort_summary.csv")
    parser.add_argument("--population-fetch", action="store_true",
                        help="Fetch population cohort from data/population_cohort.csv")
    parser.add_argument("--build-population", action="store_true",
                        help="Scrape BRef index to build data/population_cohort.csv")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of players for --population-fetch (test mode)")
    args = parser.parse_args()

    if args.summary:
        cohort_summary()
    elif args.build_population:
        build_population_cohort()
    elif args.population_fetch:
        fetch_population_cohort(limit=args.limit)
    else:
        fetch_cohort(player_filter=args.player, cohort_filter=args.cohort)
