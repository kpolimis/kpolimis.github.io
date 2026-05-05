Title: What 14,500 Withdrawn arXiv Papers Reveal About Scientific Self-Correction
Date: 2026-05-08
Category: Tutorials
Tags: arxiv, research-integrity, data-science, python, nlp, open-science, reproducibility
Slug: arxiv-withdrawn-papers-analysis
Summary: I scraped 14,500 arXiv withdrawal records and found systematic differences in how fields self-correct. Math has near-parity between critical and non-critical errors. CS skews heavily toward non-critical. One CS subdiscipline bucks the trend entirely. Here's the data and what it means.

---

Science is supposed to be self-correcting. The question nobody asks often enough is: *how fast, and in which directions?*

ArXiv — the preprint server that's become the primary venue for publishing in math, physics, computer science, and increasingly economics and social science — has a withdrawal mechanism. Authors can retract a preprint before it's formally published, leaving a tombstone record with the reason for withdrawal.

These records are publicly accessible via the OAI-PMH API. They're also almost completely understudied.

I've been harvesting them for a project I'm calling `arxiv-retracing`. Here's what 14,500 withdrawal records look like.

---

## The Data

The arXiv OAI-PMH endpoint returns withdrawal metadata in a structured format:

```python
import requests
from lxml import etree
from datetime import datetime, timedelta

OAI_BASE = "https://export.arxiv.org/oai2"

def harvest_withdrawals(
    from_date: str,
    until_date: str,
    metadata_prefix: str = "oai_dc",
) -> list[dict]:
    """
    Harvest withdrawal records from arXiv OAI-PMH endpoint.
    
    Withdrawn papers have a specific comment pattern:
    'This paper has been withdrawn' in the metadata.
    """
    params = {
        "verb": "ListRecords",
        "metadataPrefix": metadata_prefix,
        "from": from_date,
        "until": until_date,
    }
    
    records = []
    resumption_token = None
    
    while True:
        if resumption_token:
            params = {"verb": "ListRecords", "resumptionToken": resumption_token}
        
        response = requests.get(OAI_BASE, params=params)
        root = etree.fromstring(response.content)
        
        # Parse records, filter for withdrawals
        for record in root.findall(".//{http://www.openarchives.org/OAI/2.0/}record"):
            comment = extract_comment(record)
            if comment and "withdrawn" in comment.lower():
                records.append(parse_record(record))
        
        # Handle pagination
        token_el = root.find(".//{http://www.openarchives.org/OAI/2.0/}resumptionToken")
        if token_el is None or token_el.text is None:
            break
        resumption_token = token_el.text
    
    return records
```

The withdrawal reason is embedded in the `comments` field of the metadata. It's free text, which means classifying withdrawal reasons requires either manual coding or a text classifier. I used a combination: a regex-based rule classifier for common patterns (`"critical error"`, `"incomplete manuscript"`, `"subsumed"`) and an LLM for ambiguous cases.

---

## Withdrawal Reasons: A Taxonomy

After classification, the corpus breaks down as follows:

| Withdrawal Reason | Count | Pct |
|---|---|---|
| Critical error (results wrong) | 6,154 | 42.5% |
| Incomplete manuscript | 3,144 | 21.7% |
| Subsumed by another publication | 2,843 | 19.6% |
| Administrative issues | 878 | 6.1% |
| Reason not specified | 847 | 5.8% |
| Not novel / duplicate | 357 | 2.5% |
| Policy error | 135 | 0.9% |
| Typos only | 227 | 1.6% |

The 42.5% critical error rate is both encouraging and sobering. Encouraging because it means self-correction is happening at scale — people are finding and retracting papers where the main results are wrong. Sobering because 6,154 papers with critical errors made it far enough into a research pipeline to require a formal withdrawal notice.

The "subsumed" category is worth flagging: nearly 20% of withdrawals are papers that the authors pre-emptively withdrew because the work was covered by another publication. This is responsible behavior, but it's structurally different from error correction.

---

## Field-Level Patterns

The most interesting findings are at the field level. Raw withdrawal counts:

| Subject | Total | Critical Error | Other |
|---|---|---|---|
| math | 5,432 | 2,687 | 2,745 |
| cs | 3,970 | 1,541 | 2,429 |
| physics | 946 | 325 | 621 |
| cond-mat | 1,070 | 394 | 676 |
| quant-ph | 599 | 287 | 312 |

