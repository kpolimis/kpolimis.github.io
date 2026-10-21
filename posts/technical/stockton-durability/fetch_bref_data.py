"""fetch_bref_data.py — scrape BRef game logs for Stockton durability cohort.

Fetches one page per player-season; writes data/game_logs.parquet.
Run this before building the analysis notebook.

Rate-limited to 10-15 sec/request with a 5-minute cooldown every 20 pages.
Expected wall time: ~6-8 hours for full PG+PF cohort from scratch (~330 pages).
Cache skips players already present; re-runs are incremental.

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
import random
import re
import string
import time
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

DATA_DIR = pathlib.Path(__file__).parent / "data"
HTML_CACHE = DATA_DIR / "html_cache"

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

RATE_LIMIT_SEC = (
    10  # base delay between requests — conservative to stay under BRef hourly aggregate
)
RATE_LIMIT_JITTER = (
    5  # add uniform random [0, JITTER) seconds — looks human, avoids mechanical regularity
)
SESSION_COOLDOWN_PAGES = 20  # sleep SESSION_COOLDOWN_SEC after every N successful fetches
SESSION_COOLDOWN_SEC = 300  # 5-minute break every 20 pages (~200 pages/hour cap)
_MAX_BACKOFF_SEC = 600  # cap for both 429 and 403 exponential backoff

# IP-level block state: when BRef 429s/403s, ALL requests are blocked until this timestamp clears.
_ip_blocked_until: float = 0.0

# BRef player IDs: first-5-lastname + first-2-firstname + 01
# Tuple: (initial, player_id, first_season, last_season, cohort_type)
COHORT: dict[str, tuple[str, str, int, int, str]] = {
    # PG cohort — selection: debuted 1984–2000, ≥600 career games, ≥28 MPG
    "John Stockton": ("s", "stockjo01", 1985, 2003, "pg"),
    "Isiah Thomas": ("t", "thomais01", 1982, 1994, "pg"),
    "Kevin Johnson": ("j", "johnske02", 1988, 2000, "pg"),
    "Tim Hardaway": ("h", "hardati01", 1990, 2003, "pg"),
    "Gary Payton": ("p", "paytoga01", 1991, 2007, "pg"),
    "Mark Jackson": ("j", "jacksma01", 1988, 2004, "pg"),
    "Terry Porter": ("p", "portete01", 1986, 2003, "pg"),
    "Rod Strickland": ("s", "stricro02", 1989, 2005, "pg"),
    "Muggsy Bogues": ("b", "boguemu01", 1988, 2001, "pg"),  # borderline MPG (~28)
    "Sherman Douglas": ("d", "douglsh01", 1990, 1999, "pg"),  # borderline MPG
    "Jason Kidd": ("k", "kiddja01", 1995, 2013, "pg"),
    "Derek Harper": ("h", "harpede01", 1984, 1999, "pg"),  # de not d — harpede01 confirmed
    "Mookie Blaylock": ("b", "blaylmo01", 1990, 2002, "pg"),
    "Kenny Anderson": ("a", "anderke01", 1992, 2005, "pg"),
    "Steve Nash": ("n", "nashst01", 1997, 2014, "pg"),
    # PF cohort — Diaw case study + 5 era comparators (verified BRef IDs, issue #20)
    "Boris Diaw": ("d", "diawbo01", 2004, 2017, "pf"),
    "Dirk Nowitzki": ("n", "nowitdi01", 1999, 2019, "pf"),
    "Carlos Boozer": ("b", "boozeca01", 2003, 2015, "pf"),
    "Antawn Jamison": ("j", "jamisan01", 1999, 2014, "pf"),  # jamisan01 not jamisna01 (an≠na)
    "Shawn Marion": ("m", "mariosh01", 2000, 2015, "pf"),
    "Rashard Lewis": ("l", "lewisra02", 1999, 2009, "pf"),  # 02 not 01 — disambiguation
}

# Cohort selection thresholds (applied after scrape)
MIN_CAREER_GAMES = 600
MIN_CAREER_MPG = 28.0

KEEP_COLS = [
    "Date",
    "Age",
    "Tm",
    "Opp",
    "GmSc",
    "MP",
    "FG",
    "FGA",
    "3P",
    "3PA",
    "FT",
    "FTA",
    "AST",
    "TOV",
    "PTS",
    "GS",
]


def _ensure_dirs() -> None:
    """Create DATA_DIR and HTML_CACHE on disk. Called once from main(), not at import time."""
    DATA_DIR.mkdir(exist_ok=True)
    HTML_CACHE.mkdir(exist_ok=True)


def parse_mp_seconds(mp_str: str) -> float | None:
    """Convert a BRef minutes string to a float.

    Args:
        mp_str: Minutes string in "MM:SS" format (e.g. "34:21").

    Returns:
        Decimal minutes (e.g. 34.35), or None for non-playing rows.
    """
    if not isinstance(mp_str, str) or ":" not in mp_str:
        return None
    try:
        mins, secs = mp_str.split(":")
        return int(mins) + int(secs) / 60
    except ValueError:
        return None


_session_page_count: int = 0


def _get_html(url: str, cache_key: str, cache_subdir: str = "") -> str | None:
    """Return HTML for a URL, reading from disk cache when available.

    Args:
        url: Full URL to fetch.
        cache_key: Filename stem for the cached HTML file (no extension).
        cache_subdir: Optional subdirectory under HTML_CACHE for this cache entry.

    Returns:
        HTML string on success, or None on persistent HTTP error.
    """
    global _ip_blocked_until, _session_page_count

    cache_dir = HTML_CACHE / cache_subdir if cache_subdir else HTML_CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{cache_key}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    # Respect IP-level block before making any new request.
    now = time.time()
    if _ip_blocked_until > now:
        wait = _ip_blocked_until - now
        logger.warning("IP block active — sleeping %.0fs before next request", wait)
        time.sleep(wait)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; stockton-research/1.0; +https://kpolimis.github.io/)"
        )
    }
    for attempt in range(4):
        try:
            resp = requests.get(url, headers=headers, timeout=20)
        except requests.RequestException as exc:
            wait = min(15 * (2**attempt), _MAX_BACKOFF_SEC)
            logger.warning("Request error for %s: %s — retrying in %ds (attempt %d/4)", url, exc, wait, attempt + 1)
            time.sleep(wait)
            continue
        if resp.status_code == 200:
            cache_path.write_text(resp.text, encoding="utf-8")
            _session_page_count += 1
            # Session-level cooldown every N pages to stay under hourly aggregate limit.
            if _session_page_count % SESSION_COOLDOWN_PAGES == 0:
                logger.info(
                    "Session cooldown after %d pages — sleeping %ds",
                    _session_page_count,
                    SESSION_COOLDOWN_SEC,
                )
                time.sleep(SESSION_COOLDOWN_SEC)
            else:
                time.sleep(RATE_LIMIT_SEC + random.uniform(0, RATE_LIMIT_JITTER))
            return resp.text
        if resp.status_code == 429:
            # 429 = rate limit. Honor Retry-After if present; otherwise exponential backoff.
            retry_after = resp.headers.get("Retry-After")
            raw_wait = (
                int(retry_after) if retry_after and retry_after.isdigit() else 120 * (2**attempt)
            )  # 120s, 240s, 480s, 960s before cap
            wait = min(raw_wait, _MAX_BACKOFF_SEC)
            _ip_blocked_until = time.time() + wait
            logger.warning(
                "HTTP 429 for %s — IP blocked, sleeping %ds (attempt %d/4)", url, wait, attempt + 1
            )
            time.sleep(wait)
        elif resp.status_code == 403:
            # 403 = temporary IP block. Retry with exponential backoff before giving up.
            wait = min(60 * (2**attempt), _MAX_BACKOFF_SEC)  # 60s, 120s, 240s, 480s
            _ip_blocked_until = time.time() + wait
            logger.warning(
                "HTTP 403 for %s — IP block, sleeping %ds (attempt %d/4)", url, wait, attempt + 1
            )
            time.sleep(wait)
        else:
            logger.warning("HTTP %s for %s", resp.status_code, url)
            return None
    logger.warning("HTTP 429/403 persisted after retries for %s", url)
    return None


def fetch_gamelog(initial: str, player_id: str, season: int) -> pd.DataFrame | None:
    """Fetch one player-season game log from BRef.

    Args:
        initial: First letter of the player's last name (BRef URL key).
        player_id: BRef player identifier (e.g. "stockjo01").
        season: Season-ending year (e.g. 1998 for the 1997–98 season).

    Returns:
        DataFrame of active game rows for the season, or None on HTTP error
        or missing table.
    """
    url = f"https://www.basketball-reference.com/players/{initial}/{player_id}/gamelog/{season}/"
    html = _get_html(url, f"{player_id}_{season}")
    if html is None:
        return None

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "player_game_log_reg"})
    if table is None:
        return None

    df = pd.read_html(StringIO(str(table)))[0]

    # Drop mid-table repeated header rows (some pages omit the Rk column)
    if "Rk" in df.columns:
        df = df[df["Rk"] != "Rk"].copy()
        df = df[pd.to_numeric(df["Rk"], errors="coerce").notna()].copy()
        df["Rk"] = df["Rk"].astype(str)  # keep as string to match existing parquet schema
    else:
        df["Rk"] = pd.array([""] * len(df), dtype="object")

    df["player_id"] = player_id
    df["season"] = season

    if "MP" not in df.columns:
        return None  # no minutes column — not a usable game log page

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
    df["rest_days"] = df["Date"].diff().dt.days.fillna(3)  # season opener → 3
    df["b2b"] = (df["rest_days"] == 1).astype(int)

    return df[df["active"] == 1].copy()  # drop DNPs here; keep for counting separately


def load_existing() -> pd.DataFrame | None:
    """Return existing game_logs.parquet as a DataFrame, or None if absent."""
    out = DATA_DIR / "game_logs.parquet"
    if out.exists():
        return pd.read_parquet(out)
    return None


def save(df: pd.DataFrame) -> None:
    """Write parquet, merging with any rows another process added since we loaded."""
    out = DATA_DIR / "game_logs.parquet"
    lock_path = DATA_DIR / "game_logs.parquet.lock"
    import fcntl

    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            if out.exists():
                on_disk = pd.read_parquet(out)
                new_keys = set(zip(df["player_id"], df["season"], strict=False))
                on_disk_keys = set(zip(on_disk["player_id"], on_disk["season"], strict=False))
                truly_new = new_keys - on_disk_keys
                if truly_new:
                    new_rows = df[
                        df.apply(lambda r: (r["player_id"], r["season"]) in truly_new, axis=1)
                    ]
                    df = pd.concat([on_disk, new_rows], ignore_index=True)
                else:
                    df = on_disk
            # Normalize all object columns to string — BRef HTML parses inconsistently
            # across player pages (some numeric, some string, some NaN), causing
            # PyArrow type errors on concat. String is safe for all BRef text columns.
            for col in df.select_dtypes(include="object").columns:
                df[col] = df[col].astype(str).replace("nan", "")
            df.to_parquet(out, index=False)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
    logger.info("Saved %d rows to data/game_logs.parquet", len(df))


def _backfill_cohort_column(df: pd.DataFrame, cohort_lookup: dict) -> pd.DataFrame:
    """Ensure 'cohort' column exists; backfill from lookup, defaulting to 'population'."""
    if "cohort" not in df.columns:
        df["cohort"] = df["player_id"].map(cohort_lookup).fillna("population")
    else:
        df["cohort"] = df["player_id"].map(cohort_lookup).fillna(df["cohort"])
    return df


def fetch_cohort(
    player_filter: str | None = None,
    cohort_filter: str | None = None,
) -> None:
    """Fetch game logs for all cohort players not already in the parquet cache.

    Args:
        player_filter: If set, fetch only this BRef player_id.
        cohort_filter: If set, restrict to "pg" or "pf" cohort type.
    """
    existing = load_existing()
    done_keys: set[tuple[str, int]] = set()
    if existing is not None:
        cohort_lookup = {pid: ctype for _, (_, pid, _, _, ctype) in COHORT.items()}
        existing = _backfill_cohort_column(existing, cohort_lookup)
        done_keys = set(zip(existing["player_id"], existing["season"], strict=False))
        logger.info(
            "Cache: %s rows, %d (player, season) pairs already fetched.",
            f"{len(existing):,}",
            len(done_keys),
        )

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
    """Print career games and MPG to check selection thresholds; save cohort_summary.csv.

    Args:
        save_csv: Whether to write cohort_summary.csv to DATA_DIR.

    Returns:
        Summary DataFrame with career_games, career_mpg, and meets_threshold columns.
    """
    existing = load_existing()
    if existing is None:
        logger.error("No data yet — run fetch first.")
        return pd.DataFrame()

    existing["mp_float"] = existing["MP"].apply(parse_mp_seconds)

    # Build cohort type lookup from COHORT dict
    cohort_lookup = {pid: ctype for _, (_, pid, _, _, ctype) in COHORT.items()}
    # Fallback for players in parquet but not in COHORT dict (e.g. population)
    existing["cohort"] = existing["player_id"].map(cohort_lookup).fillna("population")

    summary = (
        existing.groupby(["player_name", "player_id", "cohort"])
        .agg(career_games=("Date", "count"), career_mpg=("mp_float", "mean"))
        .reset_index()
        .sort_values("career_games", ascending=False)
    )
    summary["meets_threshold"] = (summary["career_games"] >= MIN_CAREER_GAMES) & (
        summary["career_mpg"] >= MIN_CAREER_MPG
    )

    logger.info("Cohort threshold summary:\n%s", summary.to_string(index=False))

    # Document borderline cases
    borderline = summary[
        (summary["career_games"] >= MIN_CAREER_GAMES) & (summary["career_mpg"] < MIN_CAREER_MPG)
    ]
    if not borderline.empty:
        logger.info("\nBorderline (games OK, MPG below %.1f):", MIN_CAREER_MPG)
        for _, row in borderline.iterrows():
            logger.info(
                "  %s (%s): %.1f MPG — included as borderline; "
                "MPG below threshold noted in post Limitations",
                row["player_name"],
                row["player_id"],
                row["career_mpg"],
            )

    if save_csv:
        out = DATA_DIR / "cohort_summary.csv"
        summary.to_csv(out, index=False)
        logger.info("Saved cohort_summary.csv (%d players)", len(summary))

    # Assert Stockton row count is correct
    stockton_rows = existing[existing["player_id"] == "stockjo01"]
    assert len(stockton_rows) == 1504, f"Expected 1504 Stockton rows, got {len(stockton_rows)}"

    return summary


def fetch_population_cohort(limit: int | None = None) -> None:
    """Fetch game logs for population cohort players listed in data/population_cohort.csv.

    Args:
        limit: If set, fetch at most this many new players (for testing).
    """
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
        first = int(
            row["debut_year"]
        )  # BRef season = season-ending year, debut_year already correct
        last = int(row["final_year"])
        name = row["player_name"]
        logger.info("%s (%s) %d–%d", name, pid, first, last)
        player_frames = []
        for season in range(first, last + 1):
            df = fetch_gamelog(initial, pid, season)
            if df is not None:
                df["player_name"] = name
                df["cohort"] = "population"
                player_frames.append(df)
        if player_frames:
            all_frames.extend(player_frames)
            save(pd.concat(all_frames, ignore_index=True))

    if not all_frames:
        logger.warning("No data fetched.")


def _parse_player_row(
    a_tag,
    tr,
    letter: str,
    link_re,
) -> dict | None:
    """Parse a single BRef index table row into a player dict.

    Args:
        a_tag: BeautifulSoup anchor tag inside the player <th> cell.
        tr: BeautifulSoup <tr> tag for this row.
        letter: Alphabet letter for this index page (used as initial).
        link_re: Compiled regex to extract player_id from the anchor href.

    Returns:
        Player dict with keys (player_name, player_id, initial, position,
        debut_year, final_year, era), or None if the row is invalid or
        outside the modern-era guard/forward/center scope.
    """
    m = link_re.search(a_tag.get("href", ""))
    if not m:
        return None
    pid = m.group(1)
    # Strip HOF asterisk from display name (BRef marks HOFers "Name*")
    name = a_tag.get_text(strip=True).rstrip("*")

    def _td(stat: str, _tr=tr) -> str:
        tag = _tr.find("td", {"data-stat": stat})
        return tag.get_text(strip=True) if tag else ""

    pos = _td("pos")
    try:
        debut = int(_td("year_min"))
        final = int(_td("year_max"))
    except (ValueError, TypeError):
        return None
    if not name or not pos:
        return None

    pos_parts = set(pos.replace("-", " ").split())
    is_guard = bool(pos_parts & {"G", "PG", "SG"})
    is_forward = bool(pos_parts & {"F", "PF", "SF"})
    is_center = bool(pos_parts & {"C"})
    modern_era = 1980 <= debut <= 2010

    if not ((is_guard or is_forward or is_center) and modern_era):
        return None

    era = f"{(debut // 10) * 10}s"
    return {
        "player_name": name,
        "player_id": pid,
        "initial": letter,
        "position": pos,
        "debut_year": debut,
        "final_year": final,
        "era": era,
    }


def _scrape_letter_page(letter: str) -> list[dict]:
    """Fetch and parse one BRef A–Z player index page.

    Args:
        letter: Single lowercase letter for the BRef player index URL.

    Returns:
        List of player dicts for players on this page that meet era/position
        scope (modern era guards, forwards, centers). Empty list on HTTP
        error or missing table.
    """
    url = f"https://www.basketball-reference.com/players/{letter}/"
    html = _get_html(url, f"_index_{letter}", cache_subdir="index")
    if html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "players"})
    if table is None:
        return []
    try:
        df = pd.read_html(StringIO(str(table)))[0]
    except Exception:
        return []

    # Normalise column names (BRef table header varies by letter page)
    df.columns = [str(c).strip() for c in df.columns]
    if "Player" not in df.columns:
        return []

    # Row-aligned extraction: get pid from each row's own <th><a> tag.
    # Avoids name-collision clobbering and HOF-asterisk misses from a shared dict.
    link_re = re.compile(rf"/players/{letter}/(\w+)\.html")
    tbody = table.find("tbody") or table
    players = []
    for tr in tbody.find_all("tr"):
        th = tr.find("th", {"data-stat": "player"})
        if th is None:
            continue
        a = th.find("a")
        if a is None:
            continue
        row = _parse_player_row(a, tr, letter, link_re)
        if row is not None:
            players.append(row)
    return players


def build_population_cohort() -> None:
    """Scrape BRef player index (A–Z) and build data/population_cohort.csv.

    Scope: guards (G, PG, SG), forwards (F, PF, SF), and centers (C, C-F, F-C)
           who debuted 1980–2010 (modern era: post-merger, post-3-point line).
    Writes population_cohort.csv with columns:
        player_name, player_id, initial, position, debut_year, final_year, era
    """
    rows = []
    for letter in string.ascii_lowercase:
        rows.extend(_scrape_letter_page(letter))

    pop = pd.DataFrame(rows)
    dupes = pop[pop.duplicated("player_id", keep=False)]
    assert dupes.empty, f"Duplicate player_ids after rebuild — bug: {dupes['player_id'].tolist()}"
    logger.info("Population candidates: %d (before career threshold)", len(pop))
    pop.to_csv(DATA_DIR / "population_cohort.csv", index=False)
    logger.info("Saved data/population_cohort.csv")


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate fetch or analysis function."""
    _ensure_dirs()

    parser = argparse.ArgumentParser()
    parser.add_argument("--player", default=None, help="BRef player_id to fetch only one player")
    parser.add_argument(
        "--cohort", default=None, choices=["pg", "pf"], help="Restrict fetch to one cohort type"
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print cohort summary and save cohort_summary.csv"
    )
    parser.add_argument(
        "--population-fetch",
        action="store_true",
        help="Fetch population cohort from data/population_cohort.csv",
    )
    parser.add_argument(
        "--build-population",
        action="store_true",
        help="Scrape BRef index to build data/population_cohort.csv",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of players for --population-fetch (test mode)",
    )
    args = parser.parse_args()

    if args.summary:
        cohort_summary()
    elif args.build_population:
        build_population_cohort()
    elif args.population_fetch:
        fetch_population_cohort(limit=args.limit)
    else:
        fetch_cohort(player_filter=args.player, cohort_filter=args.cohort)


if __name__ == "__main__":
    main()
