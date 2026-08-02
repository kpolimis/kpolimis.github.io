# Code Review: kpolimis.github.io

## Summary

This is a Quarto-based personal website for Kivan Polimis, a data scientist and researcher. The site uses the `cosmo` Bootstrap theme augmented with custom SCSS/CSS, an animated canvas background (`bayesian-waves-bg.js`), and a standard Quarto listing setup for blog and technical posts. Most content was migrated from a prior Pelican site. The codebase is small, well-organized, and the newer posts (EPL series, algorithmic-bias) are written cleanly. The main issues are residual migration artifacts: broken/stale cross-post links, a couple of malformed HTML tags, an insecure external script load, an infinite animation loop with no accessibility escape hatch, and a handful of posts with missing metadata.

---

## Findings

### Critical

**1. Insecure MathJax CDN load (mixed-content / deprecated endpoint)**
File: `posts/technical/nba-mvp-comparisons-part-2/index.qmd`, line 23

```html
<script type="text/javascript" src="http://cdn.mathjax.org/mathjax/latest/MathJax.js?config=TeX-AMS_HTML"></script>
```

This loads MathJax over plain HTTP from a CDN that shut down in 2017. Modern browsers will block this as mixed content on an HTTPS site. The math rendering in that post is silently broken. The legacy MathJax v1 config block on lines 13–21 (`MathJax.Hub.Config`) uses the v1 API that no longer exists. Replace with a CDN-hosted MathJax v3 load over HTTPS, or remove the block and rely on Quarto's built-in `html-math-method: mathjax` setting in `_quarto.yml`.

---

**2. Duplicate `{{< embed >}}` in flights-analysis**
File: `posts/technical/flights-analysis/index.qmd`, lines 13 and 17

The same notebook is embedded twice:

```
{{< embed ../../../downloads/notebooks/flights_analysis.ipynb >}}
<img src="./flights2018.gif" alt="Gif of Flights">
{{< embed ../../../downloads/notebooks/flights_analysis.ipynb >}}
```

Quarto will render the full notebook output twice (all cells, all output), doubling the page weight and duplicating every chart and code block. This is a copy-paste error from migration. Remove the second embed.

---

### Warnings

**3. Stale cross-post links pointing to old Pelican domain**

Cross-post links in the COVID-19 mortality series and the NBA MVP series still point to the old Pelican-era domain (`http://kivanpolimis.com/...`) with the old URL slugs. These are 404s or redirect-dependent:

- `posts/technical/mortality-data-covid-19-disinformation-part-1/index.qmd` (line 204): links to `http://kivanpolimis.com/mortality-data-and-covid-19-disinformation-part-2.html`
- `posts/technical/mortality-data-covid-19-disinformation-part-2/index.qmd` (lines 15, 131): same pattern
- `posts/technical/mortality-data-covid-19-disinformation-part-3/index.qmd` (lines 15, 121)
- `posts/technical/mortality-data-covid-19-disinformation-part-4/index.qmd` (line 15)
- `posts/technical/nba-mvp-comparisons-part-2/index.qmd` (line 35): links to `http://www.kivanpolimis.com/nba-mvp-comparisons-part-1.html`

These should be converted to relative Quarto paths (e.g., `../../mortality-data-covid-19-disinformation-part-2/`) so they work regardless of domain and do not require HTTP redirects.

Additionally, `posts/blog/migrating-pelican-to-quarto/index.qmd` line 13 links to `[kivanpolimis.com](kivanpolimis.com)` — a bare domain without a scheme, which Quarto will not resolve as a hyperlink.

---

**4. Unclosed/malformed HTML tags in two files**

`software.qmd`, lines 46 and 65 — `<h1>` tags are not closed with `</h1>`:

```html
<h1>Community guidelines<h1>   <!-- should be </h1> -->
...
<h1>References<h1>             <!-- should be </h1> -->
```

`posts/technical/positions-matter/index.qmd`, line 38 — the `style` attribute quote is not closed before the `>` that ends the `img` tag:

```html
<img src="./rb-plot-example.png" alt="RB Plot Example" style="width: 72%; height: 72%>
```

The closing `"` is missing after `72%`. This causes the browser to consume the `></p>` as part of the attribute value, likely breaking the layout of the surrounding paragraph.

---

**5. Animation loop has no stop condition and ignores `prefers-reduced-motion`**
File: `bayesian-waves-bg.js`

The `tick()` function calls `requestAnimationFrame(tick)` unconditionally and the returned handle is never stored, so the loop cannot be cancelled:

```js
t += CONFIG.speed;
requestAnimationFrame(tick);   // handle discarded — no cancel path
```

Two consequences:
- The animation keeps running even when the tab is hidden (no `visibilitychange` guard), wasting battery/CPU for background tabs.
- The OS accessibility setting `prefers-reduced-motion: reduce` is not respected. Users who have requested reduced motion for vestibular or epilepsy-related reasons get the full animation with no opt-out.