**Math is nearly split.** 2,687 critical errors versus 2,745 other withdrawals — essentially parity. This is what you'd hope to see in a field with clear right-and-wrong answers and strong verification norms. Mathematical proofs are either correct or they're not. When a mathematician withdraws a paper for a "critical error," the error is usually a gap in a proof, and the withdrawal is often followed by a corrected version.

**CS skews heavily toward non-critical.** Only 38.8% of CS withdrawals are critical errors, versus 49.5% for math. CS has a much higher rate of "subsumed," "not novel," and "incomplete" withdrawals. The interpretation: CS papers get posted to arXiv early in their development cycle, before they're complete, as a way to establish priority. More incomplete manuscripts + more priority-establishment = a different withdrawal distribution.

---

## The cs.DS Anomaly

One subdiscipline breaks the CS pattern entirely:

| Subdiscipline | Critical | Other | Critical % |
|---|---|---|---|
| cs.LG (Machine Learning) | 312 | 891 | 26.0% |
| cs.CV (Computer Vision) | 187 | 514 | 26.7% |
| cs.CL (Computation and Language) | 143 | 389 | 26.9% |
| cs.DS (Data Structures & Algorithms) | 103 | 69 | 59.9% |

`cs.DS` has a critical error rate more than twice any other CS subdiscipline. This is theoretically interesting: data structures and algorithms is the CS subdiscipline most like mathematics — there are right answers, proofs of correctness, and tight formal verification norms. The withdrawal distribution reflects that.

The `cs.LG` rate of 26% is a different story. Machine learning papers are methodologically complex, often empirically evaluated rather than formally proven, and frequently withdrawn because a competing paper rendered them obsolete. The self-correction mechanism in ML is citation pressure, not retraction.

---

## Rate Adjustment: The Analysis I Can't Do Yet

Everything I've shown is raw counts. To make field-level comparisons that are actually meaningful, I need to normalize by the number of papers submitted in each field per year — the denominator.

A field with 100 withdrawals out of 200 submissions (50% withdrawal rate) is behaving very differently from one with 100 withdrawals out of 50,000 submissions (0.2% withdrawal rate). I'm in the process of pulling total submission counts by field and year from the same OAI-PMH API.

The other denominator problem: time. ArXiv was adopted by different fields at different times. Math and physics have been using it since the early 1990s; CS adoption accelerated in the mid-2000s; social science and economics are late arrivals. Comparing raw counts across fields without accounting for institutional age is comparing apples and Pell grants.

The rate-adjusted analysis will be a separate post — and arguably the main contribution of the paper.

---

## What This Tells Us About Open Science

A few things stand out from the raw patterns:

**Withdrawal is not uniformly bad.** The "subsumed" and "incomplete" categories represent healthy preprint culture — researchers posting work in progress, then responsibly cleaning up when it's superseded. The problem is when those records are treated as published work by automated systems (citation managers, news aggregators) before the withdrawal is processed.

**Critical errors cluster in specific areas.** The cs.DS anomaly suggests that formal verification norms push researchers to catch their own errors at higher rates. Interventions that increase the formalism of ML research — reproducibility checklists, required code submission, preregistration — might shift the cs.LG distribution toward cs.DS patterns.

**The "reason not specified" problem.** 847 papers (5.8%) were withdrawn with no stated reason. This is a gap in the record. For a scientific error-tracking system to function, withdrawal reasons need to be structured — not free text, and not optional.

---

## Next Steps

The data pipeline is in `arxiv-retracing` on GitHub. What's coming:

1. **Rate adjustment** — normalize by submissions per field per year
2. **Author disambiguation** — link withdrawals to OpenAlex author entities to study institutional and career-stage patterns
3. **Citation impact** — do papers with critical errors get cited before their withdrawal is processed?
4. **Temporal trends** — has the critical error rate in ML increased as the field has grown? (Informal hypothesis: yes, because the incentive to post fast is stronger than ever.)

The paper will be submitted to *Scientometrics* or *PLOS ONE* — open science research should be open access.

---

*Data: arXiv OAI-PMH API. Code: `arxiv-retracing` repo (link forthcoming at submission). If you're interested in the methodology or want to collaborate on the rate adjustment analysis, reach out.*
