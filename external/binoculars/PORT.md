# Port of Binoculars

## Original

- Binoculars by Abhimanyu Hans, Avi Schwarzschild, Valeriia Cherepanova, Hamid Kazemi, Aniruddha Saha, Micah
  Goldblum, Jonas Geiping, and Tom Goldstein, "Spotting LLMs With Binoculars: Zero-Shot Detection of
  Machine-Generated Text", ICML 2024, arXiv 2401.12070.
- Source: <https://github.com/ahans30/Binoculars> at commit `c8ae2f90d50ee696418bc71d8d9e5020e5f9d7b8` of
  2024-05-14, the newest commit of `main` on 2026-11-01. The archive
  `https://codeload.github.com/ahans30/Binoculars/tar.gz/c8ae2f90d50ee696418bc71d8d9e5020e5f9d7b8` has the SHA-256
  `25dcd32160889b015aa063157b58490ef4a80352d30ba149798b687873f9d91c`.
- License: BSD-3-Clause, in `LICENSE.md`.
- This folder holds every code file of that commit untouched. It leaves out `datasets/`, 194 MB of evaluation data,
  and `assets/`, the logo and the photo of the README. Both sit at the same commit.
- The README states: "This implementation is for academic purposes only and should not be considered as a consumer
  product. We also strongly caution against using Binoculars (or any detector) without human supervision."

## Port

The port is `src/reviews/binoculars.py`, with its tests in `tests/test_binoculars.py`. Two tests score five
texts with two tiny random models through `binoculars/metrics.py` of this folder and through the port. The scores agree
within a relative difference of 1e-5 in float32 and of 1e-6 in bfloat16.

The port keeps `Binoculars.compute_score`, the verdict of `Binoculars.predict`, `perplexity`, `entropy`, and
`assert_tokenizer_consistency`, with the same 512 tokens per text, the end-of-text token as the padding token, and the
same masks. It computes the two losses with the operations of `perplexity` and `entropy` in the dtype of the logits,
bfloat16 for the default pair, one text at a time. Its changes follow.

1. Memory. The original holds the two models in bfloat16 at once, about 28 GB for the default pair. The port loads one
   model at a time. The performer reads a chunk of texts first and keeps the input of its output layer, caught by a
   forward hook, and the weights of that layer. The observer then replaces the performer, and the port rebuilds the
   performer's logits with these weights. A check on the first text of each chunk refuses a performer whose logits
   differ from its output layer applied to the kept states, such as a model that caps or scales its logits. On a CUDA
   GPU a model either keeps bfloat16, with the layers that miss the GPU read from the checkpoint on disk for each
   forward pass through accelerate, or loads in 4-bit NF4 through bitsandbytes, with double quantization and bfloat16
   compute.
2. Threshold. The published low-false-positive threshold, `BINOCULARS_FPR_THRESHOLD`, applies only to the default
   pair at the pinned commits in bfloat16. Any other pair and 4-bit loading need the `threshold` option, since 4-bit
   scores fall below the bfloat16 scores, as the measurements below show. The original applies the threshold to any
   pair. The `accuracy` mode is left out, since PeerCheck flags reviews at the low false positive rate.
3. Loading. The port never sets `trust_remote_code`, since transformers has Falcon built in. The default pair loads at
   the commits `ec89142b67d748a1865ea4451372db8313ada0d8` of `tiiuae/falcon-7b` and
   `8782b5c5d8c9290412416618f36a133653e85285` of `tiiuae/falcon-7b-instruct`. It passes `dtype` in place of
   `torch_dtype`, as transformers 4.56 and newer expect, and leaves `HF_TOKEN` to huggingface_hub. `install()`
   downloads only the configuration, the tokenizer, and the safetensors weights, and the `cache` option moves the
   models into the `hf` folder of the cache of PeerCheck.
4. Batches. The port reads eight texts per forward pass by default and pads on the right, the default of the Falcon
   tokenizer, therefore a text keeps its positions in any batch. The original reads the whole list in one batch, and
   its experiments use batches of 32.
5. Short texts. A text with fewer than two tokens gets no score. The original returns NaN for a text of one token
   and fails on an empty text.
6. Gradients. The original turns gradients off for the whole process when it is imported. The port uses
   `torch.inference_mode()` inside the scoring only.
7. Quantization. transformers 5 hands a layer to bitsandbytes only if its type is exactly `torch.nn.Linear`. It
   therefore skips `FalconLinear`, a subclass, and leaves Falcon in bfloat16 under a 4-bit configuration. While a model
   loads in 4-bit, the port builds the layers of Falcon as `torch.nn.Linear`, which computes the same product.
8. Left out. The median, sampling, and temperature arguments of the metrics, which the detector never sets, the
   Gradio demo in `app.py` and `demo/`, `main.py`, and the experiment scripts in `experiments/`.

## Measured on this machine

The runs of 2026-11-01 used an RTX 4060 Laptop GPU with 8 GB in a machine with 15 GB of RAM, with torch 2.15.0 for
CUDA 13.2, transformers 5.22.1, accelerate 1.15.0, and bitsandbytes 0.50.2. The texts are the sample text of the
original README and 150 reviews of the public CoCoNUTS test set (`khaaaaaan/CoCoNUTS` at commit
`ac418fb3dd2c2bbe0430683b0ab753a515de8315`, MIT license), 50 drawn with seed 0 from each of the labels `hw`
(human-written), `mg` (machine-generated), and `hwmp` (human-written, then polished by a machine). The texts hold 464
tokens on average.

- Reference. The metrics of the original, run untouched on the default pair in bfloat16 with the layers that miss the
  GPU streamed from disk, give 0.75661 for the README sample, the published value 0.75661373.
- Port in bfloat16. In batches of eight, the default, the port gives 0.75661 for the README sample. On the README sample
  and the first ten reviews of each label, 31 texts, its scores differ from the reference by 0.0004 on average and by
  0.0059 at most, and no verdict differs. Read one text at a time, the port gives the scores of the reference within
  5e-8 on all 31 texts.
- Loss arithmetic. The original computes the losses in bfloat16. Computed in float32 from the same logits, the README
  sample scores 0.75793, and one polished review moves from 0.8563 to 0.8508, across the threshold. The port therefore
  keeps the bfloat16 arithmetic of the original.
- Port in 4-bit. The port gives 0.7487 for the README sample. Over the 151 texts, its scores fall 0.0057 below the
  bfloat16 scores of the port on average and differ by 0.0246 at most. Three verdicts differ, all of polished reviews
  that only the 4-bit port flags.
- Verdicts. At the published threshold, the port in bfloat16 flags 0 of 50 human-written reviews, 22 of 50
  machine-generated reviews, and 4 of 50 polished reviews. In 4-bit it flags 0, 22, and 7.
- Time and memory with batches of eight texts. In bfloat16 with streaming, the port takes 1.26 s per text and 9.2 s to
  load the two models, and PyTorch reserves at most 6.18 GB of GPU memory. In 4-bit, it takes 0.70 s per text and 20.6 s
  to load, and PyTorch reserves at most 6.35 GB.
- CPU. In 4-bit, Falcon-7B takes 64 s to load and 3.90 GB of memory, and a forward pass of 512 tokens takes 20 to 22 s.
  The CPU in bfloat16 was not run, since the machine holds 15 GB of RAM and Falcon-7B takes 13.84 GB.
