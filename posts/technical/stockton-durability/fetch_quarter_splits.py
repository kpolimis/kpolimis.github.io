r"""fetch_quarter_splits.py — scrape per-game quarter box scores from BRef.

For each player, fetch boxscore HTML for every game in game_logs.parquet,
extract quarter-level stats, and save to a parquet file.

PF cohort → data/quarter_splits_pf.parquet
PG cohort → data/quarter_splits_pg.parquet  (restricted to 1996–2003)
E8 population → data/quarter_splits_e8.parquet

Files are kept SEPARATE to avoid write conflicts.

Usage:
    # Full Diaw career (PF cohort)
    conda run -n blog python fetch_quarter_splits.py --player diawbo01

    # Diaw + 3 PF comps (after analyze_durability.py --cohort pf)
    conda run -n blog python fetch_quarter_splits.py \\
        --comps-file data/pf_comparators.csv

    # Stockton + 3 PG comps, 1996–2003 window only
    conda run -n blog python fetch_quarter_splits.py \\
        --comps-file data/pg_comparators.csv \\
        --seasons 1996-2003

    # E8: top-50 most-durable players from population
    conda run -n blog python fetch_quarter_splits.py --top-n-by-games 50

    # Quick test (single season)
    conda run -n blog python fetch_quarter_splits.py \\
        --player diawbo01 --seasons 2005
"""

import argparse
import logging
import os
import pathlib
import random as _random
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

DATA_DIR = pathlib.Path(__file__).parent / "data"
HTML_CACHE_QUARTER = DATA_DIR / "html_cache" / "quarter"

RATE_LIMIT_SEC = 3.5  # BRef allows 20 req/min max (= 3s minimum); 3.5s for headroom
RATE_LIMIT_JITTER = 1.5
SESSION_COOLDOWN_PAGES = int(os.environ.get("SESSION_COOLDOWN_PAGES", 100))
SESSION_COOLDOWN_SEC = int(os.environ.get("SESSION_COOLDOWN_SEC", 300))
_MAX_403_BACKOFF = int(os.environ.get("MAX_403_BACKOFF_SEC", 600))
GLUETUN_CTRL_URL = os.environ.get("GLUETUN_CTRL_URL", "")

_ip_blocked_until: float = 0.0
_session_page_count: int = 0

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def _ensure_dirs() -> None:
    """Create DATA_DIR and HTML_CACHE_QUARTER if they do not exist."""
    DATA_DIR.mkdir(exist_ok=True)
    HTML_CACHE_QUARTER.mkdir(parents=True, exist_ok=True)


