Title: What "Reproducible Research" Actually Requires: A Practitioner's Guide
Date: 2026-05-09
Category: Tutorials
Tags: reproducibility, research-pipelines, quarto, python, r, open-science, social-science, make
Slug: reproducible-research-pipelines-practitioner-guide
Summary: Every journal says it requires reproducibility. Almost none of them agree on what that means. After building a full reproducible pipeline for Fragile Families data and writing a course on it, here's what I think reproducibility actually requires — and the minimal toolset to get there.

---

"Reproducibility" has become the kind of word that means everything and nothing. Journals append reproducibility policies to their author guidelines. Funding agencies require data management plans. Reviewers ask for code.

None of this is the same thing.

After building a reproducible pipeline for a large-scale social science project using restricted Fragile Families data — and then turning that experience into teaching material — I have a reasonably clear view of what reproducibility actually requires, what the minimum viable toolset is, and where most researchers' pipelines break.

---

## What Reproducibility Actually Means

The AEA (American Economic Association) data policy says replication materials must allow results to be reproduced. The AJPS (American Journal of Political Science) says "replication materials must allow the results to be reproduced."

These sound identical. They're not.

The AEA policy has teeth: they run your code and verify that it produces the tables and figures in the paper. They have a dedicated data editor who does this systematically. Getting rejected by the AEA data editor after acceptance is not hypothetical — it happens.

The AJPS policy relies on community verification — reviewers and readers who want to extend or challenge your work. It's softer but broader: your materials need to be understandable, not just runnable.

The practical question: can a competent researcher who has never seen your project run your code on their machine and produce the same results? Not "similar results." The same numbers, to however many decimal places the paper reports them.

This is a harder standard than most researchers realize.

---

## The Four Failure Modes

Most irreproducible research fails in one of four ways:

### 1. Environment Underspecification

```python
# This is not a reproducible environment specification
import pandas  # which version?
from sklearn.ensemble import RandomForestClassifier  # sklearn 0.24 or 1.3?
```

Package versions matter. The behavior of `pd.DataFrame.groupby(...).agg(...)` changed between pandas 1.x and 2.x. If your code ran on 1.5 and the reviewer has 2.0, you might get different results.

The fix is a locked environment file. In Python:

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Lock exact versions (including transitive dependencies)
pip freeze > requirements.lock
```

Commit `requirements.lock` to the repository. The reviewer installs from the lock file, not the requirements file. Same versions, same behavior.

In R, `renv` does the equivalent:

```r
# Initialize renv in your project
renv::init()

# After installing packages
renv::snapshot()  # Creates renv.lock

# Collaborator restores exact environment
renv::restore()
```

### 2. Absolute Paths

```python
# This only works on your machine
data = pd.read_csv("/Users/kivan/projects/fragile-families/data/ff_data.csv")
```

Every hardcoded path is a reproducibility landmine. The fix is project-relative paths:

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"

data = pd.read_csv(DATA_DIR / "ff_data.csv")
```

Or better, a `Settings` object that reads from environment variables, with sensible defaults:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    data_dir: Path = Path("data")
    output_dir: Path = Path("output")
    model_dir: Path = Path("models")
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### 3. Missing Random Seeds

```python
# Not reproducible
from sklearn.ensemble import RandomForestClassifier
model = RandomForestClassifier(n_estimators=100)

# Reproducible
model = RandomForestClassifier(n_estimators=100, random_state=42)
```

Set seeds everywhere: model initialization, train/test splits, shuffles, bootstraps. Document that you set them. If a result depends on a random process, a reviewer needs to reproduce that process exactly.

For numpy:

```python
import numpy as np
rng = np.random.default_rng(seed=42)  # Modern API
```

For R:

```r
set.seed(42)
```

### 4. Missing DAG (Dependency Graph)

The most common failure mode: a pile of scripts with no specification of which order to run them in, or which outputs are inputs to which other scripts.

```
run_this_first.py
also_run_this.py  
run_model.py  # depends on output of first two
make_tables.py  # depends on run_model.py output
```

This looks obvious when you wrote it. It's opaque six months later or to anyone else.

