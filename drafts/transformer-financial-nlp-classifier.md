Title: Beyond the Label: Engineering a Transformer-Based Financial Transaction Classifier
Date: 2026-05-18
Category: Tutorials
Tags: nlp, transformers, finance, bert, fastapi, onnx, mlops, classification, custom-loss
Slug: transformer-financial-transaction-classifier
Summary: Financial transaction data is some of the noisiest text you'll encounter in production NLP. Off-the-shelf classifiers fail because they can't handle cryptic merchant IDs, extreme class imbalance, and semantic drift between training data and live transactions. Here's how I moved from heuristic-heavy regex to a fine-tuned BERT classifier with a custom loss function, wrapped in a FastAPI microservice with ONNX inference.

---

Transaction descriptions are designed for accounting systems, not humans. `SQ *STREET COFFEE HOU`. `APL* APPLE ITUNES`. `CHECKCARD 0413 WHOLEFDS MKT`. The merchant name is truncated, the channel prefix tells you the payment processor, and the actual category is implicit.

When I built a financial transaction classifier for a personal finance application, the first two weeks were a masterclass in everything that breaks when you take standard NLP approaches and apply them to this particular flavor of noisy text. The model that actually works in production looks quite different from the model that performs best on a clean benchmark.

---

## Why Standard Approaches Fail

**The vocabulary problem.** Pre-trained language models have rich representations of "Whole Foods Market" and "Apple iTunes Store." They have no representation of "WHOLEFDS MKT" or "APL* APPLE ITUNES" — these abbreviations don't appear in training corpora. The model has to generalize from a partial string match, which requires the fine-tuning data to include enough examples of the truncated form.

**The class imbalance problem.** A real transaction dataset looks roughly like this:

| Category | Pct of Transactions |
|---|---|
| Groceries | 22% |
| Dining | 18% |
| Transportation | 12% |
| Entertainment | 8% |
| Shopping | 14% |
| Utilities | 6% |
| Healthcare | 4% |
| Legal / Professional Services | 0.3% |
| Other | 15.7% |

A model trained with standard cross-entropy on this distribution will learn to predict "Groceries" or "Dining" for ambiguous inputs. It will have near-zero recall for rare categories like Legal Services — which are often high-value transactions where misclassification is most costly.

**The temporal drift problem.** Transaction description formats change. New payment processors emerge with new prefixes (`SQ *`, `PAYPAL *`, `CASH APP *`). New merchants appear. A model trained six months ago on a frozen dataset will quietly degrade as the live distribution shifts.

---

## The Architecture

```
Raw transaction description
         ↓
   Preprocessing
   (normalize, strip noise)
         ↓
   BERT-base-uncased
   (fine-tuned on financial corpus)
         ↓
   Custom weighted loss
   (handles class imbalance)
         ↓
   ONNX Runtime inference
   (60% latency reduction)
         ↓
   FastAPI microservice
         ↓
   Categorized transaction
```

---

## Step 1: Preprocessing

Before the model sees the text, a preprocessing layer normalizes the most common noise patterns:

```python
import re
from typing import Optional

# Common payment processor prefixes that add no categorical signal
PROCESSOR_PREFIXES = [
    r"^SQ \*",      # Square
    r"^PAYPAL \*",  # PayPal
    r"^CHECKCARD \d{4} ",  # Debit card prefix
    r"^APL\* ",     # Apple Pay
    r"^AMZN MKTP",  # Amazon Marketplace
]

CATEGORY_NORMALIZATIONS = {
    # Common abbreviations with known expansions
    r"\bWHOLEFDS\b": "Whole Foods",
    r"\bMKT\b": "Market",
    r"\bRSTRNT\b": "Restaurant",
    r"\bHOU\b": "House",
    r"\bSVC\b": "Service",
    r"\bINT\'L\b": "International",
}

def normalize_transaction(description: str) -> str:
    """
    Strip processor prefixes, normalize common abbreviations,
    remove trailing reference numbers.
    """
    text = description.upper().strip()
    
    # Remove processor prefixes
    for pattern in PROCESSOR_PREFIXES:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    
    # Normalize common abbreviations
    for abbr, expansion in CATEGORY_NORMALIZATIONS.items():
        text = re.sub(abbr, expansion, text, flags=re.IGNORECASE)
    
    # Remove trailing reference numbers (common in ACH and card transactions)
    text = re.sub(r"\s+\d{4,}\s*$", "", text)
    
    return text.strip()

# Examples:
# "SQ *STREET COFFEE HOU" → "STREET COFFEE HOUSE"
# "CHECKCARD 0413 WHOLEFDS MKT" → "WHOLE FOODS MARKET"
# "APL* APPLE ITUNES STORE 123456" → "APPLE ITUNES STORE"
```