def _rotate_vpn() -> bool:
    """Stop and restart the Gluetun VPN to get a fresh exit IP.

    Only active when GLUETUN_CTRL_URL is set (e.g. http://localhost:8000 in
    the Docker network). Returns True if the rotation completed successfully.
    """
    if not GLUETUN_CTRL_URL:
        return False
    import json as _json

    try:
        for status in ("stopped", "running"):
            r = requests.put(
                f"{GLUETUN_CTRL_URL}/v1/vpn/status",
                data=_json.dumps({"status": status}),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            r.raise_for_status()
            if status == "stopped":
                time.sleep(2)
        time.sleep(15)  # wait for reconnect and new IP assignment
        logger.info("VPN rotated via Gluetun — new exit IP active")
        return True
    except Exception as exc:
        logger.warning("VPN rotation failed: %s", exc)
        return False


def _parse_mp(mp_str: str) -> float | None:
    """Convert BRef minutes string to float.

    Args:
        mp_str: Minutes string in 'MM:SS' format (e.g. '34:21').

    Returns:
        Float minutes (e.g. 34.35), or None if not parseable.
    """
    if not isinstance(mp_str, str) or ":" not in mp_str:
        return None
    try:
        m, s = mp_str.split(":")
        return int(m) + int(s) / 60
    except ValueError:
        return None


def _ts_pct(pts: float, fga: float, fta: float) -> float | None:
    """Compute true shooting percentage.

    Args:
        pts: Points scored.
        fga: Field goal attempts.
        fta: Free throw attempts.

    Returns:
        TS% = PTS / (2 * (FGA + 0.44*FTA)), or None if denominator is zero.
    """
    denom = 2 * (fga + 0.44 * fta)
    if denom <= 0:
        return None
    return pts / denom


def _fetch_with_retry(
    base_url: str,
    headers: dict,
    game_id: str,
    pbp: bool,
    cache_path: pathlib.Path,
) -> str | None:
    """Attempt up to 4 fetches of base_url, handling 429/403/404 responses.

    Args:
        base_url: Full URL to fetch.
        headers: HTTP headers dict.
        game_id: BRef game identifier, used in log messages.
        pbp: Whether this is a play-by-play request, used in log messages.
        cache_path: Path to write successful HTML response.

    Returns:
        HTML text on success, None on persistent failure.
    """
    global _ip_blocked_until, _session_page_count

    for attempt in range(4):
        try:
            resp = requests.get(base_url, headers=headers, timeout=20)
        except requests.RequestException as exc:
            logger.warning("Request error for %s (pbp=%s): %s", game_id, pbp, exc)
            return None
        if resp.status_code == 200:
            cache_path.write_text(resp.text, encoding="utf-8")
            _session_page_count += 1
            if _session_page_count % SESSION_COOLDOWN_PAGES == 0:
                logger.info(
                    "Session cooldown (%d pages) — sleeping %ds",
                    _session_page_count,
                    SESSION_COOLDOWN_SEC,
                )
                time.sleep(SESSION_COOLDOWN_SEC)
            else:
                time.sleep(RATE_LIMIT_SEC + _random.uniform(0, RATE_LIMIT_JITTER))
            return resp.text
        if resp.status_code == 429:
            # Rate limit — wait out the Retry-After header; do NOT rotate VPN here
            # because BRef may have rate-limited multiple IPs in the pool, causing
            # an infinite rotation loop with no pages fetched. The wait-based approach
            # (which worked for 13h of successful fetching) is more reliable.
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else 120 * (2**attempt)
            logger.warning(
                "HTTP 429 game_id=%s (pbp=%s) — waiting %ds (attempt %d)",
                game_id,
                pbp,
                wait,
                attempt + 1,
            )
            _ip_blocked_until = time.time() + wait
            time.sleep(wait)
        elif resp.status_code == 403:
            # Hard IP block — rotate VPN to get a fresh exit IP, then retry
            if _rotate_vpn():
                _ip_blocked_until = 0.0
            else:
                wait = min(_MAX_403_BACKOFF, 120 * (2**attempt))
                logger.warning(
                    "HTTP 403 game_id=%s (pbp=%s) — sleeping %ds (attempt %d)",
                    game_id,
                    pbp,
                    wait,
                    attempt + 1,
                )
                _ip_blocked_until = time.time() + wait
                time.sleep(wait)
        elif resp.status_code == 404:
            return None  # don't log 404 — pre-PBP-era games are expected
        else:
            logger.warning("HTTP %d for game_id=%s (pbp=%s)", resp.status_code, game_id, pbp)
            return None
    return None


def _get_html(game_id: str, pbp: bool = False) -> tuple[str | None, bool]:
    """Return (html, cache_hit) for a BRef boxscore or PBP page.

    Args:
        game_id: BRef game identifier (e.g. '200301140UTA').
        pbp: If True, fetch the play-by-play URL; otherwise the box score.

    Returns:
        Tuple of (html_text, cache_hit). html_text is None on failure.
    """
    suffix = "_pbp" if pbp else ""
    cache_path = HTML_CACHE_QUARTER / f"{game_id}{suffix}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8"), True
    base_url = (
        f"https://www.basketball-reference.com/boxscores/pbp/{game_id}.html"
        if pbp
        else f"https://www.basketball-reference.com/boxscores/{game_id}.html"
    )
    now = time.time()
    if _ip_blocked_until > now:
        time.sleep(_ip_blocked_until - now)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; stockton-research/1.0; +https://kpolimis.github.io/)"
    }
    text = _fetch_with_retry(base_url, headers, game_id, pbp, cache_path)
    return text, False


