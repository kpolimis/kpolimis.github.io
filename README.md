# kpolimis.github.io

[![Publish](https://github.com/kpolimis/kpolimis.github.io/actions/workflows/publish.yml/badge.svg)](https://github.com/kpolimis/kpolimis.github.io/actions/workflows/publish.yml)

Source for [kivanpolimis.com](https://kivanpolimis.com), built with [Quarto](https://quarto.org) and deployed to GitHub Pages on every push to `main`.

The site migrated from Pelican in 2026.

## Local development

```bash
conda activate blog
quarto preview
```

`quarto preview` starts a local server at `localhost:4848` and live-reloads on file changes. Code blocks with `freeze: auto` won't re-execute unless you edit the source file — run `quarto render <post-dir> --execute` to force re-execution for a specific post.

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
