# kpolimis.github.io

[![Publish](https://github.com/kpolimis/kpolimis.github.io/actions/workflows/publish.yml/badge.svg)](https://github.com/kpolimis/kpolimis.github.io/actions/workflows/publish.yml)

Source for [kivanpolimis.com](https://kivanpolimis.com), built with [Quarto](https://quarto.org) and deployed to GitHub Pages on every push to `main`.

The site migrated from Pelican in 2026.

## Local development

### First-time setup

```bash
conda activate blog
pip install -r requirements.txt
make bootstrap          # installs footy (local editable) + soccerdata
```

`footy` is a local package at `~/repos/football/footy` — not on PyPI. `make bootstrap` handles the `pip install -e` step. If the path differs on your machine, install it manually:

```bash
pip install -e /path/to/football/footy
```

### Day-to-day

```bash
conda activate blog
quarto preview
```

`quarto preview` starts a local server at `localhost:4848` and live-reloads on file changes. Code blocks with `freeze: auto` won't re-execute unless you edit the source file — run `quarto render <post-dir> --execute` to force re-execution for a specific post.

### Makefile targets

```bash
make all              # fetch WC data → render both WC posts end-to-end
make data             # fetch 2026 WC data (uses soccerdata cache)
make data-refresh     # re-fetch from FBref (opens Chrome for first run)
make render           # render full site (no re-execution)
make render-wc-epl    # re-execute and render EPL WC post
make render-wc-leagues # re-execute and render leagues WC post
make lint             # run Ruff linter across repo
make clean            # remove _site/, .quarto/, _freeze/
```

## Deployment

`publish.yml` renders the site and pushes the output to `gh-pages` on every merge to `main`. GitHub Pages serves from `gh-pages`. No manual deploy step needed.

## Structure

```
├── _quarto.yml          # site config and global execute settings
├── index.qmd            # home / about
├── technical.qmd        # Technical Articles listing
├── blog.qmd             # Blog listing
├── vita.qmd             # CV / Resume
├── teaching.qmd         # Teaching
├── software.qmd         # Software / OSS
├── posts/
│   ├── technical/       # data science, ML, sports analytics posts
│   └── blog/            # notes, how-tos, reviews
├── .drafts/             # posts in progress (not rendered)
├── images/              # site-wide images (from Pelican migration)
├── docs/                # PDFs and documents
└── downloads/           # code, notebooks, downloadable assets
```

Per-post images go directly into each post's directory under `posts/`.
