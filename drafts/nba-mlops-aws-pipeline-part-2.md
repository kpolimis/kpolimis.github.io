Title: MLOps on the Hardwood, Part 2: Taking the NBA Pipeline to AWS
Date: 2026-05-20
Category: Sports
Tags: mlops, nba, aws, lambda, sagemaker, sports-analytics, feature-store, causal-inference, data-engineering
Slug: nba-mlops-aws-pipeline-part-2
Summary: Part 1 covered the local architecture — BaseETL, LightGBM ensemble, calibrated FastAPI serving. Part 2 is about moving it to AWS: Lambda for ingestion, a feature store to prevent training-serving skew, SageMaker Pipelines for automated retraining, and a causal inference insight about garbage time that materially improves prediction quality.

---

*This is Part 2 of the sports-ml series. [Part 1](/sports-ml-prediction-system-architecture.html) covered the local architecture: the ETL pattern, expanding-window cross-validation, isotonic calibration, and FastAPI serving. This post assumes you've read it.*

---

The local architecture works. LightGBM ensemble, calibrated probabilities, REST API serving — all of it runs on Apollo, my home server. But "works locally" and "works as a production prediction system" are different standards.

The NBA problem has a specific property that makes production engineering non-trivial: **the ground truth changes every 24 hours.** A player injury announced at 10 PM renders the model's pre-game weights stale for every subsequent game that player appears in. A late-night trade shifts the team's entire offensive structure.

You can't batch-retrain monthly. You need a pipeline that can respond to the data as fast as the data changes, without human intervention, and without introducing the kinds of bugs that are catastrophic in prediction systems — training-serving skew, data leakage, miscalibrated confidence intervals.

Moving to AWS is how I solved the operations problem. This post documents the architecture.

---

## The Core Challenge: Training-Serving Skew

Training-serving skew is when the features your model sees at inference time are computed differently from the features it was trained on. It's the most common and most silent failure mode in production ML.

In the NBA context: if I compute rolling ELO ratings differently in my training pipeline than in my inference pipeline (different lookback window, different handling of missing games, different normalization), the model makes predictions on features that don't match what it learned from. The predictions can look plausible while being systematically wrong.

The fix is a **feature store** — a single system that computes and serves features, used by both training and inference. You write the feature computation logic once. Both pipelines read from the same store.

```
Data Sources (NBA Stats API, odds)
           ↓
      Lambda Ingestor (daily trigger)
           ↓
      Raw Data Store (S3)
           ↓
      Feature Computation (Lambda/Glue)
           ↓
  ┌────────────────────────┐
  │    Feature Store       │
  │  (DynamoDB + S3)       │
  └─────────┬──────────────┘
            │
  ┌─────────┴──────────┐
  │                    │
Training Pipeline  Inference Pipeline
(SageMaker)        (Lambda → API)
```

Same features. Same logic. Same store.

---

## Layer 1: Lambda Ingestion

Two Lambda functions trigger on a cron schedule:

**Game schedule trigger** — Fires daily at 7 AM CT. Queries the NBA Stats API for today's games and yesterday's final box scores. Writes raw data to S3 under `s3://sports-ml/raw/nba/{date}/`.

**Odds trigger** — Fires at 11 AM CT (after most injury reports drop). Pulls current betting lines from the Odds API. Writes to `s3://sports-ml/raw/odds/{date}/`.

```python
# lambda/nba_ingestor.py
import boto3
import json
import requests
from datetime import date, timedelta
from nba_api.stats.endpoints import scoreboard, boxscoretraditionalv2

s3 = boto3.client("s3")
BUCKET = "sports-ml"

def handler(event, context):
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    
    # Yesterday's final box scores
    try:
        games = scoreboard.ScoreBoard(game_date=yesterday).get_dict()
        s3.put_object(
            Bucket=BUCKET,
            Key=f"raw/nba/{yesterday}/scoreboard.json",
            Body=json.dumps(games),
        )
        
        for game in games["scoreboard"]["games"]:
            game_id = game["gameId"]
            box = boxscoretraditionalv2.BoxScoreTraditionalV2(
                game_id=game_id
            ).get_dict()
            s3.put_object(
                Bucket=BUCKET,
                Key=f"raw/nba/{yesterday}/boxscore_{game_id}.json",
                Body=json.dumps(box),
            )
    
    except Exception as e:
        # Log and continue — partial ingestion is better than no ingestion
        print(f"Ingestion error for {yesterday}: {e}")
    
    return {"statusCode": 200, "date": yesterday}
```

