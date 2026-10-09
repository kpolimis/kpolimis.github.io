"""Scrape Russell Westbrook's regular-season game logs from Basketball-Reference.

This regenerates ``data/westbrook_game_logs.csv``, the cached dataset the post
reads at render time. Scraping lives here, out of band, so the Quarto build never
touches the network (Basketball-Reference rate-limits aggressively and the render
kernel has no ``lxml``).

What changed since the 2022 original: the game-log table id moved from the old
``pgl_basic`` to ``player_game_log_reg``, and the per-column keys are now
``data-stat`` attributes (``pts``, ``trb``, ``ast``, ``game_result``, ...). A
scraper written against the 2022 markup returns an empty frame today, so the
schema guard below fails loudly rather than silently producing zero rows.

Usage:
    python fetch_westbrook_data.py
"""

import csv
import re
import time
import urllib.request

from lxml import html as LH

PLAYER_ID = "westbru01"
FIRST_SEASON_END = 2009  # 2008-09 rookie year
LAST_SEASON_END = 2026  # 2025-26
GAMELOG_URL = "https://www.basketball-reference.com/players/w/{pid}/gamelog/{year}"
TABLE_ID = "player_game_log_reg"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
REQUEST_DELAY_SECONDS = 3.5  # be a polite scraper; the site 429s under load

OUT_COLUMNS = [
    "date", "season_start", "season_end", "team", "opp", "location",
    "active", "result_b", "margin", "points", "total_rebs", "assists",
    "steals", "blocks",
]


def _as_int(value):
    """Return ``value`` as an int, or 0 when the cell is blank/non-numeric."""
    return int(value) if re.fullmatch(r"-?\d+", value or "") else 0


def fetch_season(end_year):
    """Fetch and parse one season's game log (regular season only).

    Returns one row per *team* game, including games Westbrook missed
    (``active == 0``); Basketball-Reference still lists those with the team
    result, which is what makes the career win-percentage comparison possible.
    """
    url = GAMELOG_URL.format(pid=PLAYER_ID, year=end_year)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        doc = LH.fromstring(resp.read())

    tables = doc.xpath(f'//table[@id="{TABLE_ID}"]')
    if not tables:
        raise RuntimeError(
            f"Table '{TABLE_ID}' not found for {end_year}. Basketball-Reference "
            "likely renamed the game-log table again; inspect the page markup."
        )

    rows = []
    for tr in tables[0].xpath(".//tbody/tr"):
        cell = {c.get("data-stat"): c.text_content().strip()
                for c in tr.xpath("./th|./td")}
        if cell.get("ranker") == "Rk" or not cell.get("date"):
            continue  # repeated header / spacer row

        result = cell.get("game_result", "")
        result_b = 1 if result.startswith("W") else (0 if result.startswith("L") else None)
        margin = None
        m = re.search(r"[WL],\s*(\d+)-(\d+)", result)
        if m:
            margin = int(m.group(1)) - int(m.group(2))  # signed: + for wins

        rows.append({
            "date": cell.get("date"),
            "season_start": end_year - 1,
            "season_end": end_year,
            "team": cell.get("team_name_abbr"),
            "opp": cell.get("opp_name_abbr"),
            "location": "Away" if cell.get("game_location") == "@" else "Home",
            # a played game always has a numeric points cell; missed games do not
            "active": 1 if re.fullmatch(r"-?\d+", cell.get("pts", "")) else 0,
            "result_b": result_b,
            "margin": margin,
            "points": _as_int(cell.get("pts")),
            "total_rebs": _as_int(cell.get("trb")),
            "assists": _as_int(cell.get("ast")),
            "steals": _as_int(cell.get("stl")),
            "blocks": _as_int(cell.get("blk")),
        })
    return rows


def main():
    """Scrape every season and write the cached CSV."""
    all_rows = []
    for end_year in range(FIRST_SEASON_END, LAST_SEASON_END + 1):
        season = fetch_season(end_year)
        played = sum(r["active"] for r in season)
        print(f"{end_year - 1}-{str(end_year)[2:]}: {len(season)} team games, {played} played")
        all_rows.extend(season)
        time.sleep(REQUEST_DELAY_SECONDS)

    with open("data/westbrook_game_logs.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"wrote {len(all_rows)} rows to data/westbrook_game_logs.csv")


if __name__ == "__main__":
    main()