This preprocessing step recovers meaningful text that the pre-trained tokenizer can handle. It doesn't fully solve the vocabulary problem, but it dramatically reduces the number of out-of-vocabulary tokens.

---

## Step 2: The Custom Loss Function

Standard cross-entropy loss treats all misclassifications equally. In financial categorization, they're not equal — misclassifying a legal services transaction as "Other" is more costly than misclassifying "Coffee Shop" as "Dining."

Two adjustments:

**Class weights** to address frequency imbalance:

```python
import torch
import torch.nn as nn
from sklearn.utils.class_weight import compute_class_weight
import numpy as np

def compute_category_weights(y_train: np.ndarray, device: str = "cpu") -> torch.Tensor:
    """
    Compute inverse-frequency class weights.
    Rare categories get higher weight, pushing the model to learn them.
    """
    classes = np.unique(y_train)
    weights = compute_class_weight(
        class_weight="balanced",
        classes=classes,
        y=y_train,
    )
    return torch.tensor(weights, dtype=torch.float32).to(device)


class WeightedCategoricalLoss(nn.Module):
    """
    Cross-entropy with per-class weighting and optional label smoothing.
    
    Label smoothing prevents overconfident predictions on ambiguous
    transactions — common when a merchant operates across categories
    (e.g., Target: groceries + general merchandise).
    """
    def __init__(
        self,
        class_weights: torch.Tensor,
        label_smoothing: float = 0.1,
    ):
        super().__init__()
        self.loss_fn = nn.CrossEntropyLoss(
            weight=class_weights,
            label_smoothing=label_smoothing,
        )
    
    def forward(
        self,
        logits: torch.Tensor,
        labels: torch.Tensor,
    ) -> torch.Tensor:
        return self.loss_fn(logits, labels)
```

Label smoothing (0.1) is particularly useful for financial categories because many transactions are genuinely ambiguous. A Costco transaction could be groceries, household goods, or gas. The model shouldn't be 99% confident either way.

---

## Step 3: Fine-Tuning BERT

```python
from transformers import (
    BertForSequenceClassification,
    BertTokenizer,
    TrainingArguments,
    Trainer,
)
from datasets import Dataset
import evaluate

tokenizer = BertTokenizer.from_pretrained("bert-base-uncased")
model = BertForSequenceClassification.from_pretrained(
    "bert-base-uncased",
    num_labels=len(CATEGORY_MAP),
)

def tokenize(examples):
    return tokenizer(
        examples["text"],
        padding="max_length",
        truncation=True,
        max_length=64,  # transaction descriptions are short; 64 is sufficient
    )

# Build dataset from labeled transactions
train_dataset = Dataset.from_dict({
    "text": [normalize_transaction(t) for t in train_descriptions],
    "labels": train_labels,
}).map(tokenize, batched=True)

# Training arguments
training_args = TrainingArguments(
    output_dir="./checkpoints",
    num_train_epochs=5,
    per_device_train_batch_size=32,
    per_device_eval_batch_size=64,
    warmup_steps=500,
    weight_decay=0.01,
    logging_dir="./logs",
    evaluation_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
    metric_for_best_model="f1_macro",  # macro F1 rewards rare category performance
)

# Custom trainer that uses our weighted loss
class WeightedTrainer(Trainer):
    def __init__(self, class_weights, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loss_fn = WeightedCategoricalLoss(class_weights)
    
    def compute_loss(self, model, inputs, return_outputs=False):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        loss = self.loss_fn(logits, labels)
        return (loss, outputs) if return_outputs else loss

class_weights = compute_category_weights(train_labels, device="cuda")

trainer = WeightedTrainer(
    class_weights=class_weights,
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    compute_metrics=lambda p: evaluate.load("f1").compute(
        predictions=p.predictions.argmax(-1),
        references=p.label_ids,
        average="macro",
    ),
)

trainer.train()
```

Using macro F1 as the evaluation metric for model selection rewards performance across all categories equally, not weighted by frequency. Without this, early stopping will favor the model that's best at predicting common categories.

---

## Step 4: ONNX Export for Inference

PyTorch model inference has overhead that matters in a microservice context. ONNX Runtime eliminates the PyTorch runtime from the inference path and compiles the model graph for the target hardware.

