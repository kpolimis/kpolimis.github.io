"""Generate figures for the "Wins Without Rings" post.

Run from the post directory:
    conda run -n blog python make_figures.py

Outputs:
    figures/fig1_league_panels.png   — per-league win% dot plots
    figures/fig2_wins_vs_titles.png  — win% z-score vs. championships scatter
"""

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "teams_2020s.csv"
FIGDIR = HERE / "figures"

mpl.rcParams.update(
    {
        "figure.dpi": 150,
        "figure.figsize": (9, 5.5),
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.linewidth": 0.5,
        "grid.alpha": 0.4,
    }
)

# Okabe-Ito palette, one color per league (consistent across both figures).
OKABE_ITO = [
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#000000",
]

# Panel order: MLB/NBA top pair, NFL/NHL, MLS/NWSL, WNBA alone.
PANEL_ORDER = ["MLB", "NBA", "NFL", "NHL", "MLS", "NWSL", "WNBA"]
LEAGUE_COLORS = dict(zip(PANEL_ORDER, OKABE_ITO))


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA)
    df["created_after_2020_01_01"] = df["created_after_2020_01_01"].astype(bool)
    return df


def scatter_split(ax, sub, x, y, sizes, color):
    """Scatter with filled markers for established teams, hollow for expansion."""
    est = ~sub["created_after_2020_01_01"]
    exp = sub["created_after_2020_01_01"]
    ax.scatter(
        x[est], y[est], s=sizes[est], color=color, edgecolors=color,
        linewidths=1.2, zorder=3,
    )
    ax.scatter(
        x[exp], y[exp], s=sizes[exp], facecolors="none", edgecolors=color,
        linewidths=1.4, zorder=3,
    )


def make_fig1(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(4, 2, figsize=(14, 28))
    axes = axes.ravel()

    for i, league in enumerate(PANEL_ORDER):
        ax = axes[i]
        color = LEAGUE_COLORS[league]
        sub = df[df["league"] == league].sort_values("win_pct", ascending=False)
        sub = sub.reset_index(drop=True)
        ypos = pd.Series(range(len(sub)))  # 0 = best team, plotted at top
        sizes = 60 + 40 * sub["titles_2020s"]

        scatter_split(ax, sub, sub["win_pct"], ypos, sizes, color)

        ax.set_yticks(ypos)
        ax.set_yticklabels(sub["short_name"], fontsize=9)
        ax.invert_yaxis()  # top team at top
        ax.set_ylim(len(sub) - 0.5, -0.5)
        ax.set_xlabel("Win %")
        ax.set_title(league, fontsize=13, fontweight="bold", color="#222222")
        ax.grid(axis="y", alpha=0.2)

    # Eighth panel: blank canvas hosting the shared legend.
    legend_ax = axes[7]
    legend_ax.axis("off")
    gray = "#555555"
    handles = [
        Line2D([], [], marker="o", linestyle="", color=gray,
               markersize=8, label="Established franchise"),
        Line2D([], [], marker="o", linestyle="", markerfacecolor="none",
               markeredgecolor=gray, markersize=8,
               label="Created after Jan 1, 2020"),
        Line2D([], [], marker="o", linestyle="", color=gray,
               markersize=(60 ** 0.5), label="0 titles"),
        Line2D([], [], marker="o", linestyle="", color=gray,
               markersize=(100 ** 0.5), label="1 title"),
        Line2D([], [], marker="o", linestyle="", color=gray,
               markersize=(180 ** 0.5), label="3 titles"),
    ]
    legend_ax.legend(
        handles=handles, loc="upper left", frameon=False, fontsize=11,
        title="Marker key", title_fontsize=12, labelspacing=1.2,
    )

    # Figure is very tall, so header spacing needs generous figure-fraction
    # gaps; bbox_inches="tight" picks up text above y=1.
    fig.suptitle(
        "Win % in the 2020s — within-league rankings",
        fontsize=18, fontweight="bold", y=1.012,
    )
    fig.text(
        0.5, 1.0,
        "Dot size = championships won. Hollow circles = franchises created "
        "after Jan 1, 2020. Data: Jan 2020–Oct 2026.",
        ha="center", fontsize=12, color="#444444",
    )
    fig.tight_layout()
    out = FIGDIR / "fig1_league_panels.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def make_fig2(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(4, 2, figsize=(12, 16), sharex=True, sharey=True)
    axes = axes.ravel()

    y_max = df["titles_2020s"].max() + 0.5
    t_min, t_max = df["years_in_window"].min(), df["years_in_window"].max()

    def size_scale(years):
        return 40 + (years - t_min) / (t_max - t_min) * 160

    for i, league in enumerate(PANEL_ORDER):
        ax = axes[i]
        color = LEAGUE_COLORS[league]
        sub = df[df["league"] == league]
        sizes = size_scale(sub["years_in_window"])

        ax.axvline(0, linestyle="--", color="#999999", linewidth=1, zorder=1)
        ax.text(
            0, y_max - 0.08, "League avg", ha="center", va="top",
            fontsize=8, color="#777777",
        )
        scatter_split(
            ax, sub, sub["win_pct_z_in_league"], sub["titles_2020s"],
            sizes, color,
        )

        # Label notable outliers: high win% with no ring, or multi-champions.
        notable = sub[
            ((sub["titles_2020s"] == 0) & (sub["win_pct_z_in_league"] > 1.5))
            | (sub["titles_2020s"] >= 2)
        ].sort_values("win_pct_z_in_league")
        prev = None  # (x, y) of last label, to dodge close neighbors
        for _, row in notable.iterrows():
            x, y = row["win_pct_z_in_league"], row["titles_2020s"]
            offset, va = (0, 9), "bottom"
            if prev is not None and prev[1] == y and abs(x - prev[0]) < 0.7:
                offset, va = (0, -12), "top"  # drop below to avoid overlap
            ax.annotate(
                row["short_name"], (x, y),
                textcoords="offset points", xytext=offset,
                ha="center", va=va, fontsize=8, color="#333333",
            )
            prev = (x, y)

        ax.set_xlim(-2.5, 2.5)
        ax.set_ylim(-0.3, y_max)
        ax.set_yticks(range(int(df["titles_2020s"].max()) + 1))
        ax.set_title(league, fontsize=13, fontweight="bold", color="#222222")

    axes[7].axis("off")

    # Shared axis labels.
    for i in (4, 5, 6):  # bottom-most visible panel in each column + WNBA
        axes[i].tick_params(labelbottom=True)
    fig.supxlabel("Win % (z-score within league)", fontsize=12)
    fig.supylabel("Championships won", fontsize=12)

    fig.suptitle(
        "High win % doesn't guarantee championships",
        fontsize=17, fontweight="bold", y=0.99,
    )
    fig.text(
        0.5, 0.965,
        "Dot size = seasons of data (larger = more certain). x-axis is "
        "standardized within each league. Data: Jan 2020–Oct 2026.",
        ha="center", fontsize=11, color="#444444",
    )
    fig.tight_layout(rect=(0.02, 0.02, 1, 0.955))
    out = FIGDIR / "fig2_wins_vs_titles.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def main() -> None:
    FIGDIR.mkdir(exist_ok=True)
    df = load_data()
    make_fig1(df)
    make_fig2(df)


if __name__ == "__main__":
    main()