def _extract_game_id(row: pd.Series) -> str | None:
    """Derive BRef game_id from game log row.

    BRef game_id format: YYYYMMDD0{HOME_ABBREV}
    We reconstruct it from Date + Opp + home/away flag.
    Falls back to a URL-cached approach if Gtm/Tm columns are present.
    """
    date = row.get("Date")
    if pd.isna(date):
        return None
    date_str = pd.Timestamp(date).strftime("%Y%m%d")
    # Home/away: BRef game logs mark away games with @ in the unnamed column
    # "Team" is the parquet column name (BRef game logs use "Tm" in HTML but ETL renamed it)
    own_team = str(row.get("Team", row.get("Tm", ""))).strip()
    away_flag = str(row.get("Unnamed: 5", "")).strip() == "@"
    opponent = str(row.get("Opp", "")).strip()
    # When away, game is at opponent's arena; home team = opponent
    home = opponent if away_flag else own_team
    # BRef team abbreviations are already 3-char
    return f"{date_str}0{home.upper()}"


def _split_play(play: str) -> tuple[str, str]:
    """Split a BRef play description into main action and parenthetical content.

    Args:
        play: Lowercased play description string.

    Returns:
        Tuple of (main_action, parentheticals) where parentheticals is a
        space-joined string of all text inside parentheses.
    """
    parens_content = " ".join(re.findall(r"\(([^)]*)\)", play))
    main = re.sub(r"\([^)]*\)", "", play).strip()
    return main, parens_content


def _classify_play(play_lower: str, last_name: str, first_name: str) -> dict:
    """Return per-stat increments for one BRef PBP play text.

    Uses shooter-anchored attribution: the player must appear in the main action
    (outside parentheticals) to receive FG/FT/TOV credit. AST is the exception —
    the player's name must appear after "assist by" in a parenthetical. Prevents
    "steal by Stockton" plays from charging him a TOV, and "assist by Stockton"
    plays from crediting him a field goal.

    BRef field-goal format: "makes 2-pt jump shot from X ft", "makes 3-pt jump
    shot", "misses 2-pt/3-pt ...". Free throws: "makes/misses free throw N of M".
    PTS includes free-throw points (1 per made FT).

    Args:
        play_lower: Lowercased play description string.
        last_name: Lowercased player last name.
        first_name: Lowercased player first name.

    Returns:
        Dict with keys FT, FTA, FGA, PTS, AST, TOV and integer increment values.
    """
    increments = {"FT": 0, "FTA": 0, "FGA": 0, "PTS": 0, "AST": 0, "TOV": 0}
    main, parens = _split_play(play_lower)
    player_in_main = last_name in main or first_name in main

    if player_in_main:
        if re.search(r"makes free throw", main):
            increments["FT"] += 1
            increments["FTA"] += 1
            increments["PTS"] += 1
        elif re.search(r"misses free throw", main):
            increments["FTA"] += 1
        elif re.search(r"makes 3-pt", main):
            increments["FGA"] += 1
            increments["PTS"] += 3
        elif re.search(r"makes 2-pt", main):
            increments["FGA"] += 1
            increments["PTS"] += 2
        elif re.search(r"misses (2|3)-pt", main):
            increments["FGA"] += 1
        if re.search(r"turnover by", main):
            increments["TOV"] += 1

    if re.search(rf"assist by\b[^)]*\b{re.escape(last_name)}\b", parens):
        increments["AST"] += 1

    return increments


