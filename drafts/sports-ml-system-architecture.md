Title: Building a Production Sports Prediction System: Architecture, MLOps, and Lessons Learned
Date: 2026-05-06
Category: Sports
Tags: mlops, sports-analytics, lightgbm, fastapi, docker, nba, ncaa, machine-learning
Slug: sports-ml-prediction-system-architecture
Summary: I built a production-grade sports prediction API — win probabilities for NCAA and NBA, served via FastAPI, trained on LightGBM ensembles with isotonic calibration. Here's the architecture, the decisions I made, and what I'd change.

---

There are two kinds of sports analytics projects: the notebook that produces a great chart and the system that produces predictions you'd stake money on. The gap between them is almost entirely engineering.

I've been building toward the latter for a while. The result is `sports-ml` — a full-stack prediction system that ingests data from multiple sources, trains calibrated ensemble models, and serves win probabilities via a REST API. This post documents the architecture, the design decisions, and the things that are still rough.

---

## Why Build a System and Not Just a Notebook?

Notebooks are where ideas live. Systems are where ideas get tested.

When I say "tested," I mean something specific: a system forces you to make predictions before you see the outcome. You have to commit. There's no ex-post narrative adjustment — no "well, if you look at the adjusted numbers, the result makes sense." You said Team A wins with probability 0.73. They lost. That's a falsifiable claim, and now you know something.

That epistemological discipline is why I built infrastructure instead of stopping at a Kaggle notebook. The March Madness submission is one output of the system. Daily NBA win probabilities — updated as rosters change, as injuries happen, as the season evolves — is where the real signal lives.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Data Sources                        │
│  KenPom · HerHoopStats · Sports-Reference · Odds API   │
└────────────────────────┬────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │    ETL Pipelines    │
              │  BaseETL → OddsETL  │
              │  BaseETL → KenPom   │
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │   SQLite / Postgres  │
              │   Feature Store     │
              └──────────┬──────────┘
                         │
         ┌───────────────▼──────────────┐
         │       Model Training          │
         │  LightGBM + XGBoost + RF      │
         │  Expanding-window CV          │
         │  Isotonic Calibration         │
         └───────────────┬──────────────┘
                         │
              ┌──────────▼──────────┐
              │     FastAPI          │
              │  /predict/ncaa       │
              │  /predict/nba        │
              │  /simulate/bracket   │
              └─────────────────────┘
```

The three main layers — ingestion, training, serving — are deliberately separated. This isn't over-engineering for a personal project; it's the minimum viable separation to make the system maintainable as the feature set grows.

---

## Layer 1: ETL Pipelines

Every data source has its own ETL class that inherits from `BaseETL`:

```python
# etl/base.py
from abc import ABC, abstractmethod
from typing import Any
import pandas as pd
import logging

logger = logging.getLogger(__name__)

