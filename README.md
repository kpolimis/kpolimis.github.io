# kpolimis.github.io-src

[![Deploy](https://github.com/kpolimis/kpolimis.github.io-src/actions/workflows/deploy.yml/badge.svg)](https://github.com/kpolimis/kpolimis.github.io-src/actions/workflows/deploy.yml)

Source repository for [kivanpolimis.com](https://kivanpolimis.com).

Built with [Quarto](https://quarto.org). Pushes to [kpolimis/kpolimis.github.io](https://github.com/kpolimis/kpolimis.github.io) on every merge to `master`.

## Local development

```bash
conda activate blog
quarto preview
```

## Structure

```
├── _quarto.yml          # site config
├── index.qmd            # home / about
├── technical.qmd        # Technical Articles listing
├── blog.qmd             # Blog listing
├── vita.qmd             # CV / Resume
├── teaching.qmd         # Teaching
├── software.qmd         # Software / OSS
├── projects.qmd         # Projects
├── posts/
│   ├── technical/       # data science, ML, sports analytics posts
│   └── blog/            # notes, reviews, how-tos
├── images -> content/images/    # symlink — no duplication
├── docs -> content/docs/        # symlink — no duplication
├── downloads -> content/downloads/  # symlink — no duplication
└── content/             # original Pelican source (kept for reference)
```

> `images/`, `docs/`, and `downloads/` are symlinks into `content/` so assets
> are stored once. Per-post images are copied directly into each post's folder
> under `posts/`.
