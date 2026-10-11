---
title: "Can We See John Stockton's Heart Rate in the Box Score?"
subtitle: "3-Post NBA Durability Series — Status 2026-10-10 (v2)"
geometry: "margin=0.75in"
fontsize: 10pt
linestretch: 1.0
header-includes:
  - \usepackage{booktabs}
  - \usepackage{longtable}
  - \usepackage{array}
  - \usepackage{titling}
  - \setlength{\droptitle}{-2em}
  - \renewcommand{\maketitlehookd}{\vspace{-3.5em}}
  - \usepackage{titlesec}
  - \titlespacing*{\subsection}{0pt}{5pt}{1pt}
  - \setlength{\tabcolsep}{4pt}
  - \renewcommand{\arraystretch}{1.05}
  - \usepackage{parskip}
  - \setlength{\parskip}{2pt}
colorlinks: true
---

## The Premise

John Stockton and Boris Diaw reportedly share a resting heart rate of ~35 BPM — well below the elite-athlete norm of ~50 BPM. The question: does that physiology leave a detectable trace in box-score data as statistical resilience — fewer missed games, steadier late-game performance, more durable decision-making under fatigue? Stockton's durability is currently circulating on social media, providing a natural hook.

## Post Structure

| Post | Subject | Data Window |
|:-----|:--------|:------------|
| 1 | John Stockton + 14 PG comps | E1/E3 full career 1984–2003; E2/E4/E5 1996–2003 only |
| 2 | Boris Diaw + 5 PF comps (Nowitzki, Boozer, Jamison, Marion, Lewis) | 2004–2016, full BRef |
| 3 | All qualifying BRef-era guards + forwards + centers | 1980–2010 debuts |

Stockton ships first to ride the current conversation; Diaw follows immediately as independent methodological confirmation — different position, different era, full BRef coverage, no age-regime caveat. Post 3 addresses the cherry-picking objection: placing both players in the full distribution of all BRef-era players who meet the career-length threshold.

## Estimands

| | Metric | Data Tier | Status |
|:--|:-------|:----------|:-------|
| **E1** | Games missed per 82 — career durability | Game logs | **Done — both cohorts** |
| **E3** | Shot selection: 3PA/FGA, FTA/FGA on B2B vs rest | Game logs | **Done — both cohorts** |
| **E2** | 4Q FT% degradation vs Q1–Q3 | Quarter box scores | **Done (PG) — Stockton +4.1 pp, only improver; PF pending** |
| **E4** | 4Q AST/TOV ratio vs full-game | Quarter box scores | **Degenerate at quarter resolution (52% zero-TOV rows); dropped** |
| **E5** | 4Q TS% vs Q1–Q3 | Quarter box scores | **Degenerate (21% coverage per quarter); dropped** |
| **E6** | Full Q1→Q2→Q3→Q4 scoring profile | Quarter box scores | Proposed; no new scraping needed |

E1 and E3 are primary. E6 (profile plot) requires no new data — a subplot within the E2/E4/E5 analysis.

## Inference Approach

E1's denominator corrects for lockout-shortened seasons: 1999→50 games, 2012→66, 2020→65, 2021→72.

**n_treated = 1** makes bootstrap CIs invalid. For E1/E3: resample the treatment label across all N cohort players 5,000 times; report where the observed gap falls in the null distribution. For E2/E4/E5: mixed-effects model `metric ~ quarter * is_treated + rest_days + (1|player_id)` via `statsmodels.MixedLM`; permutation resamples `is_treated` at the player level (not game level) to preserve within-player correlation.

## Current Status

**Infrastructure: complete.** 131 tests passing across four scripts:

| Script | Purpose |
|:-------|:--------|
| `fetch_bref_data.py` | BRef game log scraper; HTML-cached per (player, season); 4 sec/request |
| `analyze_durability.py` | E1 + E3; OLS + permutation; emits `{cohort}_comparators.csv` |
| `fetch_quarter_splits.py` | Quarter box score scraper; cached by game ID; 3.5s/request + jitter |
| `analyze_quarter_splits.py` | E2/E4/E5; mixed-effects model; player-level permutation |

**Data fetch: mostly complete for PG; PF quarter splits not started.**

