"""NTED figures — run after analysis.py.

conda run -n blog python make_figures.py
"""

import pathlib

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd

DATA = pathlib.Path("data")
FIGS = pathlib.Path("figures")
FIGS.mkdir(exist_ok=True)

results = pd.read_csv(DATA / "nted_results.csv")
slates = pd.read_csv(DATA / "sunday_slates.csv", parse_dates=["game_date"])

BLUE = "#2166ac"
GRAY = "#aaaaaa"
RED = "#d6604d"

# ── Figure 1: rank dot plot ─────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 5))

for _, row in results.iterrows():
    year = int(row["year"])
    n = int(row["n_sunday_slates"])
    # grey dots for all other ranks
    other_ranks = [r for r in range(1, n + 1) if r != row["season_rank"]]
    ax.scatter(
        [year] * len(other_ranks), other_ranks,
        color=GRAY, s=18, zorder=2, alpha=0.6,
    )
    # NTED dot
    ax.scatter(
        year, row["season_rank"],
        color=BLUE, s=80, zorder=3, label="_nted" if year != 2018 else "NTED slate",
    )
    ax.annotate(
        f"{int(row['season_rank'])}",
        (year, row["season_rank"]),
        textcoords="offset points", xytext=(6, 0),
        fontsize=8, color=BLUE, va="center",
    )

ax.invert_yaxis()
ax.set_xlabel("Season")
ax.set_ylabel("Rank (1 = most TE TDs/game that season)")
ax.set_title("National Tight End Day: TE TD slate rank within season", fontsize=12)
ax.xaxis.set_major_locator(ticker.MultipleLocator(1))
ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: str(int(x))))
ax.set_xlim(2017.3, 2025.7)
ax.legend(loc="lower left", fontsize=9)
ax.spines[["top", "right"]].set_visible(False)
ax.grid(axis="y", linestyle="--", alpha=0.3)

plt.tight_layout()
fig.savefig(FIGS / "nted_rank_by_year.png", dpi=150)
plt.close()
print("saved nted_rank_by_year.png")

# ── Figure 2: NTED rate vs season average ───────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 5))

x = range(len(results))
bar_w = 0.35

nted_rates = results["nted_rate"].values
avg_rates = results["season_avg_rate"].values
years = results["year"].astype(int).values

bars_avg = ax.bar(
    [i - bar_w / 2 for i in x], avg_rates,
    width=bar_w, color=GRAY, label="Season Sunday avg", alpha=0.8,
)
bars_nted = ax.bar(
    [i + bar_w / 2 for i in x], nted_rates,
    width=bar_w, color=BLUE, label="NTED slate", alpha=0.9,
)

# annotate 2024 with measurement note
idx_2024 = list(years).index(2024)
ax.annotate(
    "16 TDs\n(media: 17)",
    xy=(idx_2024 + bar_w / 2, nted_rates[idx_2024]),
    xytext=(idx_2024 + bar_w / 2 + 0.45, nted_rates[idx_2024] + 0.12),
    fontsize=7.5, color=BLUE,
    arrowprops=dict(arrowstyle="-", color=BLUE, lw=0.8),
)

# annotate 2022 dead-last
idx_2022 = list(years).index(2022)
ax.annotate(
    "18th/18",
    xy=(idx_2022 + bar_w / 2, nted_rates[idx_2022] + 0.01),
    xytext=(idx_2022 + bar_w / 2 - 0.5, nted_rates[idx_2022] + 0.25),
    fontsize=7.5, color=RED,
    arrowprops=dict(arrowstyle="-", color=RED, lw=0.8),
)

ax.set_xticks(list(x))
ax.set_xticklabels(years)
ax.set_ylabel("TE TDs per game")
ax.set_title("NTED TE TD rate vs. season Sunday average", fontsize=12)
ax.legend(fontsize=9)
ax.spines[["top", "right"]].set_visible(False)
ax.grid(axis="y", linestyle="--", alpha=0.3)

plt.tight_layout()
fig.savefig(FIGS / "nted_rate_vs_baseline.png", dpi=150)
plt.close()
print("saved nted_rate_vs_baseline.png")