```python
import torch
from transformers import BertTokenizer

# Export to ONNX
tokenizer = BertTokenizer.from_pretrained("bert-base-uncased")
model.eval()

dummy_input = tokenizer(
    "dummy transaction description",
    return_tensors="pt",
    padding="max_length",
    truncation=True,
    max_length=64,
)

torch.onnx.export(
    model,
    (dummy_input["input_ids"], dummy_input["attention_mask"]),
    "transaction_classifier.onnx",
    input_names=["input_ids", "attention_mask"],
    output_names=["logits"],
    dynamic_axes={
        "input_ids": {0: "batch_size"},
        "attention_mask": {0: "batch_size"},
    },
    opset_version=14,
)

# Inference with ONNX Runtime
import onnxruntime as ort
import numpy as np

session = ort.InferenceSession(
    "transaction_classifier.onnx",
    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
)

def predict(description: str) -> dict:
    normalized = normalize_transaction(description)
    inputs = tokenizer(
        normalized,
        return_tensors="np",
        padding="max_length",
        truncation=True,
        max_length=64,
    )
    
    logits = session.run(
        ["logits"],
        {
            "input_ids": inputs["input_ids"],
            "attention_mask": inputs["attention_mask"],
        },
    )[0]
    
    probs = softmax(logits, axis=-1)[0]
    predicted_idx = probs.argmax()
    
    return {
        "category": CATEGORY_MAP[predicted_idx],
        "confidence": float(probs[predicted_idx]),
        "top_3": [
            {"category": CATEGORY_MAP[i], "confidence": float(probs[i])}
            for i in probs.argsort()[-3:][::-1]
        ],
    }
```

The ONNX export reduced inference latency by ~60% in benchmarking: from ~45ms to ~18ms per transaction on CPU. At transaction-level volumes (thousands per hour, not millions per second), this is not a bottleneck — but it removes inference from the latency budget, which matters when the microservice is in the critical path of a user-facing application.

---

## Step 5: FastAPI Microservice

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
import onnxruntime as ort

# Load model at startup, not per-request
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session = ort.InferenceSession("transaction_classifier.onnx")
    app.state.tokenizer = BertTokenizer.from_pretrained("bert-base-uncased")
    yield
    # Cleanup if needed

app = FastAPI(lifespan=lifespan)

class TransactionRequest(BaseModel):
    description: str
    amount: float | None = None  # amount available for future use

class CategoryPrediction(BaseModel):
    category: str
    confidence: float
    normalized_description: str
    top_3: list[dict]

@app.post("/classify", response_model=CategoryPrediction)
async def classify_transaction(request: TransactionRequest):
    if not request.description.strip():
        raise HTTPException(status_code=422, detail="Description cannot be empty")
    
    result = predict(request.description)
    
    return CategoryPrediction(
        category=result["category"],
        confidence=result["confidence"],
        normalized_description=normalize_transaction(request.description),
        top_3=result["top_3"],
    )

@app.get("/health")
async def health():
    return {"status": "ok", "model": "bert-base-financial-classifier-v2"}
```

The lifespan context manager ensures the ONNX session and tokenizer are loaded once at startup rather than on every request. This is standard FastAPI practice but worth making explicit — loading a BERT tokenizer per-request would add ~500ms to every call.

---

## Results

Evaluated on a held-out test set of 8,000 transactions (not seen during training):

| Category | Precision | Recall | F1 |
|---|---|---|---|
| Groceries | 0.94 | 0.93 | 0.93 |
| Dining | 0.91 | 0.90 | 0.90 |
| Transportation | 0.89 | 0.87 | 0.88 |
| Entertainment | 0.86 | 0.84 | 0.85 |
| Shopping | 0.83 | 0.81 | 0.82 |
| Healthcare | 0.88 | 0.79 | 0.83 |
| Legal Services | 0.79 | 0.71 | 0.75 |
| **Macro Average** | **0.87** | **0.84** | **0.85** |

The macro F1 of 0.85 across all categories, including rare ones like Legal Services, is the meaningful number — not the accuracy on the common categories. The custom loss function and balanced training objective are doing their job.

---

## What I'd Build Differently

**Amount as a feature.** A $3.50 transaction classified as "Coffee Shop" has high prior probability. A $3,500 transaction classified as "Coffee Shop" should trigger a confidence penalty. The `amount` field is in the API contract but not yet in the model.

**Online learning from corrections.** Users flag misclassified transactions. Right now those corrections go into a retraining queue for the next model version. They should also update a lightweight correction layer that overrides the base model for known patterns.

**Merchant normalization as a pre-step.** Many transactions that are hard for the model are trivial with a merchant lookup: if "SQ *BLUE BOTTLE COFFEE" maps to a known merchant entity, you can retrieve the category directly without inference. Building a merchant entity registry would dramatically reduce the tail of difficult predictions.

---

*The preprocessing code and ONNX export script are available on [my GitHub](https://github.com/kpolimis). The fine-tuned model weights are not public due to the proprietary training data, but the architecture and training procedure are fully documented here.*