The fix is a `Makefile` — not because Make is the best build tool (it isn't), but because it's universal:

```makefile
# Makefile
.PHONY: all data features model tables clean

all: tables

data: data/processed/ff_cohort.csv

features: output/features.parquet

model: output/model.pkl output/predictions.csv

tables: output/table1.tex output/table2.tex output/figure1.pdf

# Rules
data/processed/ff_cohort.csv: data/raw/ff_public.csv scripts/00_clean_data.py
    python scripts/00_clean_data.py

output/features.parquet: data/processed/ff_cohort.csv scripts/01_build_features.py
    python scripts/01_build_features.py

output/model.pkl output/predictions.csv: output/features.parquet scripts/02_train_model.py
    python scripts/02_train_model.py

output/table1.tex output/table2.tex output/figure1.pdf: output/predictions.csv scripts/03_make_tables.py
    python scripts/03_make_tables.py

clean:
    rm -f output/*
```

A reviewer can now run `make all` and get everything. Make handles dependencies automatically — if `features.parquet` is already up to date, it won't rebuild it.

---

## The Restricted Data Problem

If your project uses restricted data — administrative records, confidential surveys, proprietary datasets — you can't share the data. This creates a genuine reproducibility challenge.

The solution is a two-track pipeline:

**Track 1: Public data, full pipeline runnable by anyone**

Use a synthetic version of the data, or publicly available analogues. Your `data/` directory contains the synthetic data, your pipeline runs end to end, and a reviewer can verify that the code is correct even if they can't verify the exact numbers.

**Track 2: Restricted data, results archived with the journal**

Many journals (AEA, AJPS, ICPSR) have formal arrangements to archive restricted-data replication packages in secure repositories. Reviewers with appropriate IRB clearance can access the actual data and verify the full results.

Your data availability statement for a restricted-data paper should be specific:

> The analysis uses restricted data from the Fragile Families and Child Wellbeing Study (FF). Researchers may apply for restricted data access at [URL]. The analysis code, a synthetic public-use dataset for pipeline verification, and full replication output are archived at [journal repository]. Upon acceptance, the restricted-data replication package will be deposited with ICPSR under controlled access.

This is accurate, useful, and doesn't pretend the data is shareable when it isn't.

---

## Quarto as the Document Layer

I've been using [Quarto](https://quarto.org) as the integration layer between analysis code and research output. The key feature: code blocks that execute and embed output directly in the document.

```qmd
---
title: "Fragile Families Analysis"
format: pdf
execute:
  echo: false
  warning: false
---

## Results

```{python}
import pandas as pd
results = pd.read_csv("output/table1_results.csv")
results.style.format("{:.3f}")
```

The coefficient on maternal education (β = `{python} round(results.loc[0, 'coef'], 3)`) 
is significant at the 1% level.
```

When I render this document, the code runs, the table populates, and the inline coefficient is computed from the actual output — not typed by hand. If I rerun the analysis with updated data, the document updates automatically.

This eliminates a category of errors that affects almost every paper: transcription errors between analysis output and manuscript. The number in the table and the number in the text are guaranteed to be the same number.

---

## The Minimum Viable Reproducible Pipeline

If you take nothing else from this post, implement these five things:

1. **Lock your environment.** `requirements.lock` (Python) or `renv.lock` (R). Commit it.

2. **Set seeds everywhere.** Every random process gets an explicit seed. Document them.

3. **Use project-relative paths.** No absolute paths anywhere in the codebase.

4. **Write a Makefile.** Declare the dependency graph explicitly. A reviewer should be able to run `make all` and get the paper.

5. **Test your own pipeline cold.** Clone your repo into a fresh directory, restore the environment from the lock file, run `make all`. If it breaks, it's not reproducible.

That's it. You don't need Docker (though it helps). You don't need CI/CD (though it's good practice). You need the five things above.

---

## A Note on "Computational Reproducibility" vs. "Replicability"

These are different things that often get conflated:

**Computational reproducibility**: the same data + the same code = the same results. This is table stakes.

**Replicability**: a different researcher, using a different dataset, following the same procedure, gets the same *conclusion*. This is what science cares about.

A paper can be computationally reproducible (your code runs on my machine and produces your numbers) and still not be replicable (the effect disappears in a different sample, a different year, a different country).

Computational reproducibility is necessary but not sufficient for scientific credibility. Building it in from the start makes the replication conversation possible — and honest.

---

*The course materials this post is based on are in development. Reach out if you teach quantitative methods or computational social science and want to collaborate on the curriculum.*
