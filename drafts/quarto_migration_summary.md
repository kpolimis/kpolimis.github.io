# Pelican → Quarto Migration Summary

**Date:** 2026-05-04  
**Quarto version:** 1.9.37  
**`quarto check` result:** All green ✓

---

## Files Created at Repo Root

| File | Purpose |
|---|---|
| `_quarto.yml` | Site config: cosmo theme, `freeze: auto`, navbar, footer |
| `index.qmd` | Landing / about page |
| `technical.qmd` | Listing page — Technical Articles |
| `blog.qmd` | Listing page — Blog |
| `vita.qmd` | CV / Resume page |
| `teaching.qmd` | Teaching page |
| `software.qmd` | Software / OSS page (forest-confidence-interval) |
| `projects.qmd` | Projects page (DisCont, GFC) |
| `styles.css` | Minimal custom CSS |

---

## Post Migration Table

### Technical Articles (`posts/technical/`)

| Source `.md` | Slug | Date | Categories |
|---|---|---|---|
| `ec2-R-and-Twitter.md` | `ec2-r-and-twitter` | 2016-04-02 | how-to *(draft)* |
| `flights_analysis.md` | `flights-analysis` | 2016-09-30 | how-to |
| `host-osrm-on-ec2-server.md` | `host-osrm-on-ec2-server` | 2017-02-25 | how-to *(draft)* |
| `milano_location_history.md` | `milano-location-history` | 2018-03-06 | how-to |
| `mortality_data_covid_19_disinformation_part_1.md` | `mortality-data-covid-19-disinformation-part-1` | 2021-01-07 | tutorial, python |
| `mortality_data_covid_19_disinformation_part_2.md` | `mortality-data-covid-19-disinformation-part-2` | 2021-01-11 | tutorial, python |
| `mortality_data_covid_19_disinformation_part_3.md` | `mortality-data-covid-19-disinformation-part-3` | 2021-01-14 | tutorial, python |
| `mortality_data_covid_19_disinformation_part_4.md` | `mortality-data-covid-19-disinformation-part-4` | 2021-01-17 | tutorial, python |
| `nba_mvp_comparisons-part_1.md` | `nba-mvp-comparisons-part-1` | 2018-12-25 | sports-analytics, python |
| `nba_mvp_comparisons-part_2.md` | `nba-mvp-comparisons-part-2` | 2019-02-27 | sports-analytics, python |
| `nba_mvp_comparisons-part_3.md` | `nba-mvp-comparisons-part-3` | 2019-03-06 | sports-analytics, python |
| `nba_shot_chart_part_1.md` | `nba-shot-chart-part-1` | 2022-02-27 | sports-analytics, python |
| `positions_matter.md` | `positions-matter` | 2016-08-01 | sports-analytics, python |
| `seattle_location_history.md` | `seattle-location-history` | 2017-08-21 | how-to |
| `social_media_twitter_API_and_R.md` | `social-media-twitter-api-and-r` | 2016-04-17 | tutorial, python |
| `triple_double_russ.md` | `triple-double-russ` | 2022-03-06 | sports-analytics, python |

### Blog (`posts/blog/`)

| Source `.md` | Slug | Date | Categories |
|---|---|---|---|
| `first_post.md` | `first-post` | 2016-03-21 | review |
| `make-a-Pelican-blog.md` | `make-a-pelican-blog` | 2016-03-24 | how-to |
| `sicss_debrief.md` | `sicss-debrief` | 2017-07-17 | review |

---

## Asset Migration

| Asset | Action |
|---|---|
| `content/images/` | Copied to `images/` at repo root |
| `content/docs/` | Copied to `docs/` at repo root |
| `content/downloads/` | Copied to `downloads/` at repo root |
| `content/favicon.ico/png` | Copied into `images/` |
| Per-post images | Copied into each post's own folder; paths rewritten from `../../images/foo.png` → `./foo.png` |

**Posts with per-post image copies:**
- `mortality-data-covid-19-disinformation-part-1` — `social_media_mortality_data_screenshot.png`
- `mortality-data-covid-19-disinformation-part-4` — 4 plot PNGs
- `positions-matter` — `rb-plot-example.png`
- `social-media-twitter-api-and-r` — 8 Twitter map images
- `nba-mvp-comparisons-part-2` — `age_vote_share_bivariate.png`
- `make-a-pelican-blog` — `pelican-quickstart.png`
- `sicss-debrief` — `SICSS_group_picture_edited.jpg`
- `flights-analysis` — `flights2018.gif`

---

## `.gitignore` Additions

```
_site/
.quarto/
_freeze/
```

---

## Known Limitations / Next Steps

1. **Notebook posts render Pelican tags literally.** Posts that used `{% notebook foo.ipynb %}` embed syntax (nba-mvp-comparisons-part-1/3, nba-shot-chart-part-1, triple-double-russ, flights-analysis, seattle/milano-location-history) display the raw Jinja tag. These need to be converted to proper `.qmd` files with actual code cells or `knitr`/Jupyter cell references. `freeze: auto` means they render as static markdown without errors.

2. **Two draft posts** (`ec2-r-and-twitter`, `host-osrm-on-ec2-server`) are marked `draft: true` — they were stubs with `Status: draft` in Pelican and will not appear in the listing pages.

3. **CV links in `vita.qmd`** point to `docs/Kivan_Polimis_Curriculum_Vitae.pdf` etc. — verify these are accessible after `quarto render`.

4. **Social media category mapping** — `Tutorials` category was mapped to `["tutorial", "python"]` per the migration spec, but the mortality and Twitter posts are R-based. Consider adding an `r` category tag to those posts.

5. **`teaching.qmd`** — course materials referenced as "will be placed here" — no content to add yet.

---

## Preview

```bash
conda activate blog
quarto preview
```

## Build

```bash
conda activate blog
quarto render
```
