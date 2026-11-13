"""National Tight End Day TD Analysis.

Run from this directory: conda run -n blog python analysis.py
"""

import io
import pathlib

import numpy as np
import pandas as pd
import requests

DATA = pathlib.Path("data")
DATA.mkdir(exist_ok=True)

YEARS = list(range(2018, 2026))  # 2018–2025

NTED_DATES = {
    2018: "2018-10-28",
    2019: "2019-10-27",
    2020: "2020-10-25",
    2021: "2021-10-24",
    2022: "2022-10-23",
    2023: "2023-10-22",
    2024: "2024-10-27",
    2025: "2025-10-26",
}

PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{year}.parquet"
ROSTER_URL = "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{year}.parquet"

PBP_COLS = [
    "game_id", "game_date", "season", "week", "season_type",
    "td_player_id", "td_player_name", "td_team",
]


def download(url: str, dest: pathlib.Path) -> pathlib.Path:
    """Download url to dest, returning dest (uses cache if already present)."""
    if dest.exists():
        print(f"  cached  {dest.name}")
        return dest
    print(f"  fetch   {url} ...", end="", flush=True)
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    buf = io.BytesIO()
    for chunk in r.iter_content(65536):
        buf.write(chunk)
    buf.seek(0)
    dest.write_bytes(buf.read())
    print(f" {dest.stat().st_size // 1_000_000} MB")
    return dest


def load_pbp(year: int) -> pd.DataFrame:
    """Load play-by-play parquet for a given season, downloading if needed."""
    path = download(PBP_URL.format(year=year), DATA / f"pbp_{year}.parquet")
    df = pd.read_parquet(path, columns=PBP_COLS)
    return df


def load_roster(year: int) -> pd.DataFrame:
    """Load weekly roster parquet for a given season, filtered to TEs."""
    path = download(ROSTER_URL.format(year=year), DATA / f"roster_{year}.parquet")
    df = pd.read_parquet(path, columns=["gsis_id", "position", "season", "week"])
    return df[df["position"] == "TE"].dropna(subset=["gsis_id"])


def te_tds_for_year(year: int) -> pd.DataFrame:
    """Return one row per Sunday game-date with TE TD count and game count."""
    pbp = load_pbp(year)
    roster = load_roster(year)

    # TD plays only, regular season, with a scorer
    tds = pbp[
        (pbp["season_type"] == "REG")
        & pbp["td_player_id"].notna()
    ].copy()
    tds["game_date"] = pd.to_datetime(tds["game_date"])

    # Sunday games only
    tds = tds[tds["game_date"].dt.dayofweek == 6]

    # Join to roster: is the scorer a TE in that week?
    tds = tds.merge(
        roster.rename(columns={"gsis_id": "td_player_id"}),
        on=["td_player_id", "season", "week"],
        how="left",
    )
    te_tds = tds[tds["position"] == "TE"]

    # Count TE TDs per game
    te_per_game = (
        te_tds.groupby(["game_date", "game_id"])
        .size()
        .reset_index(name="te_tds")
    )

    # All Sunday games (to get game counts per slate)
    all_sunday_games = (
        pbp[
            (pbp["season_type"] == "REG")
            & (pd.to_datetime(pbp["game_date"]).dt.dayofweek == 6)
        ]
        .drop_duplicates("game_id")[["game_id", "game_date"]]
        .copy()
    )
    all_sunday_games["game_date"] = pd.to_datetime(all_sunday_games["game_date"])

    # Merge — games with no TE TDs get 0
    merged = all_sunday_games.merge(te_per_game, on=["game_id", "game_date"], how="left")
    merged["te_tds"] = merged["te_tds"].fillna(0).astype(int)

    # Aggregate to slate level
    slates = (
        merged.groupby("game_date")
        .agg(te_tds=("te_tds", "sum"), n_games=("game_id", "count"))
        .reset_index()
    )
    slates["te_rate"] = slates["te_tds"] / slates["n_games"]
    slates["season"] = year
    return slates


print("=== Downloading data ===")
all_slates = []
for y in YEARS:
    print(f"\n--- {y} ---")
    slates = te_tds_for_year(y)
    all_slates.append(slates)

sunday_slates = pd.concat(all_slates, ignore_index=True)
sunday_slates.to_csv(DATA / "sunday_slates.csv", index=False)
print(f"\nSaved {len(sunday_slates)} Sunday slates across {len(YEARS)} seasons.")

print("\n=== NTED Results ===")
rows = []
for year, nted_date in NTED_DATES.items():
    nted_dt = pd.Timestamp(nted_date)
    season_slates = sunday_slates[sunday_slates["season"] == year].copy()

    if len(season_slates) == 0:
        print(f"{year}: no slate data")
        continue

    # Rank slates by te_rate (rank 1 = highest)
    season_slates = season_slates.sort_values("te_rate", ascending=False).reset_index(drop=True)
    season_slates["rank"] = season_slates.index + 1

    match = season_slates[season_slates["game_date"] == nted_dt]
    if len(match) == 0:
        print(f"{year}: NTED date {nted_date} not found in slate data")
        continue

    row = match.iloc[0]
    rows.append({
        "year": year,
        "nted_date": nted_date,
        "nted_te_tds": int(row["te_tds"]),
        "nted_games": int(row["n_games"]),
        "nted_rate": round(row["te_rate"], 3),
        "season_avg_rate": round(season_slates["te_rate"].mean(), 3),
        "season_rank": int(row["rank"]),
        "n_sunday_slates": len(season_slates),
    })
    print(
        f"{year}  NTED={nted_date}  TDs={int(row['te_tds']):2d}  "
        f"games={int(row['n_games']):2d}  rate={row['te_rate']:.2f}  "
        f"rank={int(row['rank'])}/{len(season_slates)}"
    )

results = pd.DataFrame(rows)
results.to_csv(DATA / "nted_results.csv", index=False)

print("\n=== Permutation test (sum-of-ranks, lower = better) ===")
np.random.seed(42)
N_PERM = 10_000

obs_sum = results["season_rank"].sum()
null_sums = []
for _ in range(N_PERM):
    s = sum(
        np.random.randint(1, r["n_sunday_slates"] + 1)
        for _, r in results.iterrows()
    )
    null_sums.append(s)

null_arr = np.array(null_sums)
p_val = (null_arr <= obs_sum).mean()
expected_sum = sum((r["n_sunday_slates"] + 1) / 2 for _, r in results.iterrows())

print(f"Observed sum-of-ranks : {obs_sum}")
print(f"Expected under null   : {expected_sum:.1f}")
print(f"p-value (one-sided ≤) : {p_val:.3f}")
print(f"n permutations        : {N_PERM}")

results["p_value"] = p_val
results["obs_rank_sum"] = obs_sum
results["null_expected_sum"] = round(expected_sum, 1)
results.to_csv(DATA / "nted_results.csv", index=False)
print("\nSaved data/nted_results.csv")
