"""Binoculars scores that tell whether a review reads as written by a language model.

Binoculars (Hans et al., ICML 2024) divides the log-perplexity of a text under a performer model by the
cross-perplexity between an observer model and the performer. Text that a language model wrote scores low, and a text
whose score falls below the threshold reads as machine-written. This module ports the original code, which sits
untouched in ``external/binoculars`` with each change listed in ``external/binoculars/PORT.md``. The texts never
leave this machine. Only the model names reach Hugging Face, once, to download the weights.

The default pair is Falcon-7B as the observer and Falcon-7B-Instruct as the performer, at the commits pinned in
``REVISIONS``, with the published threshold that the original chose for a false positive rate of 0.01% on general
text. Any other pair needs its own threshold in the options.

Needs. torch, transformers 4.56 or newer, and accelerate, with bitsandbytes for 4-bit loading. The two models load one
at a time. The performer reads a chunk of texts and keeps the input of its output layer in CPU memory, about 4.7 MB per
text of 512 tokens for Falcon-7B. The observer then replaces the performer, and the output layer of the performer turns
the kept states back into the logits of the performer. Each model keeps bfloat16, as in the original. On a CUDA GPU too
small for a model, the layers that miss the GPU stay in the checkpoint on disk, where the system caches them, and move
to the GPU for each forward pass. On an RTX 4060 Laptop GPU with 8 GB, in a machine with 15 GB of RAM, the default pair
then peaks at 6.2 GB of GPU memory and takes 1.3 s per review of 464 tokens on average, in batches of eight, plus about
10 s per chunk to load the two models. With ``load_in_4bit``, each model loads in 4-bit NF4 instead, which peaks at
6.4 GB and takes 0.7 s per review plus about 20 s per chunk to load on the same GPU. The 4-bit scores fall 0.006 below
the bfloat16 scores on average, therefore 4-bit loading needs its own threshold. Without a GPU, each model takes about
14 GB of RAM in bfloat16, or 3.9 GB in 4-bit at about 21 s per forward pass of 512 tokens, with two passes per review.
The first run downloads about 29 GB for the default pair into the Hugging Face cache, or into the ``hf`` folder of the
``cache`` option.

Options, all optional:

- ``observer`` and ``performer``: Hugging Face names or local folders of the two models, by default
  ``tiiuae/falcon-7b`` and ``tiiuae/falcon-7b-instruct``. The two models must share one vocabulary.
- ``threshold``: the score below which a text reads as machine-written. The default, the published low-FPR threshold
  of about 0.8536, holds only for the default pair in bfloat16. Any other pair and 4-bit loading must set this option.
- ``max_tokens``: the tokens read from the start of each text, 512 by default as in the original.
- ``device``: ``auto`` (the default, a CUDA GPU when one is available and the CPU otherwise), ``cuda``, or ``cpu``.
- ``load_in_4bit``: load each model in 4-bit NF4 through bitsandbytes, false by default.
- ``batch_size``: the texts of one forward pass, 8 by default.
- ``chunk_size``: the texts read per load of the two models, 256 by default, which bounds the states kept in memory.
- ``cache``: the cache folder of PeerCheck, whose ``hf`` folder then holds the models in place of the Hugging Face
  cache.
"""

from __future__ import annotations

import contextlib
import gc
import math
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from huggingface_hub import snapshot_download
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BatchEncoding,
    BitsAndBytesConfig,
    PreTrainedModel,
    PreTrainedTokenizerBase,
)
from transformers.models.falcon import modeling_falcon

OBSERVER = "tiiuae/falcon-7b"
PERFORMER = "tiiuae/falcon-7b-instruct"
# The published threshold belongs to these weights, therefore the default pair loads at fixed commits.
REVISIONS = {
    OBSERVER: "ec89142b67d748a1865ea4451372db8313ada0d8",
    PERFORMER: "8782b5c5d8c9290412416618f36a133653e85285",
}
# BINOCULARS_FPR_THRESHOLD of the original, chosen with the default pair at bfloat16 for a false positive rate of 0.01%.
LOW_FPR_THRESHOLD = 0.8536432310785527
DEVICES = ("auto", "cuda", "cpu")
# GPU memory left free for the logits and the losses of a batch of eight texts of 512 tokens while layers stream.
GPU_RESERVE = 2 * 1024**3
OPTIONS = (
    "observer", "performer", "threshold", "max_tokens", "device", "load_in_4bit", "batch_size", "chunk_size", "cache",
)
# The files of a model that the port reads: the configuration, the tokenizer, and the weights in safetensors.
MODEL_FILES = ["*.json", "*.safetensors"]


@dataclass(frozen=True)
class Settings:
    """The two models, the threshold, and the resources of one scoring run."""

    observer: str
    performer: str
    threshold: float
    max_tokens: int
    device: str
    load_in_4bit: bool
    batch_size: int
    chunk_size: int
    cache_dir: str | None


@dataclass(frozen=True)
class TextScore:
    """The Binoculars score of one text, the threshold it was compared with, and the verdict.

    The score is None for a text with fewer than two tokens, since Binoculars needs at least one predicted token.
    """

    score: float | None
    threshold: float
    machine: bool
    tokens: int


