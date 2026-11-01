"""Tests of the Binoculars port with two tiny random Falcon models and a word tokenizer built in memory."""

from __future__ import annotations

import gc
import importlib.util
import weakref
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
tokenizers = pytest.importorskip("tokenizers")

from peercheck.reviews import binoculars

SEEDS = {"tiny-observer": 1, "tiny-performer": 2, "tiny-other": 3}
TEXTS = [
    "the paper proposes a novel method for test generation",
    "the evaluation is weak since only three projects are used",
    "we suggest more baselines and the results are clear but weak",
    "novel method",
    "the results are clear",
]
WORDS = ["<|endoftext|>", "[UNK]", *dict.fromkeys(" ".join(TEXTS).split())]
TINY = {"observer": "tiny-observer", "performer": "tiny-performer", "threshold": 1.0, "device": "cpu"}
ORIGINAL_METRICS = Path(__file__).resolve().parent.parent / "third_party" / "binoculars" / "binoculars" / "metrics.py"


def make_tokenizer(words=WORDS):
    """Return a word-level tokenizer over the given words, with the end-of-text token of Falcon."""
    vocab = {word: index for index, word in enumerate(dict.fromkeys(words))}
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel(vocab, unk_token="[UNK]"))
    backend.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    return transformers.PreTrainedTokenizerFast(tokenizer_object=backend, eos_token="<|endoftext|>", unk_token="[UNK]")


def make_model(name, model_class=transformers.FalconForCausalLM):
    """Return a tiny random Falcon model whose weights depend only on its name."""
    torch.manual_seed(SEEDS[name])
    config = transformers.FalconConfig(
        vocab_size=len(WORDS), hidden_size=16, num_hidden_layers=2, num_attention_heads=2,
        bos_token_id=0, eos_token_id=0, initializer_range=0.5,
    )
    return model_class(config).eval()


class ScaledLogits(transformers.FalconForCausalLM):
    """A tiny model that scales its logits after its output layer, as a model with a logit scale does."""

    def forward(self, *args, **kwargs):
        output = super().forward(*args, **kwargs)
        output.logits = output.logits * 2.0
        return output


@pytest.fixture
def loads(monkeypatch):
    """Replace the downloads with the tiny models and return the names in the order they load."""
    order = []

    def load_model(name, chosen, folder):
        order.append(name)
        return make_model(name)

    monkeypatch.setattr(binoculars, "_load_tokenizer", lambda name, cache_dir: make_tokenizer())
    monkeypatch.setattr(binoculars, "_load_model", load_model)
    return order


def original_scores(texts, dtype=torch.float32):
    """Score each text alone with perplexity() and entropy() of the untouched original, both models in memory."""
    spec = importlib.util.spec_from_file_location("original_binoculars_metrics", ORIGINAL_METRICS)
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)
    tokenizer = make_tokenizer()
    tokenizer.pad_token = tokenizer.eos_token
    observer, performer = make_model("tiny-observer").to(dtype), make_model("tiny-performer").to(dtype)
    scores = []
    with torch.no_grad():
        for text in texts:
            encoding = tokenizer([text], return_tensors="pt", truncation=True, max_length=512,
                                 return_token_type_ids=False)
            observer_logits, performer_logits = observer(**encoding).logits, performer(**encoding).logits
            ppl = metrics.perplexity(encoding, performer_logits)
            x_ppl = metrics.entropy(observer_logits, performer_logits, encoding, tokenizer.pad_token_id)
            scores.append(float((ppl / x_ppl)[0]))
    return scores


class TestThreshold:
    def test_default_pair_takes_the_published_low_fpr_threshold(self):
        chosen = binoculars.settings({})
        assert (chosen.observer, chosen.performer) == ("tiiuae/falcon-7b", "tiiuae/falcon-7b-instruct")
        assert chosen.threshold == binoculars.LOW_FPR_THRESHOLD == 0.8536432310785527

    def test_other_pair_without_threshold_is_refused(self):
        with pytest.raises(ValueError, match="published threshold"):
            binoculars.settings({"observer": "tiny-observer", "performer": "tiny-performer"})

    def test_one_changed_model_without_threshold_is_refused(self):
        with pytest.raises(ValueError, match="published threshold"):
            binoculars.settings({"performer": "tiiuae/falcon-7b-instruct-v2"})

    def test_other_pair_with_threshold_keeps_that_threshold(self):
        chosen = binoculars.settings({"observer": "a", "performer": "b", "threshold": 0.9})
        assert (chosen.observer, chosen.performer, chosen.threshold) == ("a", "b", 0.9)

    def test_refusal_comes_before_any_model_loads(self, loads):
        with pytest.raises(ValueError):
            binoculars.score(TEXTS, {"observer": "tiny-observer", "performer": "tiny-performer"})
        assert loads == []

    def test_text_below_threshold_reads_as_machine_written(self, loads):
        results = binoculars.score(TEXTS, TINY)
        middle = sorted(result.score for result in results)[2]
        flagged = binoculars.score(TEXTS, {**TINY, "threshold": middle})
        assert [result.machine for result in flagged] == [result.score < middle for result in results]
        assert all(result.threshold == middle for result in flagged)