The try/except pattern with logging-and-continue is intentional. NBA Stats API has reliability issues — rate limiting, occasional 504s, data that's slow to appear after late games. A failed ingestion that crashes the Lambda creates a gap in the feature store. A failed ingestion that logs and exits allows the feature computation step to handle missing days explicitly.

---

## Layer 2: Feature Computation

After ingestion, a second Lambda (or Glue job for heavier transforms) computes features from the raw data and writes them to the feature store.

The two key features for game-level prediction:

### Rolling ELO Ratings

ELO is a pairwise rating system that updates after each game. Unlike static efficiency metrics (KenPom, Net Rating), ELO reflects recent form because it's computed sequentially:

```python
def update_elo(
    winner_elo: float,
    loser_elo: float,
    k_factor: float = 20.0,
    home_advantage: float = 100.0,
    winner_is_home: bool = True,
) -> tuple[float, float]:
    """
    Update ELO ratings after a game.
    
    Returns (new_winner_elo, new_loser_elo).
    """
    # Expected score for winner
    home_adj = home_advantage if winner_is_home else -home_advantage
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo - home_adj) / 400))
    
    # Update ratings
    new_winner = winner_elo + k_factor * (1 - expected_winner)
    new_loser = loser_elo + k_factor * (0 - (1 - expected_winner))
    
    return new_winner, new_loser
```

ELO is computed sequentially over the season. The feature store stores the current ELO for each team after each game. At inference time, I pull the current ELO for both teams in the upcoming matchup.

### Adjusted Plus-Minus (RAPM)

Raw plus-minus is confounded by teammates and opponents. Regularized Adjusted Plus-Minus (RAPM) uses ridge regression to isolate each player's individual contribution:

```python
from sklearn.linear_model import Ridge
import numpy as np
import pandas as pd

def compute_rapm(possession_data: pd.DataFrame, lambda_reg: float = 2000.0) -> pd.Series:
    """
    Compute RAPM via ridge regression on possession-level data.
    
    possession_data: rows are possessions, columns are player indicators
                     (+1 for home team player, -1 for away team player)
    lambda_reg: L2 regularization strength (higher = more shrinkage toward 0)
    
    Returns: Series indexed by player_id with RAPM estimates.
    """
    X = possession_data.drop(columns=["points_differential"])
    y = possession_data["points_differential"]
    
    # Ridge regression — lambda_reg shrinks player estimates toward 0
    # This prevents overfitting for players with few possessions
    model = Ridge(alpha=lambda_reg, fit_intercept=False)
    model.fit(X, y)
    
    return pd.Series(model.coef_, index=X.columns)
```

RAPM at the game level is noisy — you need ~1,000+ possessions for stable estimates. I compute it on a rolling 30-game window per team, which gives enough possessions for meaningful estimates while capturing lineup changes.

---

## The Garbage Time Insight

This is the part that the ELO and RAPM features alone don't solve, and where my public health / causal inference background is load-bearing.

**The problem:** fourth-quarter garbage time in blowouts produces systematically misleading statistics. A team up by 25 with 2 minutes left pulls their starters. The bench unit plays against the opponent's bench. The resulting box score data — points scored, plus-minus, efficiency — reflects garbage time performance, not true team quality.

If you train a model on raw box score data without accounting for this, you teach it to learn garbage time patterns as if they were signal. A team that regularly blows games out will appear to have worse fourth-quarter bench depth than it actually does. A team that regularly loses by 25 will appear to have better bench depth than it does.

**The fix: treat garbage time as censored data.** This is survival analysis applied to basketball.

```python
def label_garbage_time(
    play_by_play: pd.DataFrame,
    score_diff_threshold: int = 20,
    time_remaining_threshold_seconds: int = 300,  # 5 minutes
) -> pd.DataFrame:
    """
    Label plays as garbage time based on score differential and time remaining.
    
    Possessions labeled as garbage time are excluded from RAPM computation
    and efficiency metric calculation.
    """
    # Absolute score differential at each possession
    play_by_play["score_diff_abs"] = play_by_play["score_diff"].abs()
    
    # Remaining seconds in regulation
    play_by_play["seconds_remaining"] = (
        play_by_play["period"].clip(upper=4).apply(lambda p: (5 - p) * 720)
        + play_by_play["clock_seconds"]
    )
    
    play_by_play["is_garbage_time"] = (
        (play_by_play["score_diff_abs"] >= score_diff_threshold) &
        (play_by_play["seconds_remaining"] <= time_remaining_threshold_seconds) &
        (play_by_play["period"] == 4)  # only regular 4th quarter, not OT
    )
    
    return play_by_play

# Use only non-garbage-time possessions for feature computation
clean_possessions = play_by_play[~play_by_play["is_garbage_time"]]
rapm_estimates = compute_rapm(clean_possessions)
```