class BaseETL(ABC):
    """Base class for all sports data ETL pipelines.
    
    Domain logic (transformations) must be pure functions.
    I/O (fetching, writing) is isolated to extract() and load().
    """
    
    @abstractmethod
    def extract(self) -> pd.DataFrame:
        """Fetch raw data from source. Side effects live here."""
        ...
    
    @abstractmethod
    def transform(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Transform raw data to feature-ready format. Must be pure."""
        ...
    
    @abstractmethod
    def load(self, features: pd.DataFrame) -> None:
        """Write to feature store. Side effects live here."""
        ...
    
    def run(self) -> None:
        logger.info(f"Running {self.__class__.__name__}")
        raw = self.extract()
        features = self.transform(raw)
        self.load(features)
        logger.info(f"Completed {self.__class__.__name__}: {len(features)} records")
```

The pure function constraint on `transform()` matters more than it sounds. It means transformations are unit-testable without mocking anything. I can run `transform(raw_df)` in a test and assert on the output without hitting the network or the database. In a system where data quality is your biggest risk, this is load-bearing.

The `OddsETL` class pulls betting lines from the Odds API, the `KenPomETL` class scrapes and parses efficiency metrics, and the `SportRefETL` class handles schedule and box score data. Each knows its own domain; none knows about the others.

---

## Layer 2: Model Training

### The Expanding-Window Problem

Most sports ML tutorials use k-fold cross-validation. This is wrong for time-series prediction and it will give you inflated accuracy estimates.

The correct approach is an expanding window: for each validation year, train only on prior years. Never look forward.

```python
# models/base.py (simplified)
def expanding_window_cv(
    df: pd.DataFrame,
    target: str,
    min_train_years: int = 3,
) -> list[dict[str, float]]:
    """
    For each year in the dataset (after min_train_years),
    train on all prior years, evaluate on current year.
    """
    years = sorted(df["season"].unique())
    results = []
    
    for i, val_year in enumerate(years[min_train_years:], start=min_train_years):
        train_years = years[:i]
        
        train = df[df["season"].isin(train_years)]
        val = df[df["season"] == val_year]
        
        model = train_lgbm(train, target)
        preds = model.predict_proba(val.drop(columns=[target]))[:, 1]
        
        brier = brier_score_loss(val[target], preds)
        results.append({"val_year": val_year, "brier": brier})
    
    return results
```

This is slower. It's also correct. The difference in estimated model quality between k-fold and expanding-window on tournament data is not small — I've seen 15-20% overestimation of performance with k-fold.

### Calibration

Raw model probabilities are not well-calibrated. A model that says "60% confidence" should win approximately 60% of the time when it says that. For sports, this is rarely true out of the box.

Isotonic regression maps raw scores to calibrated probabilities:

```python
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression

# After training the base model
calibrator = IsotonicRegression(out_of_bounds="clip")
calibrator.fit(val_raw_scores, val_outcomes)

# At inference time
calibrated_prob = calibrator.predict([raw_score])[0]
```

The 2026 lesson — which I wrote about in the postmortem — is that calibration on historical data can fail when the current tournament has a different upset rate than historical base rates. The next version will use a rolling calibration window and shrink toward a seed-based prior.

### The Ensemble

Three models, equal weight (for now):

| Model | Why |
|---|---|
| LightGBM | Fast, handles missing values, good out-of-box |
| XGBoost | Different regularization landscape from LGB |
| Random Forest | Decorrelates with boosting methods |

The ensemble doesn't dramatically outperform the best single model, but it's more stable across years. For a competition scored on Brier, variance reduction matters.

---

## Layer 3: FastAPI Serving

```python
# api/routers/ncaa.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models.ncaa.game_predictor import NCAAPredictor

router = APIRouter(prefix="/predict", tags=["ncaa"])
predictor = NCAAPredictor.load_latest()

class NCAAMatchupRequest(BaseModel):
    team1_kaggle_id: int
    team2_kaggle_id: int
    season: int = 2026

class NCAAMatchupResponse(BaseModel):
    p_team1_wins: float
    p_team2_wins: float
    model_version: str
    calibrated: bool

@router.post("/ncaa", response_model=NCAAMatchupResponse)
async def predict_ncaa_matchup(request: NCAAMatchupRequest):
    try:
        prob = predictor.predict(
            request.team1_kaggle_id,
            request.team2_kaggle_id,
            request.season
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    
    return NCAAMatchupResponse(
        p_team1_wins=round(prob, 4),
        p_team2_wins=round(1 - prob, 4),
        model_version=predictor.version,
        calibrated=True,
    )
```

The Pydantic models are doing real work here: they enforce that `team1_kaggle_id` is an integer, that `season` defaults sensibly, and they generate the OpenAPI spec automatically. When I rebuild this for NBA — where I'll be ingesting live box score data and predicting in-game — the same pattern scales.

---

## What the NCAA Notebook Is and Isn't

I made a deliberate choice to keep the Kaggle competition logic in a Jupyter notebook (`notebooks/march_mania_2026.ipynb`) rather than wiring it into the API layer.

March Madness is structurally different from regular season prediction:

- **Brier score competition** — optimal strategy is different from maximizing accuracy
- **One-and-done elimination** — variance properties are completely different
- **Audience is researchers, not bettors** — notebook is the right format

The API is for live regular-season win probabilities. The notebook is the research artifact. These have different audiences, different lifecycles, and different deployment patterns. Conflating them would make both worse.

---

## What I'd Build Differently

**Feature store.** SQLite works for development, but I'm going to hit its limits when I add real-time NBA data. A lightweight Postgres instance (already running on Apollo) is the right call, with a proper schema that separates raw tables from feature tables.

**Model registry.** Right now I load "latest" model from disk. For NBA daily retraining, I need versioned models with performance tracking — at minimum a SQLite table of `{model_id, sport, train_date, val_brier, path}`. MLflow is overkill; a simple metadata table is not.

**Monitoring.** The system has no prediction logging. I don't know post-hoc how my NBA probabilities performed game-by-game. This is the most pressing gap — you can't improve what you don't measure.

---

## The NBA Stub

The Makefile has this:

```makefile
nba-etl:
    @echo "NBA ETL not yet implemented."
    @echo "Add your existing NBA ETL code to etl/nba/ following BaseETL pattern."

nba-train:
    @echo "NBA model training not yet implemented."
```

The infrastructure exists. The feature engineering is the work. That's the next post.

---

*Code: [github.com/kivanpolimis/sports-ml](https://github.com/kivanpolimis/sports-ml). The Kaggle notebook is at `notebooks/march_mania_2026.ipynb`. Raise issues or PRs — especially if you have a better calibration strategy than I do.*