def _parse_quarter_label(row_text: str) -> str | None:
    """Return the quarter label from a PBP header row, or None if not a header.

    Args:
        row_text: Lowercased full text of one BRef PBP table row.

    Returns:
        Quarter label string (e.g. '1', '2', 'OT1') or None.
    """
    m = re.search(
        r"start of (1st|2nd|3rd|4th)\s+(quarter|overtime|period)", row_text, re.IGNORECASE
    )
    if not m:
        return None
    ordinal = m.group(1).lower()
    period = m.group(2).lower()
    if period in ("overtime", "period"):
        return {"1st": "OT1", "2nd": "OT2", "3rd": "OT3", "4th": "OT4"}.get(ordinal, f"OT{ordinal}")
    return {"1st": "1", "2nd": "2", "3rd": "3", "4th": "4"}.get(ordinal, ordinal)


def _process_play(
    play_text: str,
    first_name: str,
    last_name: str,
    current_quarter: str,
    quarters: dict[str, dict],
) -> None:
    """Apply one PBP play to the quarters accumulator in place.

    Args:
        play_text: Raw play cell text (visitor or home column).
        first_name: Lowercased player first name.
        last_name: Lowercased player last name.
        current_quarter: Active quarter label (e.g. '1', 'OT1').
        quarters: Mutable accumulator dict updated in place.
    """
    if not play_text:
        return
    play_lower = play_text.lower()
    if last_name not in play_lower and first_name not in play_lower:
        return
    inc = _classify_play(play_lower, last_name, first_name)
    if not any(inc.values()):
        return
    if current_quarter not in quarters:
        quarters[current_quarter] = {k: 0 for k in inc}
    for k, v in inc.items():
        quarters[current_quarter][k] += v


def _accumulate_pbp_stats(pbp_table, first_name: str, last_name: str) -> dict[str, dict]:
    """Walk a BRef PBP table and accumulate per-quarter stats for one player.

    Args:
        pbp_table: BeautifulSoup tag for the 'pbp' table.
        first_name: Lowercased player first name for play matching.
        last_name: Lowercased player last name for play matching.

    Returns:
        Dict mapping quarter label (e.g. '1', '2', 'OT1') to stat increments dict.
    """
    quarters: dict[str, dict] = {}
    current_quarter = "1"

    for tr in pbp_table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        # Check for quarter header row
        full_text = tr.get_text(" ", strip=True).lower()
        label = _parse_quarter_label(full_text)
        if label is not None:
            current_quarter = label
            continue

        # Each data row: col0=time, col1=visitor_play, col2=score, col3=home_play
        if len(tds) < 4:
            continue

        visitor_play = tds[1].get_text(" ", strip=True)
        home_play = tds[3].get_text(" ", strip=True)
        for play_text in (visitor_play, home_play):
            _process_play(play_text, first_name, last_name, current_quarter, quarters)

    return quarters


def _quarters_to_rows(
    quarters: dict[str, dict],
    game_id: str,
    player_id: str,
    player_name: str,
    season: int,
    date,
    age_regime: str,
) -> list[dict]:
    """Convert accumulated per-quarter stat dicts to output row dicts.

    Args:
        quarters: Mapping of quarter label → stat dict from _accumulate_pbp_stats.
        game_id: BRef game identifier.
        player_id: BRef player identifier.
        player_name: Human-readable player name.
        season: Season end-year (e.g. 2003 for 2002-03).
        date: Game date.
        age_regime: Age-regime label for this player-season.

    Returns:
        List of row dicts, one per quarter played.
    """
    rows = []
    for q_label, stats in quarters.items():
        fta = stats["FTA"]
        ft_pct = (stats["FT"] / fta) if fta > 0 else None
        fga = stats["FGA"]
        pts = stats["PTS"]
        ts = _ts_pct(pts, fga, fta)
        rows.append(
            {
                "game_id": game_id,
                "player_id": player_id,
                "player_name": player_name,
                "season": season,
                "date": date,
                "quarter": q_label,
                "FT": stats["FT"],
                "FTA": fta,
                "FT_pct": ft_pct,
                "AST": stats["AST"],
                "TOV": stats["TOV"],
                "FGA": fga,
                "PTS": pts,
                "TS_pct": ts,
                "age_regime": age_regime,
                "score_margin": None,  # margin extracted from box score, not PBP
            }
        )
    return rows


