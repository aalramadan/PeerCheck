"""Tests of the EditLens detector with a small random model, offline."""

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
tokenizers = pytest.importorskip("tokenizers")
editlens = pytest.importorskip("peercheck.reviews.editlens")

WORDS = ["[PAD]", "[UNK]", "the", "paper", "is", "clear", "results", "are", "strong"]


@pytest.fixture
def small_model(tmp_path, monkeypatch):
    """Serve a RoBERTa classifier with four buckets and a word tokenizer as the EditLens files."""
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


def test_notes_name_a_cut_text_and_a_text_shorter_than_the_training_texts():
    notes = editlens._verdict(torch.zeros(4), True, 20).notes
    assert "longer than 512 tokens" in notes[0] and "20 words, fewer than the 75" in notes[1]


def test_text_is_lowercased_with_its_white_space_collapsed():
    assert editlens.normalize("  The PAPER\n\nis   Clear ") == "the paper is clear"


def test_weights_come_from_the_pinned_revision(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(editlens, "snapshot_download", lambda repo, revision: calls.append((repo, revision)) or tmp_path)
    assert editlens.files() == tmp_path and calls == [(editlens.MODEL_REPO, editlens.MODEL_REVISION)]


def test_gated_weights_give_the_steps_to_get_access(monkeypatch):
    def gated(*args, **kwargs):
        raise editlens.GatedRepoError.__new__(editlens.GatedRepoError)

    monkeypatch.setattr(editlens, "snapshot_download", gated)
    with pytest.raises(editlens.ModelError, match="hf auth login"):
        editlens.files()


@pytest.mark.usefixtures("small_model")
def test_detector_labels_each_text_and_skips_empty_ones():
    verdicts = editlens.Detector(device="cpu").label(["The paper is clear.", " ", "results are strong " * 200])
    assert verdicts[1] is None and all(0.0 <= v.score <= 1.0 for v in (verdicts[0], verdicts[2]))
    assert verdicts[0].label in ("human", "ai-edited", "ai") and "longer than 512 tokens" in verdicts[2].notes[0]
