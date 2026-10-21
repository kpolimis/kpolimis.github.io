r"""fetch_season_splits.py — scrape BRef season-level splits pages (E7+ population).

For each population player with ≥400 career game rows in game_logs.parquet,
fetch the season splits page for every career season and store all split
tables in long format in data/season_splits.parquet.

URL: https://www.basketball-reference.com/players/{letter}/{player_id}/splits/{season}/

Each page carries ONE table (id="splits") whose sections are delimited by the
`split_id` header cell: Place, All-Star, Result, Month, Day, Role, Minutes,
Rest, Conference, Division, Opponent, plus a leading Total row.

NOTE: BRef season splits pages do NOT include By Quarter / By Half /
Score Margin sections (verified against 1997 and 2013 pages, including
commented-out HTML blocks). Quarter-level data exists only in play-by-play
(see fetch_quarter_splits.py). split_type values written here:
    total | location | allstar | result | month | day | role | minutes |
    rest | conference | division | opponent

Output schema (long format, one row per split value per player-season):
    player_id, player_name, season, split_type, split_value,
    G, MP, FG, FGA, 3P, 3PA, FT, FTA, PTS

Usage:
    conda run -n blog python fetch_season_splits.py                     # all 738 players
    conda run -n blog python fetch_season_splits.py --player stockjo01  # single player
    conda run -n blog python fetch_season_splits.py --limit 10          # first N players
"""

import argparse
import logging
import pathlib
import random
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

DATA_DIR = pathlib.Path(__file__).parent / "data"
HTML_CACHE_SPLITS = DATA_DIR / "html_cache" / "season_splits"
DATA_DIR.mkdir(exist_ok=True)
HTML_CACHE_SPLITS.mkdir(parents=True, exist_ok=True)

OUTPUT_PARQUET = DATA_DIR / "season_splits.parquet"

MIN_CAREER_GAMES = 400  # eligibility threshold on active game rows in game_logs.parquet

RATE_LIMIT_SEC = 4  # base delay between requests
RATE_LIMIT_JITTER = 2  # add uniform random [0, JITTER) seconds
SESSION_COOLDOWN_PAGES = 40  # pause after every N successful fetches
SESSION_COOLDOWN_SEC = 120
MAX_RETRIES = 5  # attempts on Timeout / ConnectionError
RETRY_BACKOFF_BASE = 15  # wait 15 * 2**attempt seconds between retries

# IP-level block state: when BRef 429s, ALL requests wait until this timestamp clears.
_ip_blocked_until: float = 0.0
_session_page_count: int = 0

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# BRef `split_id` section label → our split_type tag.
# (Season splits pages carry no Quarter/Half/Margin sections — PBP only.)
SPLIT_TYPE_MAP = {
    "": "total",  # unlabeled leading section (split_value == "Total")
    "place": "location",
    "all-star": "allstar",
    "result": "result",
    "month": "month",
    "day": "day",
    "role": "role",
    "minutes": "minutes",
    "rest": "rest",
    "conference": "conference",
    "division": "division",
    "opponent": "opponent",
}

# data-stat attribute → output column
STAT_COLS = {
    "g": "G",
    "mp": "MP",
    "fg": "FG",
    "fga": "FGA",
    "fg3": "3P",
    "fg3a": "3PA",
    "ft": "FT",
    "fta": "FTA",
    "pts": "PTS",
}


class SkipPlayerSeason(Exception):
    """Raised when a page persistently fails; caller skips this player-season."""