def parse_pbp_quarters(
    html: str,
    player_id: str,
    player_name: str,
    game_id: str,
    season: int,
    date,
    age_regime: str,
) -> list[dict]:
    """Parse BRef play-by-play HTML to produce per-quarter stats for one player.

    BRef PBP URL: /boxscores/pbp/{game_id}.html
    Table id: 'pbp'. Each row is one play; quarter boundaries are identified
    by cells containing 'Start of Nth quarter/overtime'.

    Args:
        html: Raw HTML of the BRef PBP page.
        player_id: BRef player identifier.
        player_name: Human-readable player name for play text matching.
        game_id: BRef game identifier.
        season: Season end-year.
        date: Game date.
        age_regime: Age-regime label for this player-season.

    Returns:
        List of per-quarter stat dicts. Empty if player not found or didn't play.
    """
    soup = BeautifulSoup(html, "html.parser")
    pbp_table = soup.find("table", {"id": "pbp"})
    if pbp_table is None:
        return []

    # BRef player names vary slightly; build all-lowercase match set
    first_name = player_name.split()[0].lower() if player_name else ""
    last_name = player_name.split()[-1].lower() if player_name else ""

    quarters = _accumulate_pbp_stats(pbp_table, first_name, last_name)
    if not quarters:
        return []
    return _quarters_to_rows(quarters, game_id, player_id, player_name, season, date, age_regime)


def _find_player_full_game_stats(
    soup: BeautifulSoup, player_link_pattern
) -> tuple[dict, float | None] | None:
    """Locate a player's full-game stats and score margin from a box score page.

    Args:
        soup: Parsed box score page.
        player_link_pattern: Compiled regex matching the player's BRef profile URL.

    Returns:
        Tuple of (stat_dict, score_margin) if the player is found and played,
        or None if not found or DNP.
    """
    for table in soup.find_all("table", id=re.compile(r"box-.*-game-basic")):
        for tr in table.find_all("tr"):
            link = tr.find("a", href=player_link_pattern)
            if link is None:
                continue
            tds = tr.find_all("td")
            stat = {}
            for td in tds:
                data_stat = td.get("data-stat", "")
                stat[data_stat] = td.get_text(strip=True)
            mp = _parse_mp(stat.get("mp", ""))
            if mp is None:
                continue  # DNP
            score_margin = _extract_score_margin(soup, table)
            return stat, score_margin
    return None


