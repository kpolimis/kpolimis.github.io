---
title: "NBA Durability Series — E8 Progress Report"
date: "2026-10-19"
---

# NBA Durability Series — E8 Progress Report

**Generated:** 2026-10-19
**Project:** 3-Post NBA Durability Series (Stockton / Diaw / Population)

---

## E8 Fetch Status (Apollo `bref-qs-fetch`)

**Container status:** `Up 17 minutes`

| Metric | Value |
|:-------|------:|
| Rows in `quarter_splits_e8.parquet` (Apollo) | 0 |
| Players with data | 0 |
| Parquet size | 0.0 MB |
| Total games in scope | 59,837 |
| Players in scope | 50 |

### Container Logs (tail)

```
oaklech01    1205
perkisa01    1204
johnsjo02    1200
harpede01    1199
greenac01    1196
derozde01    1187
lowryky01    1177
thorpot01    1175
conlemi01    1173
greenje02    1167
mariosh01    1163
korveky01    1158
hardeja01    1145
howarju01    1143
ellisda01    1142
batumni01    1126
johnsed03    1125
duranke01    1121
cummite01    1113
jefferi01    1102
horfoal01    1102
newmajo01    1100
lopezbr01    1098
youngth01    1098
stricro02    1094
willilo02    1093
chandty01    1089
grantho01    1084
jamisan01    1083
kerseje01    1076
randoza01    1075
schrede01    1072
jordade01    1070
INFO | Players (50): ['jamesle01', 'nowitdi01', 'stockjo01', 'kiddja01', 'willike02', 'paytoga01', 'terryja01', 'robincl02', 'jacksma01', 'paulch01', 'portete01', 'crawfja01', 'willibu01', 'millean02', 'westbru01', 'nashst01', 'fishede01', 'oaklech01', 'perkisa01', 'johnsjo02', 'harpede01', 'greenac01', 'derozde01', 'lowryky01', 'thorpot01', 'conlemi01', 'greenje02', 'mariosh01', 'korveky01', 'hardeja01', 'howarju01', 'ellisda01', 'batumni01', 'johnsed03', 'duranke01', 'cummite01', 'jefferi01', 'horfoal01', 'newmajo01', 'lopezbr01', 'youngth01', 'stricro02', 'willilo02', 'chandty01', 'grantho01', 'jamisan01', 'kerseje01', 'randoza01', 'schrede01', 'jordade01']
INFO | Output: data/quarter_splits_e8.parquet
INFO | Season range: all
INFO | Game index: 59837 games for 50 player(s) (season range: all)
INFO | Session cooldown (40 pages) — sleeping 120s
INFO | Session cooldown (80 pages) — sleeping 120s
INFO | Session cooldown (120 pages) — sleeping 120s
```

---

## Top-50 Players by Active Games (E8 Cohort)

Stockton is rank 3 (1,504 games), confirming he is in the cohort.

| Rank | player_id | Games |
|------|-----------|-------|
| 1 | jamesle01 | 1,543 |
| 2 | nowitdi01 | 1,522 |
| 3 | stockjo01 | 1,504 |
| 4 | kiddja01 | 1,391 |
| 5 | willike02 | 1,342 |
| 6 | paytoga01 | 1,335 |
| 7 | terryja01 | 1,329 |
| 8 | robincl02 | 1,298 |
| 9 | jacksma01 | 1,296 |
| 10 | paulch01 | 1,292 |
| … | *(40 more)* | *(1,072–1,274)* |


---

## Local Data Inventory

| File | Rows | Size (MB) |
|:--|--:|--:|
| `e1_pf_permutation.parquet` | 5,000 | 0.0 |
| `e1_pg_permutation.parquet` | 5,000 | 0.0 |
| `e1_test2_permutation.parquet` | 200 | 0.0 |
| `e1_test_permutation.parquet` | 100 | 0.0 |
| `e2_pf_permutation.parquet` | 5,000 | 0.0 |
| `e2_pg_permutation.parquet` | 5,000 | 0.0 |
| `e4_pf_permutation.parquet` | 5,000 | 0.0 |
| `e4_pg_permutation.parquet` | 5,000 | 0.0 |
| `e5_pf_permutation.parquet` | 5,000 | 0.0 |
| `e5_pg_permutation.parquet` | 5,000 | 0.0 |
| `game_logs.parquet` | 656,839 | 16.8 |
| `quarter_splits_pf.parquet` | 13,689 | 0.1 |
| `quarter_splits_pg.parquet` | 5,585 | 0.1 |
| `season_splits.parquet` | 665,598 | 7.2 |


---

## Completed Analyses

| Estimand | Cohort | Key Result |
|:---------|:-------|:-----------|
| **E1** (durability) | 738 players ≥400 games | Stockton: **0.3rd pctile** (rank 2/738); Diaw: 2.7th pctile |
| **E1** sensitivity | 600-game | Stockton: 0.4th pctile; Diaw: 3.8th |
| **E1** sensitivity | 820-game (10-yr) | Stockton: 0.9th pctile; Diaw: 6.9th |
| **E3** (B2B shot selection) | 738 players | Stockton: FTA/FGA −0.049 on B2Bs (largest in PG cohort) |
| **E7** (career TS%) | 464 players ≥5,000 TSA | Stockton: **rank 10/464** (98.1st pctile, p=0.022), highest PG |
| **E8** (Q4 vs Q1–Q3 TS%) | Top-50 most-durable | **In progress** |

### Estimands Dropped

| Estimand | Reason |
|:---------|:-------|
| E4 (Q4 AST/TOV) | Degenerate — 52% zero-TOV rows at quarter resolution |
| E5 (Q4 TS%) | Degenerate — 21% per-quarter data coverage |

---

## Post Drafts

| Post | Status | Draft location |
|:-----|:-------|:--------------|
| Post 1: Stockton | **Published** (draft: true) | `posts/technical/stockton-durability/` |
| Post 2: Diaw | **Published** (draft: true) | `posts/technical/diaw-35bpm/` |
| Post 3: Population | **Draft written** | `posts/technical/nba-durability-population/index.qmd` |

All three posts currently have `draft: true`. Not yet pushed to origin.

---

## Pending

1. E8 fetch completion (est. 60–70h total from launch)
2. rsync `quarter_splits_e8.parquet` to local + commit
3. Run E8 analysis (Fable 5 review)
4. Push 10 local commits to origin + verify CI
5. Season splits analysis script (`analyze_season_splits.py`)
