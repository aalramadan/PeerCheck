"""Tests of the CoCoDet port with a small fake encoder, offline."""

import logging
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
tokenizers = pytest.importorskip("tokenizers")
cocodet = pytest.importorskip("peercheck.reviews.cocodet")

ORIGINAL_HEAD_KEYS = {"main_classifier_weight", "content_classifier.weight", "content_classifier.bias",
                      "style_classifier.weight", "style_classifier.bias", "fine_grained_classifier.weight",
                      "fine_grained_classifier.bias"}
WORDS = ["[PAD]", "[UNK]", "the", "paper", "is", "clear", "results", "are", "strong"]
MIXED_LENGTHS = ["results are strong " * 30, "the paper", "", "the paper is clear " * 9, "strong", "  ",
                 "clear results " * 40, "is", "the results are clear", "paper " * 70, "are strong", "the"]


class FakeEncoder(torch.nn.Module):
    def __init__(self, hidden=4):
        super().__init__()
        self.config = SimpleNamespace(hidden_size=hidden)
        self.embed = torch.nn.Embedding(50, hidden)

    def forward(self, input_ids, attention_mask):
        return SimpleNamespace(last_hidden_state=self.embed(input_ids))


class PoolingEncoder(FakeEncoder):
    """Put the mean of the unmasked embeddings first, so that a verdict depends on the whole text."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def forward(self, input_ids, attention_mask):
        self.calls.append((attention_mask.tolist(), torch.is_inference_mode_enabled()))
        states = self.embed(input_ids)
        weights = attention_mask.unsqueeze(-1).float()
        pooled = (states * weights).sum(dim=1, keepdim=True) / weights.sum(dim=1, keepdim=True)
        return SimpleNamespace(last_hidden_state=torch.cat([pooled, states[:, 1:]], dim=1))


class CountingTokenizer:
    """Pass each call to a tokenizer and keep the texts that it tokenized."""

    def __init__(self, tokenizer):
        self.tokenizer, self.texts = tokenizer, []

    def __call__(self, text, *args, **kwargs):
        self.texts += text if isinstance(text, list) else [text]
        return self.tokenizer(text, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.tokenizer, name)


@pytest.fixture
def small_detector(tmp_path, monkeypatch):
    """Return a Detector on a pooling stand-in encoder with random heads and a word tokenizer."""
    torch.manual_seed(0)
    encoder = PoolingEncoder()
    model = cocodet.CoCoDetModel(encoder)
    # The main head starts as torch.empty, whose values change from run to run.
    torch.nn.init.normal_(model.main_classifier_weight)
    saved = tmp_path / "CoCoDet.bin"
    torch.save(model.state_dict(), saved)
    words = tokenizers.Tokenizer(tokenizers.models.WordLevel({w: i for i, w in enumerate(WORDS)}, unk_token="[UNK]"))
    words.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    tokenizer = transformers.PreTrainedTokenizerFast(tokenizer_object=words, pad_token="[PAD]", unk_token="[UNK]")
    monkeypatch.setattr(cocodet, "AutoTokenizer", SimpleNamespace(from_pretrained=lambda *args, **kwargs: tokenizer))
    monkeypatch.setattr(cocodet, "AutoModel", SimpleNamespace(from_pretrained=lambda *args, **kwargs: encoder))
    monkeypatch.setattr(cocodet, "weights", lambda: saved)
    return cocodet.Detector(device="cpu")


def _same_verdict(one, other) -> bool:
    return (one.label, one.fine_label, one.content_sources, one.style_sources, one.notes) == (
        other.label, other.fine_label, other.content_sources, other.style_sources, other.notes) and all(
        one.probabilities[k] == pytest.approx(other.probabilities[k], abs=1e-3) for k in cocodet.MAIN_LABELS)


def test_parameter_names_match_the_original_weights():
    names = {name for name in cocodet.CoCoDetModel(FakeEncoder()).state_dict() if not name.startswith("bert.")}
    assert names == ORIGINAL_HEAD_KEYS


def test_model_returns_logits_for_each_head():
    model = cocodet.CoCoDetModel(FakeEncoder()).eval()
    main, content, style, fine = model(torch.tensor([[1, 2, 3]]), torch.ones(1, 3, dtype=torch.long))
    assert [t.shape[1] for t in (main, content, style, fine)] == [3, 8, 7, 6]


def test_verdict_names_the_labels_and_sources():
    main = torch.tensor([0.0, 1.0, 9.0])
    content = torch.full((8,), -5.0)
    content[5] = 5.0
    style = torch.full((7,), -5.0)
    fine = torch.tensor([0.0, 0.0, 0.0, 0.0, 7.0, 0.0])
    verdict = cocodet._verdict(main, content, style, fine, truncated=True)
    assert verdict.label == "ai" and verdict.fine_name == "Machine-Generated"
    assert verdict.content_sources == ("gpt4o",) and verdict.style_sources == ()
    assert verdict.probabilities["ai"] > 0.99
    assert "longer than 2048 tokens" in verdict.notes[0]


def test_white_space_is_collapsed_as_in_the_original_suite():
    assert cocodet.normalize(" A  review\n\nwith\tgaps ") == "A review with gaps"


def test_weights_with_a_wrong_checksum_are_refused(tmp_path, monkeypatch):
    fake = tmp_path / "CoCoDet.bin"
    fake.write_bytes(b"not the weights")
    monkeypatch.setattr(cocodet, "hf_hub_download", lambda *args, **kwargs: str(fake))
    with pytest.raises(cocodet.ModelError, match="SHA-256"):
        cocodet.weights()


def test_detector_hides_the_report_on_unused_weights_of_the_base_model(tmp_path, monkeypatch):
    from transformers.utils import logging as transformers_logging

    def encoder(*args, **kwargs):
        transformers_logging.get_logger("transformers.modeling_utils").warning("LOAD REPORT: head.dense.weight")
        return FakeEncoder()

    saved = tmp_path / "CoCoDet.bin"
    torch.save(cocodet.CoCoDetModel(FakeEncoder()).state_dict(), saved)
    monkeypatch.setattr(cocodet, "AutoTokenizer", SimpleNamespace(from_pretrained=lambda *args, **kwargs: None))
    monkeypatch.setattr(cocodet, "AutoModel", SimpleNamespace(from_pretrained=encoder))
    monkeypatch.setattr(cocodet, "weights", lambda: saved)
    shown = []
    handler = logging.Handler()
    handler.emit = shown.append
    library = logging.getLogger("transformers")
    verbosity = transformers_logging.get_verbosity()
    transformers_logging.set_verbosity_warning()
    library.addHandler(handler)
    try:
        cocodet.Detector(device="cpu")
        assert transformers_logging.get_verbosity() == transformers_logging.WARNING
    finally:
        library.removeHandler(handler)
        transformers_logging.set_verbosity(verbosity)
    assert not shown


def test_verdicts_follow_the_order_of_the_input_whatever_the_lengths(small_detector):
    verdicts = small_detector.label(MIXED_LENGTHS)
    alone = [small_detector.label([text])[0] for text in MIXED_LENGTHS]
    assert len({v.probabilities["ai"] for v in alone if v}) > 5
    assert all(_same_verdict(v, a) if a else v is None for v, a in zip(verdicts, alone))


def test_empty_text_gets_no_verdict(small_detector):
    assert small_detector.label(["", " \n\t", "the paper"])[:2] == [None, None]
    assert small_detector.label([]) == []


def test_text_longer_than_the_limit_is_marked_as_cut(small_detector):
    cut, kept = small_detector.label(["the paper " * 1025, "the paper " * 1024])
    assert cut.notes == ("text longer than 2048 tokens; only the start was read",) and kept.notes == ()
    assert max(len(mask[0]) for mask, _ in small_detector.model.bert.calls) == cocodet.MAX_TOKENS


def test_each_text_is_tokenized_once(small_detector):
    small_detector.tokenizer = CountingTokenizer(small_detector.tokenizer)
    small_detector.label(MIXED_LENGTHS)
    assert sorted(small_detector.tokenizer.texts) == sorted(cocodet.normalize(t) for t in MIXED_LENGTHS if t.strip())


def test_texts_of_similar_length_share_a_batch(small_detector):
    small_detector.label(["the paper is clear " * 10, "the paper"] * cocodet.BATCH_SIZE)
    assert all(all(all(row) for row in mask) for mask, _ in small_detector.model.bert.calls)


def test_model_runs_in_inference_mode(small_detector):
    small_detector.label(["the paper is clear"])
    assert [inference for _, inference in small_detector.model.bert.calls] == [True]