Minimum fix: check `window.matchMedia('(prefers-reduced-motion: reduce)').matches` before starting the loop, and mirror the preference in `custom.scss` with `@media (prefers-reduced-motion: reduce) { #network-canvas { display: none; } }`. Also store the RAF handle and pause on `visibilitychange`.

---

**6. Committed binary archives in the repo root**

`content-archive.zip` and `drafts.zip` are present in the repo root and tracked in git (they are not excluded by `.gitignore`, which excludes `*.zip` only to prevent future additions — already-committed files stay tracked). These files are ~several MB of binary data that adds permanent weight to git history for every clone. They are also not referenced by any Quarto page. If the archives are needed for backup, they should be stored outside the repo or in Git LFS; otherwise they should be removed and the history rewritten.

---

**7. Broken Binder link in positions-matter**
File: `posts/technical/positions-matter/index.qmd`, line 24

```
[![Binder](http://mybinder.org/badge.svg)](http://mybinder.org:/repo/kpolimis/nfl-combine-evaluation-plots){:target=blank}
```

The URL uses `http://` (blocked on HTTPS pages), the Binder URL format has changed (`mybinder.org:/repo/` is not valid), and `{:target=blank}` is Pelican/Kramdown link attribute syntax that Quarto does not parse — it will render as literal text. The badge image also loads over HTTP, making it a mixed-content request. Either update to the current `https://mybinder.org/v2/gh/kpolimis/nfl-combine-evaluation-plots/HEAD` format or remove the badge if the repo is no longer maintained.

---

### Suggestions

**8. Seventeen posts have empty `description` or `image` fields**

The listing pages (`technical.qmd`, `blog.qmd`) show `fields: [date, title, description, categories, reading-time]`. Empty `description: ""` means these posts show no excerpt in the listings, reducing discoverability. Similarly, `image: ""` means no thumbnail appears. The affected posts are primarily the migrated Pelican content. Populating these fields is a content task, not a code fix, but it is the highest-impact improvement for reader experience after the technical issues above.

Affected posts (partial list): `nba-shot-chart-part-1`, `nba-mvp-comparisons-part-1`, `nba-mvp-comparisons-part-3`, `triple-double-russ`, `flights-analysis`, `milano-location-history`, `seattle-location-history`, `first-post`, `ec2-r-and-twitter`.

---

**9. `vita_script.sh` uses hardcoded absolute paths and copies to a non-existent output directory**
File: `docs/vita_script.sh`

```sh
cp ~/repos/vita/Polimis_Curriculum_Vitae.pdf Kivan_Polimis_Curriculum_Vitae.pdf
cp Kivan_Polimis_Curriculum_Vitae.pdf ../../output/docs/.
```

The script assumes `~/repos/vita/` exists on any machine running it, and writes to `../../output/docs/` — the old Pelican output path that does not exist in the current Quarto project structure (`_site/` is the build dir). This script will silently fail or produce wrong output for anyone other than the original author. Since the PDFs are already present in `docs/`, the script is either already outdated or needs the paths updated to reflect the Quarto layout.

---

**10. `PELICAN_END_SUMMARY` comment left in migrated post**
File: `posts/technical/social-media-twitter-api-and-r/index.qmd`, line 32

```html
<!-- PELICAN_END_SUMMARY -->
```

This is a Pelican-specific marker with no effect in Quarto. It is harmless but is a stale migration artifact that can be removed.

---

**11. Notebook category mismatch in `social-media-twitter-api-and-r`**
File: `posts/technical/social-media-twitter-api-and-r/index.qmd`

The front matter lists `categories: [tutorial, python]` but the post content is entirely R code (no Python). This causes the post to appear under the "python" filter on the listing page incorrectly. Change to `categories: [tutorial, r]`.

---

**12. Global `link-external-newwindow: true` in `_quarto.yml`**

The `_quarto.yml` sets `link-external-newwindow: true` globally, causing every external link to open in a new tab. This is generally considered an accessibility anti-pattern (it removes the user's control over tab behavior and is unexpected for keyboard and screen reader users). Consider removing this and applying `target="_blank"` only where explicitly desired, or at minimum adding `rel="noopener noreferrer"` (Quarto should add this automatically when the setting is active, but it is worth verifying in the rendered output).

---

## Conclusion

The site is well-structured and the newer content is well-written. The two highest-priority fixes are the broken MathJax script load in `nba-mvp-comparisons-part-2` (silent rendering failure) and the duplicate notebook embed in `flights-analysis` (doubled page output). The malformed HTML tags in `software.qmd` and `positions-matter` are likely causing layout breakage visible to readers. The stale Pelican-era cross-post links affect reader navigation across the entire COVID-19 mortality series and NBA MVP series. The animation accessibility gap and committed binary archives are lower urgency but worth addressing before the site reaches a wider audience.
