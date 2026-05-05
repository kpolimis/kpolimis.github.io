Title: Can We Measure Media Bias Computationally? Testing the Propaganda Model on Gaza and Ukraine Coverage
Date: 2026-05-07
Category: Tutorials
Tags: nlp, media-bias, computational-social-science, panel-regression, llm, text-as-data, causal-inference
Slug: measuring-media-bias-computationally-propaganda-model
Summary: Herman and Chomsky's 1988 "Manufacturing Consent" predicted that US media would cover victims of US-backed actors differently than victims of US-opposed actors. I'm building a computational test of that prediction using NLP, panel regression, and 30+ years of conflict coverage data. Here's the methodology and early findings.

---

In 1988, Edward Herman and Noam Chomsky published *Manufacturing Consent*, arguing that US media functions as a propaganda system — not through censorship, but through structural incentives. Their most operationalizable claim: American victims and victims of US-opposed states receive more sympathetic, more detailed coverage than victims of US-backed states. They called these "worthy" and "unworthy" victims.

The book was a landmark. It was also almost entirely qualitative — selected case studies, editorial comparisons, anecdotal evidence. Compelling, but not a test.

Thirty-eight years later, we have the tools to run that test.

---

## The Research Question

Do US media outlets systematically frame civilian victims differently based on the geopolitical alignment of the perpetrating state?

Operationally: does the *same outlet* cover Israeli airstrikes in Gaza differently than Russian airstrikes in Ukraine, controlling for casualty counts, conflict intensity, and outlet fixed effects?

This is a within-outlet comparison. I'm not asking "is the New York Times biased relative to Al Jazeera." I'm asking whether the New York Times frames similar events differently depending on which government is responsible — and whether that difference tracks US geopolitical alignment.

---

## Why This Is Hard (and Why It's Worth Doing)

The propaganda model has been critiqued for decades on the grounds that it's unfalsifiable. You can always find examples that support it and explain away examples that don't. The defenders of the model face the same problem: media coverage is so voluminous and so varied that without a systematic measurement approach, both sides are just curating examples.

Computational methods change this. With a large enough corpus, consistent coding rules, and a regression design that controls for confounders, we can make falsifiable claims about framing patterns.

The technical challenge is that "framing" is not a single variable. It's a bundle of choices:

- **Lexical choice**: "targeted strike" vs. "bombing"
- **Source selection**: government officials vs. NGOs vs. eyewitnesses
- **Casualty prominence**: does the article lead with the death toll?
- **Emotive language**: frequency of terms signaling civilian suffering
- **Historical context**: is the perpetrating government's role contextualized?

My pipeline has to measure all of these, consistently, across tens of thousands of articles.

---

## The Data

The corpus currently covers three conflicts:

| Conflict | Date Range | Articles | Outlets |
|---|---|---|---|
| Israel-Palestine (Gaza) | Oct 2023 – present | ~18,000 | 12 |
| Russia-Ukraine | Feb 2022 – present | ~22,000 | 12 |
| Control (prior Middle East) | 2015–2022 | ~8,000 | 12 |

Outlets include the New York Times, Washington Post, Fox News, NPR, Reuters, AP, the Guardian, Al Jazeera English, BBC, CNN, MSNBC, and the Wall Street Journal. The mix is deliberate — I need ideological variation within the US media ecosystem, plus international outlets as a baseline comparison.