def _get_html(player_id: str, season: int) -> str | None:
    """Return splits-page HTML, reading from disk cache when available.

    Returns None on 404/403/non-retryable HTTP errors.
    Raises SkipPlayerSeason after MAX_RETRIES Timeout/ConnectionError failures.
    """
    global _ip_blocked_until, _session_page_count

    cache_path = HTML_CACHE_SPLITS / f"{player_id}_{season}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    letter = player_id[0]
    url = f"https://www.basketball-reference.com/players/{letter}/{player_id}/splits/{season}/"

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
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=20)
        except (requests.Timeout, requests.ConnectionError) as exc:
            wait = RETRY_BACKOFF_BASE * (2**attempt)  # 15, 30, 60, 120, 240
            logger.warning(
                "%s for %s — retrying in %ds (attempt %d/%d)",
                type(exc).__name__,
                url,
                wait,
                attempt + 1,
                MAX_RETRIES,
            )
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            cache_path.write_text(resp.text, encoding="utf-8")
            _session_page_count += 1
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
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else 120 * (2**attempt)
            _ip_blocked_until = time.time() + wait
            logger.warning(
                "HTTP 429 for %s — IP blocked, sleeping %ds (attempt %d/%d)",
                url,
                wait,
                attempt + 1,
                MAX_RETRIES,
            )
            time.sleep(wait)
        elif resp.status_code == 403:
            logger.warning("HTTP 403 for %s — skipping (no VPN rotation on local IP)", url)
            return None
        elif resp.status_code == 404:
            return None  # season page absent (e.g. missed full season) — expected
        else:
            logger.warning("HTTP %d for %s", resp.status_code, url)
            return None

    raise SkipPlayerSeason(f"persistent failure for {url}")


