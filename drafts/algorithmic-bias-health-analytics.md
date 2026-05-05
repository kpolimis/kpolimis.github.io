Title: When the Model Is the Problem: Algorithmic Bias in Health Analytics
Date: 2026-05-14
Category: Tutorials
Tags: health-equity, algorithmic-bias, data-science, causal-inference, machine-learning, public-policy, social-determinants
Slug: algorithmic-bias-health-analytics
Summary: A widely deployed commercial algorithm systematically underestimated the health needs of Black patients — not because of malicious design, but because cost was used as a proxy for need. This is the story of what went wrong, why it went wrong, and how to build models that don't replicate structural inequity.

---

In 2019, Obermeyer et al. published a paper in *Science* that should have been uncomfortable reading for anyone who builds healthcare models. They analyzed a commercial algorithm used by major US health systems to identify patients for high-risk care management programs. The algorithm assigned risk scores to patients. Higher score = more resources allocated.

They found that Black patients were assigned significantly lower risk scores than white patients with identical underlying health conditions. The algorithm was, in practice, directing resources away from Black patients who needed them.

The cause wasn't racist inputs. There was no race feature in the model. The cause was the choice of target variable: **healthcare cost**.

The algorithm predicted future healthcare costs and used that prediction as a proxy for healthcare need. But Black patients, on average, have lower healthcare costs than white patients with the same conditions — because they face more structural barriers to accessing care. Less access to care → less utilization → lower cost. The model learned the proxy (cost) rather than the underlying construct (need), and the proxy encoded decades of structural inequity.

This is what algorithmic bias looks like in practice. It's rarely intentional. It's almost always structural.

---

## Analytical Practices and Where Bias Enters

"Analytics" in healthcare covers a spectrum: descriptive dashboards that count things, diagnostic models that explain variance, predictive models that score future risk, and prescriptive systems that recommend interventions.

Bias can enter at every stage, but the highest-leverage points are:

**1. Data collection design.** Who gets measured, and how? Electronic health records (EHRs) systematically underrepresent patients who receive care outside formal health system settings — which skews toward lower-income, rural, and immigrant populations. A model trained on EHR data has a built-in gap for populations the system doesn't see.

**2. Target variable selection.** The Obermeyer et al. finding is the canonical example. Any target variable that is itself a product of structural inequity will teach the model to replicate that inequity. Cost, utilization, and prior diagnosis codes are all compromised proxies in this way.

**3. Feature selection.** Features that correlate with race (zip code, insurance type, prior diagnosis codes) allow a model to learn race-based patterns even when race is explicitly excluded. This is proximate discrimination — not using the protected attribute directly, but using correlated features to achieve the same effect.

**4. Threshold setting.** Even a well-calibrated model requires a decision threshold. Where that threshold is set determines who gets flagged for intervention. The same model can be more or less equitable depending on threshold choice, and threshold decisions are almost never documented or audited.

---

## A Framework: What Fairness Requires

Fairness in ML is not a single concept. There are multiple definitions, and they are often mutually incompatible. The three most commonly invoked:

**Demographic parity**: The positive prediction rate is equal across demographic groups.
```python
# Checking demographic parity
group_positive_rates = df.groupby("race")["predicted_high_risk"].mean()
```

**Equal opportunity**: The true positive rate (recall) is equal across groups.
```python
# Equal opportunity
group_recall = df.groupby("race").apply(
    lambda g: g["predicted_high_risk"][g["actual_high_risk"] == 1].mean()
)
```

**Calibration**: Among all patients with predicted risk p, approximately p% should actually be high-risk — within each demographic group.
```python
from sklearn.calibration import calibration_curve

# Check calibration separately per group
for group in df["race"].unique():
    subset = df[df["race"] == group]
    fraction_pos, mean_pred = calibration_curve(
        subset["actual_high_risk"],
        subset["predicted_risk"],
        n_bins=10
    )
```

The cruel mathematical fact: demographic parity and calibration cannot both be satisfied simultaneously when base rates differ across groups (which they almost always do in healthcare, due to structural factors). You have to choose what you're optimizing for, and that choice is a values decision, not a technical one.

---

## SDOH-Aware Regression: A Better Starting Point

The standard clinical risk model regresses outcomes on clinical variables: diagnosis codes, lab values, medication lists, prior utilization. These variables are all endogenous to the healthcare system — they measure what the system has done, not what the patient's health status actually is.

Social Determinants of Health (SDOH) — housing stability, food security, transportation access, neighborhood environment, occupational exposure — are typically excluded because they're not in the EHR.