| Status | Players |
|:-------|:--------|
| Full PG game logs + quarter splits | Stockton, Payton, Jackson, Harper |
| Full PG game logs only | Thomas, Hardaway, K. Johnson, Porter, Bogues, Strickland, Kidd, Nash, Blaylock, Anderson, Douglas |
| PF game logs complete (all 6) | Diaw, Nowitzki, Boozer, Jamison, Marion, Lewis |
| PF quarter splits | Not started |
| Population (Apollo) | 232 / 1,995 players — running (~4 days remaining) |

**Post drafts:**

| Post | E1/E3 | E2/E4/E5 | Status |
|:-----|:------|:---------|:-------|
| Stockton | Written | **E2 written; E4/E5 dropped (degenerate)** | Draft — complete |
| Diaw | Written | Pending PF quarter splits | Draft — E2 pending |
| Population | — | — | Outline only |

## Caveats (mandatory in every post)

1. **Selection-on-outcome bias** — >=600-game threshold conditions on the dependent variable; E1 estimates durability *among players who completed long careers*, not all players.
2. **B2B state selection** — playing a B2B selects healthier player-states; within-player pairing removes stable effects but not selection.
3. **Blowout/garbage time** — starters sit in non-competitive games; 4Q minutes are not random. Compresses treatment effect toward zero.
4. **Intentional fouling** — close-game FTA inflation in Q4; FT% estimates partly reflect pressure context, not just physical state.
5. **Timeout-adjusted rest** — unmeasured confounder; coaches use Q4 timeouts strategically.
6. **Age-regime** — Stockton's quarter data covers ages 34–40 (career decline). A null within-game result does not contradict a prime-years resilience claim.
7. **Pre-1996 quarter gap** — BRef play-by-play starts 1996-97; only Stockton ages 34–40 are covered. Justin Jacobs (Squared Statistics) has video-reconstructed pre-1996 quarter logs that would extend the window to his prime (ages 22–33). Outreach drafted, not sent.
8. **No causality** — frame consistently as "consistent with" and "does not contradict."

## What's Left

| Step | Blocker | Est. |
|:-----|:--------|:-----|
| E2/E4/E5 prose → Stockton post | **Done** | — |
| PF quarter splits fetch | None — run now | ~4h |
| E2 analysis + prose → Diaw post | PF quarter splits | ~2h |
| Remaining 11 PG quarter splits | Optional; E1/E3 sufficient for Post 1 | ~8h |
| Population fetch (Apollo) | Running — ETA ~Oct 14 | ~4 days |
| Population analysis + post | Population fetch complete | 1 day |
| Jacobs outreach (#22) — manual browser form | Human action required | 20 min |

---

**NOTE:** Causal language forbidden. Null results are valid findings — state them plainly. Sourcing asymmetry: Diaw's 35 BPM comes from documented post-retirement interviews; the Stockton figure is less sourced — acknowledge this explicitly in the Stockton post.

---

## Changelog

### v2 — 2026-10-10 (updated same day)
- BRef ID fixes: Bogues (`boguemu01`), Harper (`harpede01`), Strickland (`stricro02`) — PG cohort grew from 12 → 15 players
- E1 + E3 analysis complete for both PG (15 players) and PF (6 players)
- Stockton post drafted with E1/E3 results; E2/E4/E5 sections stubbed pending figures
- Diaw post drafted with E1/E3 results; E2/E4/E5 sections stubbed
- Quarter splits fetched for Payton, Jackson, Harper, Stockton (5,585 rows)
- E2/E4/E5 analysis run for PG cohort; E2 interpretable (Stockton Q4 FT% +4.1 pp, only improver, p=0.494 at floor); E4/E5 dropped — degenerate at per-quarter resolution (52% zero-TOV rows; 21% TS% coverage)
- Stockton post now complete draft (E1/E3/E2 written; E4/E5 explained as methodologically degenerate)
- Population fetch scope expanded to include centers; running on Apollo (232/1,995 players, 99,883 rows)
- Population cohort size: 1,995 players (guards + forwards + centers, debuts 1980–2010)
- Fixed 5 bugs in `fetch_quarter_splits.py`: Age column KeyError, rate limit (0.35s→3.5s+jitter), 429 backoff, game_id Tm→Team column, season range (1996→1997)
- Fixed parallel `--player` race condition in `fetch_bref_data.py` with `fcntl.flock()`

### v1 — 2026-10-09
- Initial status document; infrastructure complete (131 tests); data fetch incomplete