class TestOptions:
    def test_unknown_option_is_refused(self):
        with pytest.raises(ValueError, match="unknown options treshold"):
            binoculars.settings({"treshold": 0.9})

    @pytest.mark.parametrize("key, value", [("max_tokens", 1), ("batch_size", 0), ("chunk_size", "8"),
                                            ("batch_size", True), ("device", "tpu"), ("load_in_4bit", "false")])
    def test_invalid_value_is_refused(self, key, value):
        with pytest.raises(ValueError, match=key):
            binoculars.settings({key: value})

    def test_gpu_keeps_bfloat16_by_default(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        chosen = binoculars.settings({})
        assert (chosen.device, chosen.load_in_4bit, chosen.batch_size) == ("cuda", False, 8)

    def test_cpu_fallback_without_cuda(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        chosen = binoculars.settings({"device": None})
        assert (chosen.device, chosen.load_in_4bit) == ("cpu", False)

    def test_4bit_without_threshold_is_refused(self):
        with pytest.raises(ValueError, match="4-bit"):
            binoculars.settings({"load_in_4bit": True})
        assert binoculars.settings({"load_in_4bit": True, "threshold": 0.85}).load_in_4bit

    def test_cache_option_points_to_its_hugging_face_folder(self):
        assert binoculars.settings({"cache": "peercheck-cache"}).cache_dir == str(Path("peercheck-cache") / "hf")
        assert binoculars.settings({}).cache_dir is None


class TestScores:
    def test_scores_match_the_original_metrics(self, loads):
        results = binoculars.score(TEXTS, TINY)
        assert [result.score for result in results] == pytest.approx(original_scores(TEXTS), rel=1e-5)

    def test_scores_match_the_original_metrics_in_bfloat16(self, monkeypatch):
        monkeypatch.setattr(binoculars, "_load_tokenizer", lambda name, cache_dir: make_tokenizer())
        monkeypatch.setattr(binoculars, "_load_model", lambda name, chosen, folder: make_model(name).to(torch.bfloat16))
        results = binoculars.score(TEXTS, {**TINY, "batch_size": 1})
        assert [result.score for result in results] == pytest.approx(original_scores(TEXTS, torch.bfloat16), rel=1e-6)

    def test_scores_do_not_depend_on_batches_or_chunks(self, loads):
        single = [result.score for result in binoculars.score(TEXTS, {**TINY, "batch_size": 1})]
        for batch_size, chunk_size in ((2, 3), (4, 1), (8, 256)):
            options = {**TINY, "batch_size": batch_size, "chunk_size": chunk_size}
            assert [result.score for result in binoculars.score(TEXTS, options)] == pytest.approx(single, rel=1e-5)

    def test_long_text_is_cut_to_max_tokens(self, loads):
        long_text = " ".join(TEXTS)
        cut = binoculars.score([long_text], {**TINY, "max_tokens": 9})[0]
        assert cut.tokens == 9
        assert cut.score == pytest.approx(original_scores([" ".join(long_text.split()[:9])])[0], rel=1e-5)

    def test_text_shorter_than_two_tokens_gets_no_score(self, loads):
        results = binoculars.score(["", "novel", TEXTS[0]], TINY)
        assert [(result.score, result.machine, result.tokens) for result in results[:2]] == [
            (None, False, 0), (None, False, 1)]
        assert results[2].score == pytest.approx(original_scores([TEXTS[0]])[0], rel=1e-5)

    def test_no_texts_load_no_model(self, loads):
        assert binoculars.score([], TINY) == []
        assert loads == []


class TestMemory:
    def test_models_load_one_at_a_time_for_each_chunk(self, loads):
        binoculars.score(TEXTS, {**TINY, "chunk_size": 3})
        assert loads == ["tiny-performer", "tiny-observer"] * 2

    def test_performer_is_released_before_the_observer_loads(self, monkeypatch):
        alive = []

        def load_model(name, chosen, folder):
            gc.collect()
            assert not any(ref() is not None for ref in alive), "an earlier model is still in memory"
            model = make_model(name)
            alive.append(weakref.ref(model))
            return model

        monkeypatch.setattr(binoculars, "_load_tokenizer", lambda name, cache_dir: make_tokenizer())
        monkeypatch.setattr(binoculars, "_load_model", load_model)
        assert len(binoculars.score(TEXTS, {**TINY, "chunk_size": 3})) == len(TEXTS)
        assert len(alive) == 4


class TestPairs:
    def test_pair_with_different_vocabularies_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            binoculars, "_load_tokenizer",
            lambda name, cache_dir: make_tokenizer(WORDS + ["extra"]) if name == "tiny-other" else make_tokenizer())
        monkeypatch.setattr(binoculars, "_load_model", lambda name, chosen, folder: make_model(name))
        with pytest.raises(ValueError, match="different tokenizers"):
            binoculars.score(TEXTS, {**TINY, "performer": "tiny-other"})

    def test_performer_whose_logits_are_scaled_is_refused(self, monkeypatch):
        monkeypatch.setattr(binoculars, "_load_tokenizer", lambda name, cache_dir: make_tokenizer())
        monkeypatch.setattr(binoculars, "_load_model", lambda name, chosen, folder: make_model(name, ScaledLogits))
        with pytest.raises(ValueError, match="plain linear map"):
            binoculars.score(TEXTS, TINY)


class TestLoading:
    @pytest.fixture
    def calls(self, monkeypatch):
        """Record the options of each model load on a GPU with 7 GiB free, without loading any weights."""
        recorded = []

        def from_pretrained(name, **options):
            recorded.append(options)
            return make_model("tiny-observer")

        monkeypatch.setattr(binoculars.AutoModelForCausalLM, "from_pretrained", from_pretrained)
        monkeypatch.setattr(torch.cuda, "mem_get_info", lambda: (7 * 1024**3, 8 * 1024**3))
        return recorded

    def test_gpu_with_4bit_holds_the_whole_model(self, calls):
        chosen = binoculars.settings({"device": "cuda", "load_in_4bit": True, "threshold": 0.85})
        binoculars._load_model(binoculars.OBSERVER, chosen, "folder")
        assert calls[0]["device_map"] == {"": "cuda"}
        assert calls[0]["quantization_config"].load_in_4bit
        assert calls[0]["revision"] == "ec89142b67d748a1865ea4451372db8313ada0d8"

    def test_gpu_without_4bit_streams_the_layers_that_miss_it(self, calls):
        chosen = binoculars.settings({"device": "cuda", "load_in_4bit": False})
        binoculars._load_model(binoculars.PERFORMER, chosen, "folder")
        assert calls[0]["device_map"] == "auto"
        assert calls[0]["max_memory"] == {0: 7 * 1024**3 - binoculars.GPU_RESERVE}
        assert calls[0]["offload_folder"] == "folder"
        assert calls[0]["dtype"] is torch.bfloat16
        assert "quantization_config" not in calls[0]

    def test_cpu_holds_the_whole_model_in_bfloat16(self, calls):
        binoculars._load_model("local/model", binoculars.settings({**TINY, "observer": "local/model"}), "folder")
        assert calls[0]["device_map"] == {"": "cpu"}
        assert calls[0]["revision"] is None
        assert calls[0]["cache_dir"] is None
        assert "quantization_config" not in calls[0]

    def test_cache_option_reaches_the_model_load(self, calls):
        chosen = binoculars.settings({**TINY, "cache": "peercheck-cache"})
        binoculars._load_model("tiny-observer", chosen, "folder")
        assert calls[0]["cache_dir"] == str(Path("peercheck-cache") / "hf")

    def test_falcon_layers_load_in_4bit(self, tmp_path):
        pytest.importorskip("bitsandbytes")
        make_model("tiny-observer").save_pretrained(tmp_path)
        chosen = binoculars.settings({**TINY, "observer": str(tmp_path), "load_in_4bit": True})
        model = binoculars._load_model(str(tmp_path), chosen, str(tmp_path))
        kinds = {type(module).__name__ for module in model.modules()}
        assert "Linear4bit" in kinds
        assert "FalconLinear" not in kinds

    def test_falcon_layers_keep_their_class_without_4bit(self, tmp_path):
        make_model("tiny-observer").save_pretrained(tmp_path)
        chosen = binoculars.settings({**TINY, "observer": str(tmp_path)})
        model = binoculars._load_model(str(tmp_path), chosen, str(tmp_path))
        kinds = {type(module).__name__ for module in model.modules()}
        assert "FalconLinear" in kinds
        assert transformers.models.falcon.modeling_falcon.FalconLinear.__name__ == "FalconLinear"


class TestInstall:
    @pytest.fixture
    def downloads(self, monkeypatch):
        """Record each download instead of making it."""
        recorded = []
        monkeypatch.setattr(binoculars, "snapshot_download", lambda name, **options: recorded.append((name, options)))
        return recorded

    def test_install_downloads_the_default_pair_into_the_cache(self, downloads, tmp_path):
        binoculars.install(tmp_path)
        assert [name for name, _ in downloads] == ["tiiuae/falcon-7b", "tiiuae/falcon-7b-instruct"]
        assert [options["revision"] for _, options in downloads] == [
            "ec89142b67d748a1865ea4451372db8313ada0d8", "8782b5c5d8c9290412416618f36a133653e85285"]
        assert {options["cache_dir"] for _, options in downloads} == {str(tmp_path / "hf")}
        assert downloads[0][1]["allow_patterns"] == ["*.json", "*.safetensors"]

    def test_install_skips_a_model_in_a_local_folder(self, downloads, tmp_path):
        binoculars.install(None, {"observer": str(tmp_path), "performer": "other/model", "threshold": 0.9})
        assert [(name, options["cache_dir"]) for name, options in downloads] == [("other/model", None)]
