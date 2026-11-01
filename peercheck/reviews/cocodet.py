"""CoCoDet, the detector of AI-generated peer reviews from the CoCoNUTS work, ported for PeerCheck.

CoCoDet (Chen et al., ACL 2026) is a ModernBERT-base encoder with four heads. It labels the content of a
review as Human (written by a person, possibly translated or polished by a machine), Mix, or AI, and names
the likely sources of the content and of the style. This module runs the inference of the original script,
third_party/coconuts/infer.py, with the changes listed in third_party/coconuts/PORT.md. The weights come
from a pinned revision on Hugging Face into its cache (HF_HOME, by default ~/.cache/huggingface) and are
checked against their SHA-256 before loading. The model card
states that CoCoDet "should not be used as the sole arbiter of academic misconduct", therefore PeerCheck
reports each verdict as a lead for the chairs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import torch
import torch.nn.functional as F
from huggingface_hub import hf_hub_download
from torch import nn
from transformers import AutoModel, AutoTokenizer

MODEL_REPO = "khaaaaaan/CoCoDet"
MODEL_FILE = "CoCoDet.bin"
MODEL_REVISION = "7f60a5dcdad3af02767cb57da842ead41424c89d"
MODEL_SHA256 = "70506dfe4afbc11612d0c3aa480918250b68b5b9294ffe52aac6490f438b4143"
BASE_MODEL = "answerdotai/ModernBERT-base"
BASE_REVISION = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
# The training setting of CoCoNUTS (arXiv 2509.04460, Table 9) and the defaults of infer.py.
MAX_TOKENS = 2048
SCALE = 30.0
BATCH_SIZE = 8
MAIN_LABELS = ("human", "mix", "ai")
CONTENT_LABELS = ("human", "qwen25", "qwen3", "llama", "gemini", "gpt4o", "claude", "deepseek")
STYLE_LABELS = ("human", "qwen", "llama", "gemini", "gpt4o", "claude", "deepseek")
FINE_LABELS = ("hw", "hwmt", "hwmp", "hwmg", "mg", "mgmp")
FINE_NAMES = {
    "hw": "Human-Written",
    "hwmt": "Human-Written, Machine-Translated",
    "hwmp": "Human-Written, Machine-Polished",
    "hwmg": "Human-Written, Machine-Generated",
    "mg": "Machine-Generated",
    "mgmp": "Machine-Generated, Machine-Polished",
}


class ModelError(RuntimeError):
    """The CoCoDet weights failed their checksum or could not load."""


@dataclass(frozen=True)
class Verdict:
    """The CoCoDet labels of one review, with the probability of each main class."""

    label: str
    probabilities: dict[str, float]
    fine_label: str
    content_sources: tuple[str, ...] = ()
    style_sources: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def fine_name(self) -> str:
        """Return the readable name of the fine-grained label."""
        return FINE_NAMES.get(self.fine_label, self.fine_label)


class CoCoDetModel(nn.Module):
    """The four heads of CoCoDet on a ModernBERT encoder, with the parameter names of the original weights."""

    def __init__(self, encoder: nn.Module) -> None:
        super().__init__()
        self.bert = encoder
        hidden = encoder.config.hidden_size
        self.main_classifier_weight = nn.Parameter(torch.empty(len(MAIN_LABELS), hidden))
        self.content_classifier = nn.Linear(hidden, len(CONTENT_LABELS))
        self.style_classifier = nn.Linear(hidden, len(STYLE_LABELS))
        self.fine_grained_classifier = nn.Linear(hidden, len(FINE_LABELS))

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        """Return the logits of the main, content, style, and fine-grained heads."""
        pooled = self.bert(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state[:, 0]
        cosine = F.linear(F.normalize(pooled, p=2, dim=1), F.normalize(self.main_classifier_weight, p=2, dim=1))
        return (cosine * SCALE, self.content_classifier(pooled), self.style_classifier(pooled),
                self.fine_grained_classifier(pooled))


def weights() -> Path:
    """Download the CoCoDet weights at the pinned revision and verify their SHA-256."""
    path = Path(hf_hub_download(MODEL_REPO, MODEL_FILE, revision=MODEL_REVISION))
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != MODEL_SHA256:
        raise ModelError(f"{path} has SHA-256 {digest.hexdigest()}, expected {MODEL_SHA256}")
    return path


class Detector:
    """A loaded CoCoDet model that labels review texts."""

    def __init__(self, device: str | None = None) -> None:
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_REVISION)
        encoder = AutoModel.from_pretrained(BASE_MODEL, revision=BASE_REVISION)
        self.model = CoCoDetModel(encoder)
        state = torch.load(weights(), map_location="cpu", weights_only=True)
        try:
            self.model.load_state_dict(state)
        except RuntimeError as exc:
            raise ModelError(f"the CoCoDet weights do not fit the model: {exc}") from exc
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
                main, content, style, fine = self.model(encoded["input_ids"], encoded["attention_mask"])
            for row, (index, text) in enumerate(batch):
                verdicts[index] = _verdict(main[row], content[row], style[row], fine[row],
                                           truncated=len(self.tokenizer(text)["input_ids"]) > MAX_TOKENS)
        return verdicts


def normalize(text: str) -> str:
    """Collapse the white space of a review as the original suite did before inference."""
    return re.sub(r"\s+", " ", text or "").strip()


def _verdict(main, content, style, fine, truncated: bool) -> Verdict:
    probabilities = torch.softmax(main.float(), dim=0).tolist()
    notes = (f"text longer than {MAX_TOKENS} tokens; only the start was read",) if truncated else ()
    return Verdict(
        label=MAIN_LABELS[int(torch.argmax(main))],
        probabilities={name: round(p, 4) for name, p in zip(MAIN_LABELS, probabilities)},
        fine_label=FINE_LABELS[int(torch.argmax(fine))],
        content_sources=tuple(n for n, on in zip(CONTENT_LABELS, (torch.sigmoid(content) > 0.5).tolist()) if on),
        style_sources=tuple(n for n, on in zip(STYLE_LABELS, (torch.sigmoid(style) > 0.5).tolist()) if on),
        notes=notes,
    )