def settings(options: dict[str, Any] | None = None) -> Settings:
    """Check the options and fill in the defaults, refusing the published threshold where it does not hold."""
    options = dict(options or {})
    unknown = sorted(set(options) - set(OPTIONS))
    if unknown:
        raise ValueError(f"binoculars: unknown options {', '.join(unknown)}; known options: {', '.join(OPTIONS)}")
    observer = str(options.get("observer") or OBSERVER)
    performer = str(options.get("performer") or PERFORMER)
    load_in_4bit = options.get("load_in_4bit", False)
    if load_in_4bit not in (True, False):
        raise ValueError("binoculars: load_in_4bit must be true or false")
    threshold = options.get("threshold")
    if threshold is None:
        if (observer, performer) != (OBSERVER, PERFORMER) or load_in_4bit:
            raise ValueError(
                f"binoculars: the published threshold holds only for {OBSERVER} with {PERFORMER} in bfloat16; "
                "set the threshold option for any other pair or for 4-bit loading"
            )
        threshold = LOW_FPR_THRESHOLD
    device = str(options.get("device") or "auto")
    if device not in DEVICES:
        raise ValueError(f"binoculars: device must be one of {', '.join(DEVICES)}")
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    cache = options.get("cache")
    return Settings(
        observer=observer,
        performer=performer,
        threshold=float(threshold),
        max_tokens=_count(options, "max_tokens", 512, 2),
        device=device,
        load_in_4bit=bool(load_in_4bit),
        batch_size=_count(options, "batch_size", 8, 1),
        chunk_size=_count(options, "chunk_size", 256, 1),
        cache_dir=str(Path(cache) / "hf") if cache else None,
    )


def install(cache: Path | None = None, options: dict[str, Any] | None = None) -> None:
    """Download the configuration, the tokenizer, and the weights of the two models into the cache.

    The models go into the ``hf`` folder of the cache folder of PeerCheck, or into the Hugging Face cache without one.
    """
    chosen = settings({**(options or {}), **({"cache": cache} if cache else {})})
    for name in (chosen.observer, chosen.performer):
        if not Path(name).is_dir():
            snapshot_download(
                name, revision=REVISIONS.get(name), cache_dir=chosen.cache_dir, allow_patterns=MODEL_FILES
            )


def score(texts: list[str], options: dict[str, Any] | None = None) -> list[TextScore]:
    """Return, for each text, its Binoculars score, the threshold, and whether the text reads as machine-written."""
    chosen = settings(options)
    if not texts:
        return []
    tokenizer = _shared_tokenizer(chosen)
    tokens = [len(ids) for ids in tokenizer(list(texts), truncation=True, max_length=chosen.max_tokens)["input_ids"]]
    readable = [index for index, count in enumerate(tokens) if count >= 2]
    values: dict[int, float] = {}
    for start in range(0, len(readable), chosen.chunk_size):
        chunk = readable[start:start + chosen.chunk_size]
        values.update(zip(chunk, _scores([texts[index] for index in chunk], tokenizer, chosen)))
    results = []
    for index, count in enumerate(tokens):
        value = values.get(index)
        if value is not None and not math.isfinite(value):
            value = None
        machine = value is not None and value < chosen.threshold
        results.append(TextScore(score=value, threshold=chosen.threshold, machine=machine, tokens=count))
    return results


def _scores(texts: list[str], tokenizer: PreTrainedTokenizerBase, chosen: Settings) -> list[float]:
    """Score one chunk with the performer first and the observer second, one model in memory at a time."""
    batches = [
        _encode(texts[start:start + chosen.batch_size], tokenizer, chosen.max_tokens)
        for start in range(0, len(texts), chosen.batch_size)
    ]
    log_ppl, kept, cross_ppl = [], [], []
    with tempfile.TemporaryDirectory() as folder, torch.inference_mode():
        performer = _load_model(chosen.performer, chosen, folder)
        head = performer.get_output_embeddings()
        weight = head.weight.detach()
        bias = None if head.bias is None else head.bias.detach()
        if weight.device.type == "meta":
            raise ValueError(f"binoculars: the output layer of {chosen.performer} does not fit the GPU")
        inputs: list[torch.Tensor] = []
        hook = head.register_forward_hook(lambda _module, args, _output: inputs.append(args[0]))
        for batch in batches:
            batch = batch.to(chosen.device)
            logits = performer(**batch).logits
            states = inputs.pop()
            if not kept:
                _check_head(states[:1], logits[:1], weight, bias, chosen.performer)
            log_ppl.extend(_perplexity(logits, batch))
            kept.append(states.cpu())
            del logits, states
        hook.remove()
        del performer, head, hook
        _release()
        observer = _load_model(chosen.observer, chosen, folder)
        for batch, states in zip(batches, kept):
            batch = batch.to(chosen.device)
            observer_logits = observer(**batch).logits
            performer_logits = F.linear(states.to(weight.device), weight, bias)
            cross_ppl.extend(_cross_perplexity(observer_logits, performer_logits, batch, tokenizer.pad_token_id))
            del observer_logits, performer_logits
        del observer, weight, bias
        _release()
    return [ppl / x_ppl for ppl, x_ppl in zip(log_ppl, cross_ppl)]


