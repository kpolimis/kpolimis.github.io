Title: Reproducibility is Not a Checkbox: A Complete Guide for Multi-Phase Analytical Pipelines
Date: 2026-05-19
Category: Tutorials
Tags: reproducibility, research-pipelines, mlops, python, r, quarto, make, docker, mlflow, open-science
Slug: reproducibility-complete-guide-multi-phase-pipelines
Summary: Every journal says it requires reproducibility. Almost none agree on what that means, and most ML engineers have a different set of failure modes than academic researchers. This post covers both — the five engineering failure modes in multi-phase ML pipelines, and the four things social science researchers consistently get wrong — with the minimal toolset to fix all of them.

---

Reproducibility has become the kind of word that means everything and therefore nothing. Journals append reproducibility policies to author guidelines. Funding agencies require data management plans. ML teams pin `requirements.txt`. Reviewers ask for code.

None of this is the same thing, and most of it is insufficient.

I've hit reproducibility failures from two directions: building multi-phase ML pipelines for production systems (where the failure mode is silent drift between pipeline stages), and conducting social science research with restricted data (where the failure mode is not being able to satisfy a journal's data editor). The fixes look different. The underlying principle is the same: **reproducibility is a property that accumulates across every decision in a pipeline, not a cleanup task at the end.**

This post covers both failure landscapes and the minimal toolset that addresses them.

---

## Part I: Engineering Failure Modes in ML Pipelines

### Why Multi-Phase Pipelines Are Different

A single analysis script is relatively easy to make reproducible. Seed your random state. Pin your dependencies.

Multi-phase pipelines are harder because **state leaks between phases**:

```
Phase 1: Data ingestion + cleaning
    ↓  (intermediate artifact)
Phase 2: Feature engineering
    ↓  (intermediate artifact)
Phase 3: Model training
    ↓  (model artifact)
Phase 4: Evaluation + reporting
```

Each phase produces intermediate artifacts that feed the next. Reproducibility requires that each phase is internally consistent **and** that the contracts between phases are stable and versioned. Most pipelines handle the former and ignore the latter.

### Failure Mode 1: Implicit State in Data Cleaning

The most common failure: cleaning logic that produces different outputs depending on the order rows are processed.

```python
# Dangerous: order-dependent deduplication
df = df.drop_duplicates(subset=["patient_id", "visit_date"])

# If the upstream query changes its ORDER BY, you get different rows
# surviving deduplication. Your model trains on different data. Silently.
```

The fix is explicit deterministic sorting before any order-sensitive operation:

```python
# Reproducible: sort first, then deduplicate
df = (
    df
    .sort_values(["patient_id", "visit_date", "record_created_at"])
    .drop_duplicates(subset=["patient_id", "visit_date"], keep="last")
)
```

Rule: any cleaning step that selects among competing rows must be deterministic. Make the selection logic explicit, never implicit.

### Failure Mode 2: Feature Engineering Fitted on the Wrong Split

This one produces optimistic evaluation metrics without raising any errors.

```python
# Wrong: fit scaler on full dataset before splitting
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)  # leaks test set statistics into training

X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, random_state=42)
```

The correct pattern uses sklearn Pipelines to enforce fit-on-train-only:

```python
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingClassifier

pipeline = Pipeline([
    ("scaler", StandardScaler()),
    ("model", GradientBoostingClassifier(random_state=42)),
])

X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)
pipeline.fit(X_train, y_train)  # scaler only sees training data
```

In multi-phase pipelines, serialize fitted transformers alongside models and reload them for scoring rather than re-fitting:

```python
import joblib

# End of Phase 2 — save the fitted pipeline
joblib.dump(pipeline, "artifacts/pipeline_v1.pkl")
joblib.dump({
    "train_end_date": "2024-01-01",
    "n_features": X_train.shape[1],
    "schema_version": "v2.1",
}, "artifacts/pipeline_v1_metadata.json")

# Phase 4 scoring — reload, don't refit
pipeline = joblib.load("artifacts/pipeline_v1.pkl")
```

