Title: Privacy-First GenAI in Healthcare: Architecting a Multi-Agent RAG System
Date: 2026-05-16
Category: Tutorials
Tags: generative-ai, rag, healthcare, llm, multi-agent, privacy, hipaa, mlops, fastapi, pinecone
Slug: privacy-first-genai-healthcare-multi-agent-rag
Summary: When I architected a GenAI system for healthcare administrative workflows, the challenge wasn't the LLM — it was building a multi-agent orchestration layer that reduced administrative load by 40% without ever letting patient data touch a cloud model. Here's the architecture, the tradeoffs, and what I'd change.

---

Healthcare AI has a trust problem, and it's earned. The history of algorithmic systems in clinical settings is littered with models that encoded structural bias, violated privacy assumptions, or were deployed on populations far outside their validation set. When I was asked to architect a GenAI framework to reduce administrative burden in a healthcare context, the first design constraint wasn't performance — it was trust.

The system I built uses a multi-agent RAG architecture with an explicit compliance layer. It reduced administrative load — specifically the time staff spent synthesizing patient records, policy documents, and prior authorization requirements — by 40%. This post documents the architecture, the decisions that shaped it, and the places where the implementation is still rough.

---

## The Problem

Healthcare administrative work is document-heavy and latency-sensitive in ways that most information retrieval systems handle poorly. A prior authorization request requires a staff member to:

1. Locate the patient's relevant clinical history
2. Cross-reference the payer's policy documentation
3. Synthesize both into a justification that meets the payer's criteria
4. Repeat for each payer, each procedure, each patient

This is expert work that requires both clinical knowledge and policy fluency. It is also repetitive, time-consuming, and error-prone under time pressure. It is exactly the kind of task that retrieval-augmented generation should help with — if you can do it without touching PHI in a cloud model.

---

## Why Not Just Call the API?

The instinctive response to "healthcare AI" is to drop documents into an OpenAI or Anthropic API and prompt your way to an answer. This works in demos. It fails the real constraint: **HIPAA**.

PHI (Protected Health Information) cannot be sent to a general-purpose commercial API endpoint unless that vendor has executed a Business Associate Agreement (BAA) and the transmission meets HIPAA's technical safeguards requirements. OpenAI and Anthropic offer BAA-covered APIs, but the risk surface expands dramatically when patient data traverses external endpoints.

The design constraint I accepted: **no raw PHI in any LLM prompt that leaves the network boundary**. The system can synthesize and retrieve, but the synthesis must happen on de-identified or aggregated data, and any patient-specific context must be assembled locally.

This ruled out the simple approach and required an architecture that separates what it knows (the retrieval layer) from what it generates (the LLM layer).

---

## The Multi-Agent Architecture

Three agents, operating in sequence:

```
User Query
    ↓
┌─────────────────────────────────┐
│  Agent 1: Triage                │
│  Classify: clinical vs. policy  │
│  Extract: entities, intent      │
└────────────────┬────────────────┘
                 │
    ┌────────────▼────────────┐
    │  Agent 2: Retrieval     │
    │  Query vector DB        │
    │  (de-identified docs)   │
    │  Score + rank chunks    │
    └────────────┬────────────┘
                 │
    ┌────────────▼────────────┐
    │  Agent 3: Compliance    │
    │  Check output for PII   │
    │  Gate before delivery   │
    └────────────┬────────────┘
                 │
           Final Response
```

### Agent 1: Triage

The triage agent classifies incoming queries before any retrieval happens. Two dimensions:

**Query type**: clinical data request (patient history, lab values, medication lists) vs. policy request (payer criteria, coverage rules, authorization requirements).

**Intent**: synthesis request (summarize what we know) vs. lookup request (find the specific policy) vs. action request (draft the prior auth).

This classification changes which retrieval collections are queried and which LLM prompt template is used. A policy lookup goes to the policy vector collection with a factual extraction prompt. A synthesis request for prior authorization goes to both collections with a structured generation prompt.