def _perplexity(logits: torch.Tensor, batch: BatchEncoding) -> list[float]:
    """Return perplexity() of the original for each text, with its operations and dtype, one text at a time."""
    values = []
    for row, ids, mask in zip(logits, batch["input_ids"], batch["attention_mask"]):
        shifted_logits = row[None, :-1, :].contiguous()
        shifted_labels = ids[None, 1:].contiguous()
        shifted_mask = mask[None, 1:].contiguous()
        loss = F.cross_entropy(shifted_logits.transpose(1, 2), shifted_labels, reduction="none")
        values.append(float(((loss * shifted_mask).sum(1) / shifted_mask.sum(1))[0]))
    return values


def _cross_perplexity(
    observer_logits: torch.Tensor, performer_logits: torch.Tensor, batch: BatchEncoding, pad_token_id: int
) -> list[float]:
    """Return entropy() of the original for each text, with its operations and dtype, one text at a time.

    entropy() is the cross-entropy of the performer's logits against the observer's probabilities, averaged over every
    position that holds no padding token, the last position included.
    """
    values = []
    for observed, performed, ids in zip(observer_logits, performer_logits, batch["input_ids"]):
        vocab = observed.shape[-1]
        probabilities = torch.softmax(observed[None], dim=-1).view(-1, vocab)
        loss = F.cross_entropy(performed[None].view(-1, vocab), probabilities, reduction="none").view(1, -1)
        padding_mask = (ids[None] != pad_token_id).type(torch.uint8)
        values.append(float(((loss * padding_mask).sum(1) / padding_mask.sum(1))[0]))
    return values


def _check_head(
    states: torch.Tensor, logits: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor | None, name: str
) -> None:
    # Loading one model at a time rebuilds the performer's logits from its last hidden states, which holds only for
    # an output layer that is a plain linear map, unlike one that caps or scales its logits.
    if not torch.allclose(F.linear(states, weight, bias).float(), logits.float(), rtol=1e-2, atol=1e-2):
        raise ValueError(f"binoculars: the output layer of {name} is no plain linear map, which this port needs")


def _shared_tokenizer(chosen: Settings) -> PreTrainedTokenizerBase:
    tokenizer = _load_tokenizer(chosen.observer, chosen.cache_dir)
    if tokenizer.get_vocab() != _load_tokenizer(chosen.performer, chosen.cache_dir).get_vocab():
        raise ValueError(f"binoculars: {chosen.observer} and {chosen.performer} use different tokenizers")
    if not tokenizer.pad_token:
        tokenizer.pad_token = tokenizer.eos_token
    # Padding on the right keeps the positions of the tokens of a text in any batch.
    tokenizer.padding_side = "right"
    return tokenizer


def _encode(texts: list[str], tokenizer: PreTrainedTokenizerBase, max_tokens: int) -> BatchEncoding:
    return tokenizer(
        texts,
        return_tensors="pt",
        padding="longest" if len(texts) > 1 else False,
        truncation=True,
        max_length=max_tokens,
        return_token_type_ids=False,
    )


def _load_tokenizer(name: str, cache_dir: str | None) -> PreTrainedTokenizerBase:
    return AutoTokenizer.from_pretrained(name, revision=REVISIONS.get(name), cache_dir=cache_dir)


def _load_model(name: str, chosen: Settings, folder: str) -> PreTrainedModel:
    options: dict[str, Any] = {
        "revision": REVISIONS.get(name), "cache_dir": chosen.cache_dir, "dtype": torch.bfloat16,
        "device_map": {"": chosen.device},
    }
    building = contextlib.nullcontext()
    if chosen.load_in_4bit:
        options["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        building = _plain_falcon_linear()
    elif chosen.device == "cuda":
        # The layers that miss the GPU stay in the checkpoint on disk, where the system caches them, and move to the
        # GPU for each forward pass.
        free, _ = torch.cuda.mem_get_info()
        options.update(device_map="auto", max_memory={0: max(free - GPU_RESERVE, 0)}, offload_folder=folder)
    with building:
        model = AutoModelForCausalLM.from_pretrained(name, **options)
    return model.eval()


@contextlib.contextmanager
def _plain_falcon_linear() -> Iterator[None]:
    """Build the layers of Falcon as torch.nn.Linear while the context lasts.

    transformers 5 hands a layer to bitsandbytes only if its type is exactly torch.nn.Linear, which skips the subclass
    FalconLinear and leaves Falcon in bfloat16. FalconLinear computes the same product as torch.nn.Linear.
    """
    original = modeling_falcon.FalconLinear
    modeling_falcon.FalconLinear = torch.nn.Linear
    try:
        yield
    finally:
        modeling_falcon.FalconLinear = original


def _release() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _count(options: dict[str, Any], key: str, default: int, least: int) -> int:
    value = options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < least:
        raise ValueError(f"binoculars: {key} must be a whole number of at least {least}")
    return value