def parse_quarter_box(
    html: str,
    player_id: str,
    player_name: str,
    game_id: str,
    season: int,
    date,
    age_regime: str,
) -> list[dict]:
    """Extract full-game stats for one player from a boxscore HTML page.

    BRef box scores expose full-game totals only (no per-quarter breakdown).
    Quarter-level splits require play-by-play; this is the fallback path for
    games where PBP is unavailable. score_margin is extracted here for
    blowout sensitivity analysis.

    Args:
        html: Raw HTML of the BRef box score page.
        player_id: BRef player identifier.
        player_name: Human-readable player name.
        game_id: BRef game identifier.
        season: Season end-year.
        date: Game date.
        age_regime: Age-regime label for this player-season.

    Returns:
        List with one row dict (quarter='full'), or empty list if not found / DNP.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Locate player's row in the basic box score tables
    player_link_pattern = re.compile(rf"/players/\w/{player_id}\.html")
    player_tag = soup.find("a", href=player_link_pattern)
    if player_tag is None:
        return []

    result = _find_player_full_game_stats(soup, player_link_pattern)
    if result is None:
        return []
    stat, score_margin = result

    def _n(key: str, _stat: dict = stat) -> float:
        try:
            return float(_stat.get(key, 0) or 0)
        except ValueError:
            return 0.0

    ft = _n("ft")
    fta = _n("fta")
    fga = _n("fga")
    pts = _n("pts")
    ast = _n("ast")
    tov = _n("tov")

    ft_pct = (ft / fta) if fta > 0 else None
    ts = _ts_pct(pts, fga, fta)

    return [
        {
            "game_id": game_id,
            "player_id": player_id,
            "player_name": player_name,
            "season": season,
            "date": date,
            "quarter": "full",  # full-game; quarter-level requires PBP
            "FT": ft,
            "FTA": fta,
            "FT_pct": ft_pct,
            "AST": ast,
            "TOV": tov,
            "FGA": fga,
            "PTS": pts,
            "TS_pct": ts,
            "age_regime": age_regime,
            "score_margin": score_margin,
        }
    ]


def _extract_score_margin(soup: BeautifulSoup, table) -> float | None:
    """Extract final score margin from the page scoreline.

    Args:
        soup: Parsed box score page.
        table: The box score table tag (unused; kept for call-site compatibility).

    Returns:
        Absolute score difference as float, or None if not parseable.
    """
    # BRef scoreline is in <div class="scorebox">
    scorebox = soup.find("div", class_="scorebox")
    if scorebox is None:
        return None
    scores = scorebox.find_all("div", class_="score")
    if len(scores) < 2:
        return None
    try:
        s1 = int(scores[0].get_text(strip=True))
        s2 = int(scores[1].get_text(strip=True))
        return float(abs(s1 - s2))
    except (ValueError, TypeError):
        return None


def _age_regime(player_id: str, season: int) -> str:
    """Return age-regime label for a player-season.

    Stockton rows get 'stockton_34_40'; others get their actual age bracket.

    Args:
        player_id: BRef player identifier.
        season: Season end-year.

    Returns:
        Age-regime label string.
    """
    if player_id == "stockjo01":
        return "stockton_34_40"
    # Approximate age from season; this is refined per-row if 'Age' column available
    return f"ages_{(season - 25) // 5 * 5}_{(season - 25) // 5 * 5 + 4}"


def build_player_game_index(
    player_ids: list[str],
    season_range: tuple[int, int] | None = None,
) -> pd.DataFrame:
    """Build index of (player_id, game_id, season, date) from game_logs.parquet.

    Args:
        player_ids: List of BRef player identifiers to include.
        season_range: Optional (start_year, end_year) filter, inclusive.

    Returns:
        DataFrame with columns [player_id, player_name, game_id, season, Date].

    Raises:
        FileNotFoundError: If game_logs.parquet does not exist.
    """
    parquet = DATA_DIR / "game_logs.parquet"
    if not parquet.exists():
        raise FileNotFoundError("data/game_logs.parquet not found — run fetch_bref_data.py first.")

    df = pd.read_parquet(parquet)
    df = df[df["player_id"].isin(player_ids)].copy()
    df["mp_float"] = df["MP"].apply(_parse_mp)
    df = df[df["mp_float"].notna()].copy()

    if season_range:
        df = df[(df["season"] >= season_range[0]) & (df["season"] <= season_range[1])].copy()

    df["game_id"] = df.apply(_extract_game_id, axis=1)
    df = df.dropna(subset=["game_id"]).copy()
    df["game_id"] = df["game_id"].astype(str)

    logger.info(
        "Game index: %d games for %d player(s) (season range: %s)",
        len(df),
        df["player_id"].nunique(),
        season_range or "all",
    )
    return df[["player_id", "player_name", "game_id", "season", "Date"]].copy()


def _fetch_game_rows(
    grow: pd.Series,
    done_games: set,
    new_requests: int,
    cache_hits: int,
) -> tuple[list[dict], int, int]:
    """Fetch quarter-split rows for one game log row.

    Tries PBP first; falls back to full-game box score if PBP yields nothing.

    Args:
        grow: One row from the game index DataFrame.
        done_games: Set of (player_id, game_id) pairs already in the output parquet.
        new_requests: Running count of new network requests (for logging).
        cache_hits: Running count of cache hits (for logging).

    Returns:
        Tuple of (rows, new_requests_delta, cache_hits_delta).
    """
    pid = grow["player_id"]
    pname = grow.get("player_name", pid)
    game_id = grow["game_id"]
    season = int(grow["season"])
    date = grow["Date"]

    if (pid, game_id) in done_games:
        return [], 0, 1

    regime = _age_regime(pid, season)

    # Try PBP first (gives true quarter-level stats; available ≥1996-97)
    pbp_html, pbp_cached = _get_html(game_id, pbp=True)
    req_delta = 0 if pbp_cached else 1
    hit_delta = 1 if pbp_cached else 0

    rows: list[dict] = []
    if pbp_html:
        rows = parse_pbp_quarters(pbp_html, pid, pname, game_id, season, date, regime)

    # Fall back to full-game box score (produces quarter='full'; less informative
    # but still captures FTA/FGA/score_margin used in blowout sensitivity)
    if not rows:
        box_html, box_cached = _get_html(game_id, pbp=False)
        req_delta += 0 if box_cached else 1
        hit_delta += 1 if box_cached else 0
        if box_html:
            rows = parse_quarter_box(box_html, pid, pname, game_id, season, date, regime)

    return rows, req_delta, hit_delta


def fetch_quarter_splits(
    player_ids: list[str],
    output_parquet: str,
    season_range: tuple[int, int] | None = None,
) -> pd.DataFrame:
    """Fetch quarter-split stats for the given players; save to output_parquet.

    Args:
        player_ids: List of BRef player identifiers.
        output_parquet: Filename (not full path) under data/ for the output parquet.
        season_range: Optional (start_year, end_year) filter, inclusive.

    Returns:
        Combined DataFrame of all fetched and previously-existing rows.
    """
    out_path = DATA_DIR / output_parquet

    # Load existing output to skip already-fetched game_ids
    if out_path.exists():
        existing = pd.read_parquet(out_path)
        done_games: set[tuple[str, str]] = set(
            zip(existing["player_id"], existing["game_id"], strict=False)
        )
        logger.info(
            "Existing: %d rows, %d (player, game) pairs already fetched.",
            len(existing),
            len(done_games),
        )
    else:
        existing = pd.DataFrame()
        done_games = set()

    game_index = build_player_game_index(player_ids, season_range)
    all_rows: list[dict] = []
    new_requests = 0
    cache_hits = 0
    _last_save = 0

    for _, grow in game_index.iterrows():
        rows, req_delta, hit_delta = _fetch_game_rows(grow, done_games, new_requests, cache_hits)
        new_requests += req_delta
        cache_hits += hit_delta
        all_rows.extend(rows)

        # Incremental save every 500 new requests — allow resume on container restart.
        # Use delta (not modulo) to avoid skipped triggers when a single iteration
        # increments new_requests by 2 (PBP miss + box fetch), and to avoid per-game
        # rewrites when new_requests sits exactly on a prior multiple of 500.
        if new_requests - _last_save >= 500 and all_rows:
            _tmp = pd.DataFrame(all_rows)
            _combined = (
                pd.concat([existing, _tmp], ignore_index=True) if not existing.empty else _tmp
            )
            _combined.to_parquet(out_path, index=False)
            logger.info(
                "Incremental save: %d rows (%d new requests so far)", len(_combined), new_requests
            )
            _last_save = new_requests

    logger.info(
        "Fetch complete: %d new network requests, %d cache hits",
        new_requests,
        cache_hits,
    )

    if not all_rows and existing.empty:
        logger.warning("No rows fetched.")
        return pd.DataFrame()

    new_df = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
    combined = pd.concat([existing, new_df], ignore_index=True) if not new_df.empty else existing
    combined.to_parquet(out_path, index=False)
    logger.info("Saved %d rows to %s", len(combined), out_path)
    logger.info("Row count: %d (expected ~9,100–9,600 for PG cohort full fetch)", len(combined))

    return combined


def _parse_season_range(s: str | None) -> tuple[int, int] | None:
    """Parse '1996-2003' → (1996, 2003).

    Args:
        s: Season range string in 'YYYY-YYYY' format, or None.

    Returns:
        Tuple (start_year, end_year), or None if s is None.

    Raises:
        ValueError: If the format is not 'YYYY-YYYY'.
    """
    if s is None:
        return None
    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(f"Season range must be YYYY-YYYY, got: {s!r}")
    return int(parts[0]), int(parts[1])


def _top_n_by_games(n: int) -> list[str]:
    """Return the n player_ids with the most active game rows in game_logs.parquet.

    Args:
        n: Number of players to return.

    Returns:
        List of BRef player_id strings, sorted descending by active game count.

    Raises:
        FileNotFoundError: If game_logs.parquet does not exist.
    """
    parquet = DATA_DIR / "game_logs.parquet"
    if not parquet.exists():
        raise FileNotFoundError("data/game_logs.parquet not found — run fetch_bref_data.py first.")
    df = pd.read_parquet(parquet)
    df["mp_float"] = df["MP"].apply(_parse_mp)
    active = df[df["mp_float"].notna()]
    counts = active.groupby("player_id").size().sort_values(ascending=False)
    top = counts.head(n)
    logger.info("Top-%d by active games:\n%s", n, top.to_string())
    return top.index.tolist()


if __name__ == "__main__":
    _ensure_dirs()

    parser = argparse.ArgumentParser()
    parser.add_argument("--player", default=None, help="Single BRef player_id to fetch")
    parser.add_argument(
        "--comps-file", default=None, help="CSV with player_id column (from analyze_durability.py)"
    )
    parser.add_argument("--seasons", default=None, help="Season range YYYY-YYYY (e.g. 1996-2003)")
    parser.add_argument(
        "--output",
        default=None,
        help="Output parquet filename (auto-detected from comps-file if omitted)",
    )
    parser.add_argument(
        "--top-n-by-games",
        type=int,
        default=None,
        metavar="N",
        help="Fetch top-N most-durable players from game_logs.parquet (E8 mode); outputs quarter_splits_e8.parquet",
    )
    args = parser.parse_args()

    if args.top_n_by_games is None and args.comps_file is None and args.player is None:
        parser.error("Provide --player, --comps-file, or --top-n-by-games")

    player_ids = []
    output_parquet = args.output

    if args.top_n_by_games is not None:
        player_ids = _top_n_by_games(args.top_n_by_games)
        if output_parquet is None:
            output_parquet = "quarter_splits_e8.parquet"

    if args.player:
        player_ids.append(args.player)

    if args.comps_file:
        comps = pd.read_csv(args.comps_file)
        if "player_id" not in comps.columns:
            raise ValueError(f"--comps-file {args.comps_file} must have a 'player_id' column.")
        player_ids.extend(comps["player_id"].tolist())
        # Auto-detect output file from comps filename
        if output_parquet is None:
            stem = pathlib.Path(args.comps_file).stem  # e.g. "pg_comparators"
            cohort_tag = stem.split("_")[0]  # "pg" or "pf"
            output_parquet = f"quarter_splits_{cohort_tag}.parquet"

    if output_parquet is None:
        # Fall back: single player, guess from player_id
        if "stockjo01" in player_ids:
            output_parquet = "quarter_splits_pg.parquet"
        else:
            output_parquet = "quarter_splits_pf.parquet"

    season_range = _parse_season_range(args.seasons)
    player_ids = list(dict.fromkeys(player_ids))  # deduplicate preserving order

    logger.info("Players (%d): %s", len(player_ids), player_ids)
    logger.info("Output: data/%s", output_parquet)
    logger.info("Season range: %s", season_range or "all")

    fetch_quarter_splits(player_ids, output_parquet, season_range)