def parse_splits_page(html: str, player_id: str, player_name: str, season: int) -> list[dict]:
    """Parse the single `splits` table into long-format rows.

    Sections are delimited by the text of the th[data-stat=split_id] cell on a
    section's first row ("Place", "Rest", ...); continuation rows carry an
    empty split_id. Repeated column-header rows have split_value as a <th>,
    data rows as a <td> — that distinguishes them.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "splits"})
    if table is None:
        return []

    rows: list[dict] = []
    current_split_type: str | None = "total"  # leading "Total" row precedes any split_id label

    for tr in table.find_all("tr"):
        id_cell = tr.find("th", {"data-stat": "split_id"})
        value_td = tr.find("td", {"data-stat": "split_value"})

        if id_cell is not None:
            label = id_cell.get_text(strip=True).lower()
            if label and label != "split":
                current_split_type = SPLIT_TYPE_MAP.get(label, label)

        if value_td is None:
            continue  # column-header or spacer row

        split_value = value_td.get_text(strip=True)
        if not split_value or current_split_type is None:
            continue

        row: dict = {
            "player_id": player_id,
            "player_name": player_name,
            "season": season,
            "split_type": current_split_type,
            "split_value": split_value,
        }
        for data_stat, col in STAT_COLS.items():
            td = tr.find("td", {"data-stat": data_stat})
            text = td.get_text(strip=True) if td is not None else ""
            row[col] = pd.to_numeric(text, errors="coerce")
        rows.append(row)

    return rows


def load_done_keys() -> set[tuple[str, int]]:
    """Return (player_id, season) pairs already present in the output parquet."""
    if not OUTPUT_PARQUET.exists():
        return set()
    existing = pd.read_parquet(OUTPUT_PARQUET, columns=["player_id", "season"])
    return set(zip(existing["player_id"], existing["season"], strict=False))


def append_save(new_rows: list[dict]) -> int:
    """Append new rows to the output parquet; return total row count on disk."""
    new_df = pd.DataFrame(new_rows)
    # Enforce schema: G nullable int, stats float
    new_df["season"] = new_df["season"].astype(int)
    new_df["G"] = new_df["G"].astype("Int64")
    for col in ["MP", "FG", "FGA", "3P", "3PA", "FT", "FTA", "PTS"]:
        new_df[col] = new_df[col].astype(float)
    if OUTPUT_PARQUET.exists():
        combined = pd.concat([pd.read_parquet(OUTPUT_PARQUET), new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_parquet(OUTPUT_PARQUET, index=False)
    return len(combined)


def load_population(player_filter: str | None, limit: int | None) -> pd.DataFrame:
    """Return eligible players (≥MIN_CAREER_GAMES rows) with season ranges.

    Columns: player_id, player_name, debut_year, final_year.
    """
    game_logs = DATA_DIR / "game_logs.parquet"
    if not game_logs.exists():
        raise FileNotFoundError("data/game_logs.parquet not found — run fetch_bref_data.py first.")
    logs = pd.read_parquet(game_logs, columns=["player_id", "season"])
    counts = logs.groupby("player_id").size()
    eligible_ids = set(counts[counts >= MIN_CAREER_GAMES].index)

    pop = pd.read_csv(DATA_DIR / "population_cohort.csv")
    pop = pop[pop["player_id"].isin(eligible_ids)].copy()
    missing = eligible_ids - set(pop["player_id"])
    if missing:
        logger.warning(
            "%d eligible players missing from population_cohort.csv — skipped: %s",
            len(missing),
            sorted(missing),
        )

    if player_filter:
        pop = pop[pop["player_id"] == player_filter]
        if pop.empty:
            raise ValueError(
                f"--player {player_filter!r} not in eligible population "
                f"(≥{MIN_CAREER_GAMES} game rows + population_cohort.csv)"
            )
    pop = pop.sort_values("player_id").reset_index(drop=True)
    if limit:
        pop = pop.head(limit)
    return pop[["player_id", "player_name", "debut_year", "final_year"]]


def fetch_season_splits(player_filter: str | None = None, limit: int | None = None) -> None:
    """Fetch splits pages for all eligible player-seasons not already in the parquet."""
    pop = load_population(player_filter, limit)
    done_keys = load_done_keys()
    logger.info(
        "Population: %d players; %d (player, season) pairs already in parquet.",
        len(pop),
        len(done_keys),
    )

    total_players_fetched = 0
    total_players_skipped = 0
    total_rows_added = 0

    for idx, prow in pop.iterrows():
        pid = prow["player_id"]
        pname = prow["player_name"]
        first = int(prow["debut_year"])
        last = int(prow["final_year"])

        player_rows: list[dict] = []
        n_fetched = 0
        n_skipped = 0

        for season in range(first, last + 1):
            if (pid, season) in done_keys:
                n_skipped += 1
                continue
            try:
                html = _get_html(pid, season)
            except SkipPlayerSeason as exc:
                logger.warning("Skipping %s season %d: %s", pid, season, exc)
                n_skipped += 1
                continue
            if html is None:
                n_skipped += 1
                continue
            rows = parse_splits_page(html, pid, pname, season)
            if rows:
                player_rows.extend(rows)
                n_fetched += 1
            else:
                logger.warning("%s season %d: no splits table parsed", pid, season)
                n_skipped += 1

        if player_rows:
            total_on_disk = append_save(player_rows)
            total_rows_added += len(player_rows)
            total_players_fetched += 1
            # keep done_keys current so a duplicate id in pop can't double-fetch
            done_keys.update({(pid, int(r["season"])) for r in player_rows})
        else:
            total_players_skipped += 1
            total_on_disk = None

        logger.info(
            "[%d/%d] %s: %d seasons fetched, %d skipped%s",
            idx + 1,
            len(pop),
            pname,
            n_fetched,
            n_skipped,
            f" (parquet: {total_on_disk:,} rows)" if total_on_disk is not None else "",
        )

    final_rows = len(pd.read_parquet(OUTPUT_PARQUET)) if OUTPUT_PARQUET.exists() else 0
    logger.info(
        "Done. Total rows in parquet: %s | players with new data: %d | "
        "players fully skipped: %d | rows added this run: %s",
        f"{final_rows:,}",
        total_players_fetched,
        total_players_skipped,
        f"{total_rows_added:,}",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", default=None, help="Single BRef player_id (for testing)")
    parser.add_argument(
        "--limit", type=int, default=None, help="First N eligible players (smoke test)"
    )
    args = parser.parse_args()

    fetch_season_splits(player_filter=args.player, limit=args.limit)