### Failure Mode 3: Non-Deterministic External Calls

APIs return different results over time. Web scrapers break. Database query results shift as tables are updated. Any phase that makes external calls is a reproducibility risk.

The solution is snapshot and version your raw data:

```python
import hashlib
import json
from datetime import datetime

def fetch_and_snapshot(api_call_fn, *args, snapshot_dir="data/raw", **kwargs):
    """
    Execute an API call and snapshot the result with a content hash.
    """
    data = api_call_fn(*args, **kwargs)
    
    content_hash = hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()[:12]
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    snapshot_path = f"{snapshot_dir}/{timestamp}_{content_hash}.json"
    
    with open(snapshot_path, "w") as f:
        json.dump({
            "fetched_at": timestamp,
            "content_hash": content_hash,
            "data": data,
        }, f)
    
    return data, snapshot_path
```

This gives you a full audit trail of what data trained each model, and the ability to replay any historical run exactly.

### Failure Mode 4: Undeclared Cross-Phase Dependencies

Phase 3 depends on *specific outputs* of Phase 2 — not just "the features file," but a particular version with a particular schema. When Phase 2 evolves, Phase 3 breaks in confusing ways.

Fix: a lightweight contract manifest between phases:

```python
# Phase 2 writes a manifest
import subprocess

phase2_manifest = {
    "output_path": "features/features_20240401.parquet",
    "schema_version": "v2.1",
    "feature_columns": ["age", "income_bucket", "days_since_last_visit"],
    "row_count": 84291,
    "produced_at": datetime.utcnow().isoformat(),
    "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
}

with open("features/manifest_20240401.json", "w") as f:
    json.dump(phase2_manifest, f, indent=2)
```

```python
# Phase 3 reads and validates the manifest
def load_features_with_validation(manifest_path, required_schema_version="v2.1"):
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    assert manifest["schema_version"] == required_schema_version, \
        f"Schema mismatch: expected {required_schema_version}, got {manifest['schema_version']}"
    
    df = pd.read_parquet(manifest["output_path"])
    
    missing_cols = set(manifest["feature_columns"]) - set(df.columns)
    assert not missing_cols, f"Missing expected columns: {missing_cols}"
    
    return df, manifest
```

### Failure Mode 5: Environment Drift

Pinning `requirements.txt` helps, but doesn't capture OS-level dependencies, CUDA versions, or parameter defaults that change between library minor versions (scikit-learn is notorious for this).

For production work: Docker with pinned base image digests, plus MLflow for experiment tracking:

```dockerfile
FROM python:3.11.8-slim@sha256:a4bc...  # pin to digest, not tag

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

```python
import mlflow

with mlflow.start_run(run_name="phase3_model_v2"):
    mlflow.log_params({
        "model_type": "GradientBoosting",
        "n_estimators": 200,
        "feature_schema_version": "v2.1",
        "training_data_hash": content_hash,
    })
    mlflow.log_metrics({"auc": auc, "f1_macro": f1})
    mlflow.sklearn.log_model(pipeline, "model")
```

Every run is tagged with the data hash and schema version — complete lineage from raw data to model artifact.

---

## Part II: Research Reproducibility for Academic Pipelines

### What Journal Policies Actually Require

The AEA (American Economic Association) data policy says replication materials must allow results to be reproduced. So does the AJPS. These sound identical. They're not.

The AEA has a dedicated data editor who runs your code and verifies it produces the tables in the paper. Getting rejected by the AEA data editor after acceptance happens. The AJPS relies on community verification — softer, but requires the materials to be understandable, not just runnable.

The practical question for both: can a competent researcher who has never seen your project run your code on their machine and produce the same results? Not "similar." The same numbers, to however many decimal places the paper reports them.

### Four Things Researchers Get Wrong

**1. No environment specification**

```python
import pandas  # which version?
from sklearn.ensemble import RandomForestClassifier  # 0.24 or 1.3?
```

Fix:

```bash
pip freeze > requirements.lock  # Python
```

```r
renv::snapshot()  # R — creates renv.lock
```

Commit the lock file. Reviewers install from it.

**2. Absolute paths**

```python
# This only works on your machine
data = pd.read_csv("/Users/kivan/projects/analysis/data/ff_data.csv")
```

Fix:

```python
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
data = pd.read_csv(PROJECT_ROOT / "data" / "ff_data.csv")
```

**3. Missing random seeds**

```python
# Not reproducible
model = RandomForestClassifier(n_estimators=100)

