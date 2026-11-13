"""Tests of the EditLens detector with a small random model, offline."""

import math
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
tokenizers = pytest.importorskip("tokenizers")
editlens = pytest.importorskip("peercheck.reviews.editlens")

WORDS = ["[PAD]", "[UNK]", "the", "paper", "is", "clear", "results", "are", "strong"]
MIXED_LENGTHS = ["results are strong " * 30, "the paper", "", "the paper is clear " * 9, "strong", "  ",
                 "clear results " * 40, "is", "the results are clear", "paper " * 70, "are strong", "the"]


def _logits_with_score(score: float, low: int) -> torch.Tensor:
    """Return logits that split all weight between buckets low and low + 1 to give the score."""
    share = 3 * score - low
    logits = torch.full((4,), -100.0)
    logits[low], logits[low + 1] = 0.0, math.log(share / (1 - share))
    return logits


@pytest.fixture
def small_model(tmp_path, monkeypatch):
    """Serve a RoBERTa classifier with four buckets and a word tokenizer as the EditLens files."""
    torch.manual_seed(0)
    words = tokenizers.Tokenizer(tokenizers.models.WordLevel({w: i for i, w in enumerate(WORDS)}, unk_token="[UNK]"))
    words.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    transformers.PreTrainedTokenizerFast(tokenizer_object=words, pad_token="[PAD]",
                                         unk_token="[UNK]").save_pretrained(tmp_path)
    config = transformers.RobertaConfig(vocab_size=len(WORDS), hidden_size=8, num_hidden_layers=1,
                                        num_attention_heads=2, intermediate_size=16, max_position_embeddings=600,
                                        num_labels=4, pad_token_id=0)
    transformers.RobertaForSequenceClassification(config).save_pretrained(tmp_path)
    monkeypatch.setattr(editlens, "files", lambda: tmp_path)


def test_score_is_the_expected_bucket_divided_by_three():
    assert editlens._verdict(torch.tensor([0.0, 0.0, 0.0, 30.0]), False, 100) == editlens.Verdict("ai", 1.0)
    assert editlens._verdict(torch.tensor([30.0, 0.0, 0.0, 0.0]), False, 100) == editlens.Verdict("human", 0.0)
    assert editlens._verdict(torch.zeros(4), False, 100) == editlens.Verdict("ai-edited", 0.5)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a GPU")
def test_score_of_logits_on_the_gpu_matches_the_score_on_the_cpu():
    logits = torch.tensor([0.0, 0.0, 0.0, 30.0], device="cuda")
    assert editlens._verdict(logits, False, 100) == editlens.Verdict("ai", 1.0)


def test_notes_name_a_cut_text_or_else_a_text_shorter_than_the_training_texts():
    assert editlens._verdict(torch.zeros(4), True, 20).notes == (
        "text longer than 512 tokens; only the start was read",)
    assert editlens._verdict(torch.zeros(4), False, 20).notes == (
        "20 words, fewer than the 75 of the shortest training texts",)


def test_label_follows_the_score_that_the_report_shows():
    assert editlens._verdict(_logits_with_score(0.99696, 2), False, 100) == editlens.Verdict("ai", 0.997)
    assert editlens._verdict(_logits_with_score(0.09707, 0), False, 100) == editlens.Verdict("ai-edited", 0.0971)


def test_text_is_lowercased_with_its_white_space_collapsed():
    assert editlens.normalize("  The PAPER\n\nis   Clear ") == "the paper is clear"


def test_weights_come_from_the_pinned_revision(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(editlens, "snapshot_download",
                        lambda repo, revision: calls.append((repo, revision)) or tmp_path)
    assert editlens.files() == tmp_path and calls == [(editlens.MODEL_REPO, editlens.MODEL_REVISION)]


def test_gated_weights_give_the_steps_to_get_access(monkeypatch):
    def gated(*args, **kwargs):
        raise editlens.GatedRepoError.__new__(editlens.GatedRepoError)

    monkeypatch.setattr(editlens, "snapshot_download", gated)
    with pytest.raises(editlens.ModelError, match="hf auth login"):
        editlens.files()


@pytest.mark.usefixtures("small_model")
def test_words_of_a_text_without_spaces_are_counted_as_editlens_counts_them():
    (verdict,) = editlens.Detector(device="cpu").label(["，".join(["本文研究了不稳定的测试"] * 80)])
    assert verdict.notes == ()


@pytest.mark.usefixtures("small_model")
def test_detector_labels_each_text_and_skips_empty_ones():
    verdicts = editlens.Detector(device="cpu").label(["The paper is clear.", " ", "results are strong " * 200])
    assert verdicts[1] is None and all(0.0 <= v.score <= 1.0 for v in (verdicts[0], verdicts[2]))
    assert verdicts[0].label in ("human", "ai-edited", "ai") and "longer than 512 tokens" in verdicts[2].notes[0]


class CountingTokenizer:
    """Pass each call to a tokenizer and keep the texts that it tokenized."""

    def __init__(self, tokenizer):
        self.tokenizer, self.texts = tokenizer, []

    def __call__(self, text, *args, **kwargs):
        self.texts += text if isinstance(text, list) else [text]
        return self.tokenizer(text, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.tokenizer, name)


class TokenSumModel(torch.nn.Module):
    """Give each text the logits 0, 0, 0, and the log of the sum of its token ids, so its score depends on all of it."""

    def forward(self, input_ids, attention_mask, **kwargs):
        total = (input_ids * attention_mask).sum(dim=1).float()
        zeros = torch.zeros_like(total)
        return SimpleNamespace(logits=torch.stack([zeros, zeros, zeros, total.log()], dim=1))


@pytest.fixture
def small_detector(small_model):
    """Return a Detector on the small model that records the attention mask of each call and the inference mode."""
    detector = editlens.Detector(device="cpu")
    detector.calls = []
    detector.model.register_forward_pre_hook(lambda module, args, kwargs: detector.calls.append(
        (kwargs["attention_mask"].tolist(), torch.is_inference_mode_enabled())), with_kwargs=True)
    return detector


def test_verdicts_follow_the_order_of_the_input_whatever_the_lengths(small_detector):
    small_detector.model = TokenSumModel()
    verdicts = small_detector.label(MIXED_LENGTHS)
    alone = [small_detector.label([text])[0] for text in MIXED_LENGTHS]
    assert len({v.score for v in alone if v}) > 5 and verdicts == alone


def test_each_text_is_tokenized_once(small_detector):
    small_detector.tokenizer = CountingTokenizer(small_detector.tokenizer)
    small_detector.label(MIXED_LENGTHS)
    assert sorted(small_detector.tokenizer.texts) == sorted(editlens.normalize(t) for t in MIXED_LENGTHS if t.strip())


def test_texts_of_similar_length_share_a_batch(small_detector):
    small_detector.label(["the paper is clear " * 10, "the paper"] * editlens.BATCH_SIZE)
    assert all(all(all(row) for row in mask) for mask, _ in small_detector.calls)


def test_model_runs_in_inference_mode(small_detector):
    small_detector.label(["the paper is clear"])
    assert [inference for _, inference in small_detector.calls] == [True]
