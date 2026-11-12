"""Tests of the CoCoDet port with a small fake encoder, offline."""

import logging
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
cocodet = pytest.importorskip("peercheck.reviews.cocodet")

ORIGINAL_HEAD_KEYS = {"main_classifier_weight", "content_classifier.weight", "content_classifier.bias",
                      "style_classifier.weight", "style_classifier.bias", "fine_grained_classifier.weight",
                      "fine_grained_classifier.bias"}


class FakeEncoder(torch.nn.Module):
    def __init__(self, hidden=4):
        super().__init__()
        self.config = SimpleNamespace(hidden_size=hidden)
        self.embed = torch.nn.Embedding(50, hidden)

    def forward(self, input_ids, attention_mask):
        return SimpleNamespace(last_hidden_state=self.embed(input_ids))


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
