---
draft: true
---

# Team-season panel — data dictionary

Built by `../build_panel.py` (Stage 1 of the Week-1 overreaction study; see
`../method-spec.md`). Source: football-data.co.uk EPL CSVs (code E0) via
`footy_stats.sources.football_data.load_matches`, seasons 2008/09–2025/26
(codes `0809`–`2526`). 360 rows: one per team-season (18 seasons × 20 clubs).

## Files

| File | Contents |
|---|---|
| `matches/matches_<season>.parquet` | One tidy match frame per season (380 rows each), with a `season` column |
| `matches_all.parquet` | All 18 seasons concatenated (6,840 rows) |
| `panel.parquet` / `panel.csv` | The team-season panel (parquet is canonical; csv is for eyeballing) |

## The Week-1 match definition

A team's **Week-1 match** is its chronologically earliest fixture of the
season (minimum `date` in the match frame). In 16 of 18 seasons the 20
earliest fixtures collapse to exactly 10 matches — every team's opener is
also its opponent's opener. Two seasons deviate because openers were
postponed, so a team's first *played* match was originally a later round:

- **2011/12** (11 distinct W1 matches): Tottenham v Everton was postponed
  (London riots), so Tottenham's first fixture is Man United away
  (2011-08-22) and Everton's is QPR at home (2011-08-20).
- **2020/21** (12 distinct W1 matches): the COVID-shortened preseason gave
  Man United, Man City, Aston Villa, and Burnley a staggered start; their
  openers fall on 2020-09-19/20/21 against opponents already one game in.

In those cases the panel still records each team's genuine first fixture;
the de-vigged expectation is that match's own pre-match line, so
`week1_shock` remains a valid market-expectation residual.

## Columns

### Identity

| Column | Type | Definition |
|---|---|---|
| `season` | str | football-data 4-digit season code (`"0809"` = 2008/09 … `"2526"` = 2025/26) |
| `club_id` | str | footy club id (e.g. `epl:arsenal`) |

### Week-1 signal

| Column | Type | Definition |
|---|---|---|
| `home_week1` | bool | team played its W1 match at home |
| `week1_opponent_id` | str | footy club id of the W1 opponent |
| `week1_result` | str | `"W"` / `"D"` / `"L"` from this team's perspective (narrative only per spec) |
| `week1_points` | int | actual points from the W1 match: 3 / 1 / 0 |
| `week1_expected_points` | float | `3·p_win + 1·p_draw` from the de-vigged (Shin) B365 1X2 of the W1 match; `p_win` is the home probability if `home_week1` else the away probability |
| `week1_shock` | float | `week1_points − week1_expected_points` — the spec's primary fitted signal |
| `week1_odds_source` | str | which B365 triple supplied the W1 odds: `"b365c"` (closing; available 2019/20+), `"b365"` (opening fallback, 2008/09–2018/19), or `"none"` (never occurs in this build) |

### Indicators

| Column | Type | Definition |
|---|---|---|
| `newly_promoted` | boolean (nullable) | club absent from the previous season's panel; **NA for all of 2008/09** (earliest season — no prior season observed). Every other season has exactly 3 |
| `post_psr` | bool | season ≥ 2013/14 (PSR introduction) |
| `psr_enforcement` | bool | season ≥ 2023/24 (first points-deduction era) |
| `covid_restart` | bool | season ∈ {2019/20, 2020/21} |

### Season outcomes

| Column | Type | Definition |
|---|---|---|
| `final_points` | int | full-season points from match results (**note:** computed from results only — PSR points deductions, e.g. Everton/Forest 2023/24, are *not* applied) |
| `final_gd` | int | full-season goal difference |
| `final_position` | int | 1–20, ranked by points, then GD, then goals for |
| `made_top4` | bool | `final_position ≤ 4` |
| `relegated` | bool | `final_position ≥ 18` |

## Deliberately absent

`prior_strength`, `preseason_tier`, `week1_opponent_tier` — these require the
fitted seed/link from a later stage and are not stubbed here.

## Odds-coverage note

The method spec anticipated closing lines from ≈2012/13; in the fetched data
the `b365c*` columns only exist from **2019/20** onward. Seasons
2008/09–2018/19 therefore all fall back to opening B365 (`week1_odds_source
== "b365"`), and closing-line analyses are a 2019/20+ refinement.
