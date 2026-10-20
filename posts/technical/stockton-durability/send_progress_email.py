#!/usr/bin/env python3
"""Render NBA durability project progress docs to PDF and email via claude-notify.

Usage:
    # E8 completion report (default)
    conda run -n blog python send_progress_email.py

    # Arbitrary subject override
    conda run -n blog python send_progress_email.py --subject "Custom subject"

    # Dry run — build PDFs but do not send
    conda run -n blog python send_progress_email.py --no-email

Generates two PDFs:
    1. project-status.pdf  — rendered from docs/project-status.md (full project tracker)
    2. e8-progress.pdf     — live E8 fetch stats + top-50 player list + parquet inventory

Models after ~/repos/homelab-docs/scripts/steve_md_to_pdf_email.py (weasyprint pattern)
but uses pandoc (available in PATH) since weasyprint is not in the blog conda env.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DOCS_DIR = SCRIPT_DIR / "docs"
OUT_DIR = DOCS_DIR / "pdf"


# ── Pandoc helpers ────────────────────────────────────────────────────────────

PANDOC_FLAGS = [
    "--pdf-engine=xelatex",
    "-V", "geometry:margin=1in",
    "-V", "fontsize=11pt",
    "-V", "colorlinks=true",
    "-V", "linkcolor=NavyBlue",
    "--highlight-style=tango",
    "--toc",
    "--toc-depth=2",
]

PANDOC_FLAGS_NOTOC = [
    "--pdf-engine=xelatex",
    "-V", "geometry:margin=1in",
    "-V", "fontsize=11pt",
    "-V", "colorlinks=true",
    "-V", "linkcolor=NavyBlue",
    "--highlight-style=tango",
]


def _render_pdf(md_path: Path, out_path: Path, toc: bool = True) -> bool:
    """Render a markdown file to PDF via pandoc. Returns True on success."""
    flags = PANDOC_FLAGS if toc else PANDOC_FLAGS_NOTOC
    cmd = ["pandoc", "-f", "markdown", "-t", "pdf", *flags, str(md_path), "-o", str(out_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and out_path.exists():
            size_kb = out_path.stat().st_size // 1024
            logger.info("Rendered %s  (%d KB)", out_path.name, size_kb)
            return True
        # Retry without xelatex on engine failure
        cmd_fb = ["pandoc", "-f", "markdown", "-t", "pdf",
                  "-V", "geometry:margin=1in", str(md_path), "-o", str(out_path)]
        r2 = subprocess.run(cmd_fb, capture_output=True, text=True)
        if r2.returncode == 0 and out_path.exists():
            logger.info("Rendered %s via fallback engine", out_path.name)
            return True
        logger.error("pandoc failed for %s:\n%s", md_path.name, r.stderr or r2.stderr)
        return False
    except FileNotFoundError:
        logger.error("pandoc not found in PATH")
        return False


# ── E8 live stats ─────────────────────────────────────────────────────────────

def _e8_fetch_stats() -> dict:
    """Pull live E8 fetch stats from Apollo container logs + parquet inventory."""
    stats: dict = {
        "container_status": "unknown",
        "log_tail": "",
        "parquet_rows": 0,
        "parquet_players": 0,
        "parquet_size_mb": 0.0,
    }

    # Container status
    r = subprocess.run(
        ["ssh", "apollo",
         "docker ps -a --filter name=bref-qs-fetch --format '{{.Status}}'"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        stats["container_status"] = r.stdout.strip() or "not found"

    # Log tail
    r = subprocess.run(
        ["ssh", "apollo", "docker logs --tail 40 bref-qs-fetch 2>&1"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        stats["log_tail"] = r.stdout.strip()

    # Parquet inventory on Apollo
    r = subprocess.run(
        ["ssh", "apollo",
         """python3 -c "
import sys
try:
    import pyarrow.parquet as pq, os
    p='/home/kivan/repos/stockton-pop/data/quarter_splits_e8.parquet'
    if os.path.exists(p):
        t=pq.read_table(p)
        ids=t.column('player_id').to_pylist()
        print(f'{len(t):,}|{len(set(ids))}|{os.path.getsize(p)/1e6:.1f}')
    else:
        print('0|0|0')
except Exception as e:
    print(f'err:{e}')
" """],
        capture_output=True, text=True,
    )
    if r.returncode == 0 and "|" in r.stdout:
        parts = r.stdout.strip().split("|")
        if len(parts) == 3:
            stats["parquet_rows"] = int(parts[0].replace(",", ""))
            stats["parquet_players"] = int(parts[1])
            stats["parquet_size_mb"] = float(parts[2])

    # Also check local copy
    local_e8 = DATA_DIR / "quarter_splits_e8.parquet"
    if local_e8.exists():
        try:
            import pandas as pd
            df = pd.read_parquet(local_e8)
            stats["local_rows"] = len(df)
            stats["local_players"] = df["player_id"].nunique()
        except Exception:
            pass

    return stats