In practice, this means RAPM and efficiency metrics are computed only on meaningful possessions. The model learns true team quality rather than blowout patterns. On validation data, excluding garbage time improved Brier score by approximately 3% — not dramatic, but consistent and explainable.

---

## Layer 3: Automated Retraining with SageMaker Pipelines

When model performance drops below a threshold, the system automatically triggers retraining. The trigger is the Brier score computed on the trailing 30 games:

```python
# lambda/monitor_and_retrain.py
import boto3
import json
import numpy as np
from sklearn.metrics import brier_score_loss

sagemaker = boto3.client("sagemaker")
PIPELINE_NAME = "nba-model-retrain-pipeline"
BRIER_THRESHOLD = 0.22  # retrain if trailing-30 Brier exceeds this

def handler(event, context):
    # Pull trailing-30 predictions and outcomes from feature store
    predictions, outcomes = load_trailing_predictions(n_games=30)
    
    current_brier = brier_score_loss(outcomes, predictions)
    print(f"Trailing-30 Brier: {current_brier:.4f} (threshold: {BRIER_THRESHOLD})")
    
    if current_brier > BRIER_THRESHOLD:
        print("Threshold exceeded — triggering retraining pipeline")
        response = sagemaker.start_pipeline_execution(
            PipelineName=PIPELINE_NAME,
            PipelineParameters=[
                {"Name": "TrainingDataS3Path", "Value": "s3://sports-ml/features/"},
                {"Name": "ModelOutputS3Path", "Value": "s3://sports-ml/models/"},
                {"Name": "TriggerReason", "Value": f"Brier={current_brier:.4f}"},
            ],
        )
        print(f"Pipeline execution started: {response['PipelineExecutionArn']}")
    
    return {
        "current_brier": current_brier,
        "threshold": BRIER_THRESHOLD,
        "retrain_triggered": current_brier > BRIER_THRESHOLD,
    }
```

The SageMaker Pipeline itself runs the full training job: pulls features from the feature store, trains the LightGBM ensemble with expanding-window CV (identical to the local architecture), calibrates, registers the new model, and deploys it if the validation Brier is better than the currently deployed model's.

The deploy-only-if-better gate is critical. An automated system that deploys degraded models because the retraining trigger fired is worse than no automation at all.

---

## What the System Looks Like Running

On a typical game day:

- **7:00 AM CT**: Lambda pulls yesterday's final box scores from NBA Stats API
- **8:00 AM CT**: Feature computation Lambda runs on yesterday's games, updates ELO ratings and RAPM estimates in DynamoDB
- **11:00 AM CT**: Odds Lambda pulls today's betting lines
- **12:00 PM CT**: Monitor Lambda computes trailing Brier, triggers retraining if needed
- **Afternoon**: Retraining job completes (typically 45 min), new model deployed if improved
- **6:00 PM CT**: Inference endpoint serves pre-game win probabilities for tonight's games

The system runs without human intervention on days when nothing breaks. On days when the NBA Stats API has issues or a new season format changes the data schema, monitoring surfaces the problem and I intervene manually.

---

## Remaining Work

**Player-level features.** The current model operates at the team level. Adding player availability (injury status, load management) as features would materially improve accuracy, especially for games where a key player is unexpectedly out. The data is available; the feature engineering is the work.

**Live in-game probabilities.** The current system generates pre-game probabilities. Updating them live — using in-game score, time remaining, and pace — is the next architectural layer. This requires a streaming ingestion path (Kinesis or SNS) rather than the current batch Lambda approach.

**The Brier threshold is too coarse.** A single Brier threshold for retraining doesn't account for the variance in game outcomes. A 0.22 Brier on a week of close games is fine; 0.22 on a week of blowouts might indicate a real model problem. I need a better monitoring metric.

---

*The local architecture this AWS layer deploys is described in [Part 1](/sports-ml-prediction-system-architecture.html). The repository at [github.com/kivanpolimis/sports-ml](https://github.com/kivanpolimis/sports-ml) contains the feature computation code; the AWS infrastructure is in a separate private repo pending cleanup.*