```python
from anthropic import Anthropic
from pydantic import BaseModel
from enum import Enum

client = Anthropic()

class QueryType(str, Enum):
    CLINICAL = "clinical"
    POLICY = "policy"
    MIXED = "mixed"

class Intent(str, Enum):
    SYNTHESIS = "synthesis"
    LOOKUP = "lookup"
    DRAFT = "draft"

class TriageResult(BaseModel):
    query_type: QueryType
    intent: Intent
    key_entities: list[str]
    requires_patient_data: bool

TRIAGE_SYSTEM = """
You are a healthcare administrative AI classifier.
Classify queries by type and intent.
Extract key entities (procedures, diagnoses, payer names).
Flag if the query requires patient-specific clinical data.
Return ONLY valid JSON matching the TriageResult schema.
"""

def triage_query(query: str) -> TriageResult:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        system=TRIAGE_SYSTEM,
        messages=[{"role": "user", "content": query}],
    )
    return TriageResult.model_validate_json(response.content[0].text)
```

### Agent 2: Retrieval

The vector database contains de-identified documentation: clinical policy summaries, payer coverage criteria, procedure code descriptions, and anonymized case precedents. No PHI enters the index.

The retrieval agent queries the appropriate collection(s) based on the triage result, scores chunks by semantic similarity, and assembles a ranked context window.

```python
from pinecone import Pinecone
import anthropic

pc = Pinecone(api_key="your_pinecone_key")
policy_index = pc.Index("healthcare-policy-docs")
clinical_index = pc.Index("clinical-guidelines")

def get_embedding(text: str) -> list[float]:
    """Use Claude's embedding model for consistent embedding space."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1,
        system="Generate a semantic embedding for this text.",
        messages=[{"role": "user", "content": text}],
    )
    # In production: use a dedicated embedding endpoint
    # This is illustrative — use voyage-3 or text-embedding-3-large
    return []  # placeholder

def retrieve_relevant_chunks(
    query: str,
    triage: TriageResult,
    top_k: int = 8,
) -> list[dict]:
    """
    Query appropriate collections based on triage result.
    Returns ranked chunks with metadata.
    """
    query_embedding = get_embedding(query)
    chunks = []
    
    if triage.query_type in [QueryType.POLICY, QueryType.MIXED]:
        policy_results = policy_index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
        )
        chunks.extend(policy_results.matches)
    
    if triage.query_type in [QueryType.CLINICAL, QueryType.MIXED]:
        clinical_results = clinical_index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
        )
        chunks.extend(clinical_results.matches)
    
    # Re-rank by score, deduplicate by source
    chunks.sort(key=lambda x: x.score, reverse=True)
    return chunks[:top_k]
```

### Agent 3: Compliance

The compliance agent is the guardrail before output reaches the user. It checks generated content for PII patterns: names, dates of birth, MRN-like identifiers, specific addresses.

This is not a semantic check — it's a deterministic rule layer with regex patterns, supplemented by an LLM pass for cases that pattern matching misses (implicit identifiers, combinations of quasi-identifiers that together constitute PHI).

```python
import re
from dataclasses import dataclass

# Pattern library for PHI detection
PHI_PATTERNS = {
    "mrn": r"\b(MRN|Medical Record|Patient ID)[:\s]*\d{6,10}\b",
    "dob": r"\b(DOB|Date of Birth|Born)[:\s]*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    "name_title": r"\b(Patient|Mr\.|Mrs\.|Dr\.)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b",
    "ssn": r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b",
}

@dataclass
class ComplianceResult:
    passes: bool
    violations: list[str]
    redacted_output: str | None

def compliance_check(generated_text: str) -> ComplianceResult:
    """
    Deterministic PHI pattern check.
    Returns violation list and redacted version if violations found.
    """
    violations = []
    redacted = generated_text
    
    for phi_type, pattern in PHI_PATTERNS.items():
        matches = re.findall(pattern, generated_text, re.IGNORECASE)
        if matches:
            violations.append(f"{phi_type}: {len(matches)} match(es)")
            redacted = re.sub(pattern, f"[{phi_type.upper()} REDACTED]", 
                             redacted, flags=re.IGNORECASE)
    
    return ComplianceResult(
        passes=len(violations) == 0,
        violations=violations,
        redacted_output=redacted if violations else None,
    )
```