def _data_inventory() -> list[dict]:
    """List all parquet files in data/ with row counts."""
    inventory = []
    for p in sorted(DATA_DIR.glob("*.parquet")):
        row = {"name": p.name, "size_mb": p.stat().st_size / 1e6, "rows": None}
        try:
            import pandas as pd
            df = pd.read_parquet(p)
            row["rows"] = len(df)
        except Exception:
            pass
        inventory.append(row)
    return inventory


# ── Report generators ──────────────────────────────────────────────────────────

def _build_e8_progress_md(stats: dict, inventory: list[dict]) -> str:
    """Build the E8 progress report markdown."""
    rows_k = f"{stats['parquet_rows']:,}"
    players = stats['parquet_players']
    size = stats['parquet_size_mb']
    status = stats['container_status']
    log = stats['log_tail']

    inv_table = "| File | Rows | Size (MB) |\n|:--|--:|--:|\n"
    for item in inventory:
        rows_str = f"{item['rows']:,}" if item['rows'] is not None else "—"
        inv_table += f"| `{item['name']}` | {rows_str} | {item['size_mb']:.1f} |\n"

    top50_section = """
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
"""

    return f"""---
title: "NBA Durability Series — E8 Progress Report"
date: "2026-10-19"
---

# NBA Durability Series — E8 Progress Report

**Generated:** 2026-10-19
**Project:** 3-Post NBA Durability Series (Stockton / Diaw / Population)

---

## E8 Fetch Status (Apollo `bref-qs-fetch`)

**Container status:** `{status}`

| Metric | Value |
|:-------|------:|
| Rows in `quarter_splits_e8.parquet` (Apollo) | {rows_k} |
| Players with data | {players} |
| Parquet size | {size:.1f} MB |
| Total games in scope | 59,837 |
| Players in scope | 50 |

### Container Logs (tail)

```
{log}
```

---

## Top-50 Players by Active Games (E8 Cohort)

Stockton is rank 3 (1,504 games), confirming he is in the cohort.
{top50_section}

---

## Local Data Inventory

{inv_table}

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
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    """Render progress docs to PDF and email the result."""
    ap = argparse.ArgumentParser(description="Render progress docs to PDF and email.")
    ap.add_argument("--no-email", action="store_true", help="Build PDFs but skip sending.")
    ap.add_argument("--subject", default=None, help="Override email subject line.")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)

    # PDF 1: project-status.md → project-status.pdf
    ps_src = DOCS_DIR / "project-status.md"
    ps_pdf = OUT_DIR / "project-status.pdf"
    ok1 = _render_pdf(ps_src, ps_pdf, toc=False)

    # PDF 2: E8 progress report
    logger.info("Pulling E8 stats from Apollo...")
    stats = _e8_fetch_stats()
    inventory = _data_inventory()
    e8_md_text = _build_e8_progress_md(stats, inventory)

    e8_md_path = OUT_DIR / "e8-progress.md"
    e8_md_path.write_text(e8_md_text, encoding="utf-8")
    e8_pdf = OUT_DIR / "e8-progress.pdf"
    ok2 = _render_pdf(e8_md_path, e8_pdf, toc=False)

    pdfs = [p for p, ok in [(ps_pdf, ok1), (e8_pdf, ok2)] if ok and p.exists()]

    if args.no_email:
        logger.info("--no-email set. PDFs: %s", [str(p) for p in pdfs])
        return 0

    if not pdfs:
        logger.error("No PDFs built — aborting email.")
        return 1

    sys.path.insert(0, str(Path("~/repos/claude-notify").expanduser()))
    from claude_notify import notify  # type: ignore

    rows_k = f"{stats['parquet_rows']:,}"
    players = stats['parquet_players']
    container = stats['container_status']
    subject = args.subject or (
        f"[stockton] E8 fetch update — {rows_k} rows, {players}/50 players"
    )

    body = f"""**NBA Durability Series — E8 Progress Update**

**E8 container status:** `{container}`

| Metric | Value |
|:-------|------:|
| Rows fetched (Apollo parquet) | {rows_k} |
| Players with data | {players}/50 |

**Completed analyses:** E1 (durability, 738 players), E3 (B2B shot selection), E7 (career TS%, rank 10/464).

**Post 3 draft** written (`nba-durability-population/index.qmd`). All three posts set to `draft: true`.

**Attached:**
1. `project-status.pdf` — full project tracker (scripts, data, analyses, CI status)
2. `e8-progress.pdf` — E8 fetch stats, top-50 cohort, data inventory, completed analyses

10 commits ahead of origin; push pending your approval.
"""

    ok = notify(
        subject=subject,
        body=body,
        attachments=[str(p) for p in pdfs],
        status="info",
        _bypass_cooldown=True,
    )
    if ok:
        logger.info("Email sent OK")
    else:
        logger.error("Email FAILED — check claude-notify config")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