# Reproducible
model = RandomForestClassifier(n_estimators=100, random_state=42)
```

Set seeds everywhere, for every random process, and document them in the paper's methods section.

**4. No dependency graph**

A pile of scripts with no specification of run order is not reproducible. Fix: a Makefile:

```makefile
all: output/table1.tex output/figure1.pdf

data/processed/cohort.csv: data/raw/ff_public.csv scripts/00_clean.py
    python scripts/00_clean.py

output/features.parquet: data/processed/cohort.csv scripts/01_features.py
    python scripts/01_features.py

output/table1.tex output/figure1.pdf: output/features.parquet scripts/02_analyze.py
    python scripts/02_analyze.py

clean:
    rm -f output/*
```

A reviewer runs `make all`. Make handles dependencies. Reproducibility is demonstrated, not claimed.

### The Restricted Data Problem

If you use restricted data (administrative records, confidential surveys), you can't share it. This creates a genuine reproducibility challenge.

The two-track solution:

**Track 1: Public pipeline** — A synthetic version of the data, or public analogues. Your code runs end to end. A reviewer can verify the code is correct even without the actual data.

**Track 2: Restricted archive** — Many journals (AEA, AJPS, ICPSR) have arrangements to archive restricted-data packages in secure repositories. Reviewers with appropriate clearance can access the actual data.

Your data availability statement should be specific:

> The analysis uses restricted data from [dataset]. Researchers may apply for restricted access at [URL]. The analysis code, a synthetic public-use dataset for pipeline verification, and full replication output are archived at [journal repository]. Upon acceptance, the restricted-data replication package will be deposited with ICPSR under controlled access.

### Quarto as the Integration Layer

[Quarto](https://quarto.org) integrates prose and code so that the output in the paper is always computed from the actual analysis:

```qmd
---
title: "Fragile Families Analysis"
execute:
  echo: false
---

```{python}
import pandas as pd
results = pd.read_csv("output/table1_results.csv")
results.style.format("{:.3f}")
```

The coefficient on maternal education (β = `{python} round(results.loc[0, 'coef'], 3)`)
is significant at the 1% level.
```

When this renders, the inline coefficient and the table cell are both computed from `results` — the same object. They can't disagree. This eliminates a category of error (transcription errors between analysis output and manuscript) that affects a significant fraction of published papers.

---

## The Complete Checklist

**Data Layer**
- [ ] External calls are snapshotted and content-addressed
- [ ] Cleaning operations are deterministic (explicit sort before dedup)
- [ ] Raw data is immutable after ingestion; processed data is versioned

**Feature Engineering Layer**
- [ ] Transformers fit only on training data
- [ ] Fitted transformers serialized alongside models
- [ ] Schema version declared and validated downstream

**Modeling Layer**
- [ ] Random seeds set and logged for all random processes
- [ ] Model artifacts tagged with data hash + schema version
- [ ] Experiment tracking captures all hyperparameters

**Environment Layer**
- [ ] Lock file committed (`requirements.lock` or `renv.lock`)
- [ ] Docker image pinned to digest (not just tag)
- [ ] CI runs the full pipeline on each commit

**Research Output Layer**
- [ ] Dependency graph declared in Makefile or equivalent
- [ ] All paths are project-relative, never absolute
- [ ] Quarto (or R Markdown) for integrated prose + code output
- [ ] Data availability statement is accurate and specific

That's the complete list. It's longer than "pin your requirements." It's also what actually makes a pipeline reproducible — not just claimed to be.

---

*Code examples in this post are from real pipelines. All available on [GitHub](https://github.com/kpolimis). The social science reproducibility curriculum these examples draw from is in active development as a Quarto-based course.*