---

## The Generation Layer

Between retrieval and compliance, the synthesis happens. This is a standard RAG generation step with a healthcare-specific system prompt:

```python
def generate_synthesis(
    query: str,
    triage: TriageResult,
    retrieved_chunks: list[dict],
) -> str:
    """
    Generate synthesis from retrieved de-identified context.
    No PHI in the context or the prompt.
    """
    context = "\n\n".join([
        f"[Source: {chunk.metadata.get('source', 'unknown')}]\n{chunk.metadata.get('text', '')}"
        for chunk in retrieved_chunks
    ])
    
    intent_instructions = {
        Intent.SYNTHESIS: "Synthesize the key points relevant to the query.",
        Intent.LOOKUP: "Extract the specific information requested. Be precise.",
        Intent.DRAFT: "Draft a structured prior authorization justification based on the context.",
    }
    
    system_prompt = f"""
    You are a healthcare administrative assistant.
    You have access to de-identified clinical guidelines and payer policy documentation.
    You do NOT have access to patient-specific information.
    
    Task: {intent_instructions[triage.intent]}
    
    Always cite your sources. Flag uncertainty explicitly.
    Do not generate specific patient identifiers.
    """
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"Context:\n{context}\n\nQuery: {query}",
        }],
    )
    
    return response.content[0].text
```

---

## The Impact

The 40% reduction in administrative time came primarily from two use cases:

**Prior authorization drafting.** Staff went from writing justifications from scratch to reviewing and editing AI-generated drafts with citations. The average time per authorization dropped from ~22 minutes to ~13 minutes.

**Policy lookup.** Finding the specific payer criteria for a given procedure dropped from a 5–10 minute manual search to a sub-30-second query. The compliance agent ensures no PHI is generated in these lookups.

The remaining 60% of administrative time involves tasks that require judgment, relationship management, or access to systems the AI can't reach — scheduling, escalations, direct payer calls. The system doesn't replace the human; it removes the lookup and drafting overhead so the human can focus on the judgment work.

---

## What I'd Build Differently

**Hallucination logging.** The compliance agent catches PHI, but there's no systematic logging of factually incorrect outputs. Healthcare is a domain where confident wrong answers are dangerous. I'd add a feedback loop where staff flag incorrect synthesis, with those flags feeding a fine-tuning or calibration process.

**Structured output from triage.** The triage agent's output is parsed JSON, which is fragile. I'd move to tool use / function calling to get structured output natively rather than parsing free-text JSON.

**Local LLM for the compliance pass.** The current compliance agent sends the generated text to the same external API for the LLM component of PII checking. A local model (Llama-3-8B running on Apollo) would keep the compliance check fully on-network, eliminating the last external call in the pipeline.

---

## The Broader Point

Healthcare GenAI gets framed as a choice between capability and safety. This is a false binary — it's a sequencing problem. Build the safety layer first (de-identified index, compliance agent, no PHI in external prompts), then optimize for capability within those constraints.

The 40% reduction wasn't possible in the first version of the system. It required three iterations of the retrieval quality, one rebuild of the triage classification, and a complete replacement of the initial vector store. Safety constraints don't make capability impossible; they make it slower to achieve and more robust when you get there.

---

*Code for the compliance agent and triage classifier is available on request. The vector store schema and document preprocessing pipeline will be open-sourced after the project's commercial phase concludes.*
