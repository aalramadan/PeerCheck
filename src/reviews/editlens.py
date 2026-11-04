"""EditLens, the detector of AI writing that Pangram Labs released as Open Pangram, for PeerCheck.

EditLens (Thai et al., ICLR 2026, arXiv 2510.03154) scores how much of a text an AI wrote or edited, from 0 for
human writing to 1 for AI writing. PeerCheck runs the RoBERTa-large model of the release, a full model that reads
up to 512 tokens and sorts a text into four buckets. The other model of the release adapts the gated Llama 3.2
base model and stays out. As in scripts/inference.py of github.com/pangramlabs/EditLens, the text is lowercased
with its white space collapsed, and the score is the expected bucket divided by three. A score below 0.0971 reads
as Human, a score of 0.997 or more as AI, and a score between them as AI-Edited. Each threshold maximizes the F1
score on the released validation split (data/val.csv at commit 05a588f), the calibration of the release post.
With these thresholds, none of the 6,309 human texts of the five released test sets reads as AI.

The weights come from a pinned revision on Hugging Face into its cache. They are gated under CC BY-NC-SA 4.0, for
non-commercial use only, and each user accepts the terms on Hugging Face and logs in once with hf auth login. The
release post states that the models "should NOT be used to enforce any sort of AI usage policy in an educational
or professional setting", therefore an EditLens label alone is only a note in the report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from huggingface_hub.errors import GatedRepoError
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_REPO = "pangram/editlens_roberta-large"
MODEL_REVISION = "f93e1ace74528cfb48f337ab2fe946fb71a728cb"
MAX_TOKENS = 512
BATCH_SIZE = 8
HUMAN_BELOW = 0.0971
AI_FROM = 0.997
# The training data of EditLens keeps texts of 75 words or more (configs/roberta.yaml, min_words).
MIN_WORDS = 75
GATED = (f"EditLens is gated: accept its terms at https://huggingface.co/{MODEL_REPO} while logged in, then run "
         "hf auth login on this machine, or check the reviews with --detectors cocodet")


class ModelError(RuntimeError):
    """The EditLens weights are gated or could not load."""


@dataclass(frozen=True)
class Verdict:
    """The EditLens label of one review (human, ai-edited, or ai) with its score from 0 to 1."""

    label: str
    score: float
    notes: tuple[str, ...] = ()


def files() -> Path:
    """Download the model at the pinned revision and return its folder."""
    try:
        return Path(snapshot_download(MODEL_REPO, revision=MODEL_REVISION))
    except GatedRepoError as exc:
        raise ModelError(GATED) from exc


class Detector:
    """A loaded EditLens model that labels review texts."""

    def __init__(self, device: str | None = None) -> None:
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        folder = files()
        self.tokenizer = AutoTokenizer.from_pretrained(folder)
        self.model = AutoModelForSequenceClassification.from_pretrained(folder)
        self.model.to(self.device).eval()

    def label(self, texts: list[str]) -> list[Verdict | None]:
        """Label each text; an empty text gets None."""
        verdicts: list[Verdict | None] = [None] * len(texts)
        indexed = [(i, normalize(t)) for i, t in enumerate(texts) if normalize(t)]
        for start in range(0, len(indexed), BATCH_SIZE):
            batch = indexed[start:start + BATCH_SIZE]
            encoded = self.tokenizer([t for _, t in batch], truncation=True, max_length=MAX_TOKENS,
                                     padding=True, return_tensors="pt").to(self.device)
            with torch.no_grad():
                logits = self.model(**encoded).logits
            for row, (index, text) in enumerate(batch):
                verdicts[index] = _verdict(logits[row], truncated=len(self.tokenizer(text)["input_ids"]) > MAX_TOKENS,
                                           words=len(text.split()))
        return verdicts


def normalize(text: str) -> str:
    """Lowercase a review and collapse its white space, as EditLens does before inference."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _verdict(logits: torch.Tensor, truncated: bool, words: int) -> Verdict:
    probabilities = torch.softmax(logits.float(), dim=0)
    score = float(probabilities @ torch.arange(len(probabilities), dtype=torch.float32)) / (len(probabilities) - 1)
    label = "human" if score < HUMAN_BELOW else "ai" if score >= AI_FROM else "ai-edited"
    notes = ((f"text longer than {MAX_TOKENS} tokens; only the start was read",) if truncated else ()) + \
        ((f"{words} words, fewer than the {MIN_WORDS} of the shortest training texts",) if words < MIN_WORDS else ())
    return Verdict(label=label, score=round(score, 4), notes=notes)