This is not because SDOH are less important than clinical variables. It's because they're harder to collect.

A more honest model specification:

```r
library(fixest)

# Standard clinical model
model_clinical <- feols(
  readmission_30d ~ age + n_diagnoses + prior_utilization + 
    comorbidity_index | hospital + year,
  data = patient_panel,
  cluster = ~patient_id
)

# SDOH-augmented model
model_sdoh <- feols(
  readmission_30d ~ age + n_diagnoses + prior_utilization + 
    comorbidity_index + 
    # SDOH variables from census/community health data linked by zip code
    poverty_rate + housing_instability_index + food_desert_indicator +
    transportation_access_score |
    hospital + year,
  data = patient_panel,
  cluster = ~patient_id
)

# Compare model performance AND fairness metrics
compare_models(model_clinical, model_sdoh)
```

The key result to look for: does adding SDOH variables reduce the performance gap between demographic groups? If yes, the clinical-only model was systematically underestimating need for patients with adverse SDOH.

---

## The Measurement Framework Problem

Most healthcare analytics uses measurement frameworks that were validated on non-representative samples. The Charlson Comorbidity Index — ubiquitous in risk stratification — was developed in the 1980s on a predominantly white, insured population. Its validity for predicting outcomes in uninsured, elderly, or non-white populations is mixed.

Questions to ask before using any clinical measurement tool:

1. **On what population was this index validated?** Read the original paper.
2. **Does the validation population match your deployment population?** If not, external validity is uncertain.
3. **Has the index been tested for differential validity across demographic groups?** Most haven't.
4. **What is the index measuring versus what you need to measure?** Charlson measures coded diagnosis burden, not health status.

Vyas et al. (2020, *NEJM*) made this argument forcefully about race correction factors embedded in clinical algorithms — eGFR formulas that adjust kidney function estimates based on race, for example. These adjustments were based on population-level averages that masked within-group variation and, when embedded in clinical decision tools, led to systematic differences in treatment recommendations.

---

## Mitigation at the Design Stage

The most effective bias interventions happen before model training, not after.

**Pre-training:**

- **Audit your target variable.** Is it a proxy for something that encodes structural inequity? If so, find a better target or explicitly correct for the structural factor.
- **Map your data gaps.** Who is underrepresented in your training data, and why? Document it.
- **Disaggregate your evaluation set.** Build a test set that includes sufficient sample sizes within demographic subgroups to evaluate performance separately.

**During training:**

- **Reweighting.** Upweight underrepresented groups during training to prevent the model from optimizing primarily for the majority:
```python
from sklearn.utils.class_weight import compute_sample_weight

sample_weights = compute_sample_weight(
    class_weight={
        "White": 1.0,
        "Black": 2.5,   # adjust based on representation gap
        "Hispanic": 2.0,
        "Other": 1.5,
    },
    y=df["race"]
)

model.fit(X_train, y_train, sample_weight=sample_weights[train_idx])
```

- **Constrained optimization.** Some frameworks (Fairlearn, IBM AI Fairness 360) allow you to add fairness constraints directly to the optimization objective.

**Post-training:**

- **Threshold optimization per group.** Set different decision thresholds for different groups to equalize error rates. This is controversial — it involves explicitly treating groups differently — but may be the honest choice when base rates differ.
- **Ongoing monitoring.** Fairness metrics drift over time as populations change, care patterns shift, and the model's deployment context evolves. A model that was fair at deployment may not be fair two years later.

---

## What This Means for Practice

The Obermeyer et al. finding wasn't about a rogue algorithm or a bad actor. It was about the field's default assumptions: that cost is a reasonable proxy for need, that a model that performs well on aggregate metrics is performing well for everyone, that checking for race as an input is sufficient for fairness.

None of those assumptions are correct.

Every model deployed in a high-stakes setting — clinical risk stratification, benefit eligibility determination, resource allocation — warrants a fairness audit before deployment and monitoring afterward. That audit needs to be disaggregated by the demographic characteristics most likely to be affected by the structural factors your proxy variables are encoding.

This is not a burden on top of good modeling. It is good modeling.

---

*References: Obermeyer, Z., et al. (2019). Dissecting racial bias in an algorithm used to manage the health of populations. Science, 366(6464), 447–453. Vyas, D.A., et al. (2020). Hidden in plain sight — reconsidering the use of race correction in clinical algorithms. NEJM, 383(9), 874–882.*