Event-level conflict data comes from [ACLED](https://acleddata.com) (Armed Conflict Location and Event Dataset), which gives me daily casualty counts, event types, and geographic precision. This is the crucial denominator: I need to know how severe an event was to compare the intensity of coverage it received.

---

## The Measurement Pipeline

### Step 1: LLM-Based Frame Classification

Each article gets classified on four framing dimensions using a prompted LLM (GPT-4, temperature=0, model version pinned for reproducibility):

```python
FRAME_CLASSIFICATION_PROMPT = """
You are a content analysis assistant. Classify the following news article on four dimensions:

1. VICTIM_FRAMING: Rate 1-5 how sympathetically civilian victims are framed.
   (1=dehumanized/absent, 5=individualized/humanized with names and stories)

2. PERPETRATOR_ATTRIBUTION: Rate 1-5 directness of blame attribution to the perpetrator.
   (1=passive voice/no attribution, 5=direct causal attribution with accountability framing)

3. SOURCE_DIVERSITY: Rate 1-5 the diversity of sources quoted.
   (1=government/official only, 5=government + NGO + local witnesses + survivors)

4. HISTORICAL_CONTEXT: Rate 1-5 the depth of historical/political context provided.
   (1=none, 5=substantial context including international law, prior events)

Return ONLY a JSON object with keys: victim_framing, perpetrator_attribution, 
source_diversity, historical_context. Integer values only. No explanation.

Article:
{article_text}
"""
```

The LLM annotations are validated against a human-coded gold standard (n=500 articles, two coders, Cohen's kappa reported). This isn't optional — without inter-annotator agreement metrics, the classification is not scientific.

### Step 2: Lexical Asymmetry Score

Beyond the LLM classifications, I compute a lexical asymmetry score using a curated word list:

```python
# Simplified version of the lexical scorer
CIVILIAN_HARM_WORDS = {
    "high_emotive": ["massacre", "slaughter", "atrocity", "genocide", 
                     "war crime", "civilian", "children", "hospital"],
    "low_emotive": ["casualties", "fatalities", "collateral", "combatant",
                    "militant", "infrastructure", "targeted"],
}

def compute_lexical_asymmetry(article_text: str) -> float:
    """
    Returns ratio of high-emotive to total harm-related words.
    Higher values = more humanizing framing.
    """
    text_lower = article_text.lower()
    high_count = sum(text_lower.count(w) for w in CIVILIAN_HARM_WORDS["high_emotive"])
    low_count = sum(text_lower.count(w) for w in CIVILIAN_HARM_WORDS["low_emotive"])
    total = high_count + low_count
    return high_count / total if total > 0 else 0.5
```

This is a coarse instrument — a bag-of-words approach that misses context entirely. Its value is in volume: I can compute it for all 48,000 articles without API costs. I use it as a robustness check against the LLM classifications.

### Step 3: Panel Regression

The core identification strategy is a two-way fixed effects panel regression:

```
Framing_Score_iat = β₁(Conflict_it × US_Alignment_a) + β₂(Casualties_it) 
                  + α_i + α_a + α_t + ε_iat
```

Where:
- `i` indexes events (specific incidents)
- `a` indexes articles/outlets
- `t` indexes time
- `α_i`, `α_a`, `α_t` are event, outlet, and time fixed effects
- `Conflict_it × US_Alignment_a` is the interaction of interest

The outlet fixed effects are load-bearing. They absorb all time-invariant differences between the Times and Fox News. What's identified is the *within-outlet* change in framing across conflicts — and whether that change tracks US geopolitical alignment.

In R:

```r
library(fixest)

model <- feols(
  victim_framing ~ conflict:us_alignment + log1p(casualties) | 
    outlet + event_id + year_month,
  data = article_panel,
  cluster = ~outlet
)

summary(model)
```

`feols` from the `fixest` package handles large fixed effect structures efficiently and computes cluster-robust standard errors at the outlet level, which is where the serial correlation lives.

---

## Early Findings (Descriptive, Pre-Regression)

I want to be clear that what follows is descriptive. The regression model is not yet fully estimated. These are patterns in the raw data that motivate the design.

**Victim framing scores by conflict:**

| Conflict | Mean Victim Framing | SD |
|---|---|---|
| Gaza (Palestinian victims) | 2.41 | 0.89 |
| Ukraine (Ukrainian victims) | 3.87 | 0.71 |
| Gaza (Israeli victims) | 3.94 | 0.68 |

The gap between how Palestinian civilian victims are framed versus Ukrainian civilian victims — across the same outlets, in the same time period — is roughly 1.5 points on a 5-point scale. That's a large raw difference. Whether it survives outlet and event fixed effects, and whether it tracks US alignment rather than some other confounder, is what the regression will determine.

**I am not claiming this is evidence of bias.** Descriptive statistics without controls are not evidence of anything except correlation. The purpose of the regression is to establish whether the framing difference persists after controlling for casualty counts, event severity, outlet ideology, and time trends.

---

## What This Paper Contributes

Herman and Chomsky were right that the propaganda model makes testable predictions. They were wrong to think qualitative case studies constituted a test. This project:

1. **Operationalizes** the worthy/unworthy victim framework as measurable framing dimensions
2. **Applies** an identification strategy (two-way fixed effects) that controls for the most obvious confounders
3. **Validates** the measurement instrument against human coders
4. **Replicates** the analysis across three conflicts with different geopolitical alignments

If the model's prediction is correct, we should see a positive interaction between US geopolitical alignment of the perpetrator and victim framing scores, robust to controls. If the prediction fails, that's also a contribution — negative results in computational social science are systematically underreported.

---

## The Dashboard (Eventually)

Once the paper is submitted, I plan to build a public-facing version: paste a news article URL, get back frame classification scores, see how the article compares to the corpus for that outlet and conflict. The methodology becomes the public instrument.

The backend is the same pipeline. The frontend is a question of finding the time.

---

## Current Status

The corpus is assembled. The LLM annotation pipeline is running (rate-limited, costs real money). The lexical scorer is done. The panel regression specification is finalized but not yet estimated on the full corpus.

The paper is co-authored — more on that when it's closer to submission.

If you work in computational social science, NLP, or conflict research and have thoughts on the identification strategy or measurement approach, I'd genuinely like to hear from you: [kivan.polimis@gmail.com](mailto:kivan.polimis@gmail.com).

---

*Related: Herman, E.S. & Chomsky, N. (1988). Manufacturing Consent. Gilardi et al. (2023). ChatGPT outperforms crowd workers for text annotation. PNAS. Code will be released upon paper submission.*
