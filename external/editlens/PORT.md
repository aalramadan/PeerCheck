# EditLens in PeerCheck

PeerCheck runs EditLens, the detector that Pangram Labs released as Open Pangram, as its second detector of
AI-written reviews in `src/reviews/editlens.py`. PeerCheck runs no file of this copy.

## Version and license

- The repository is <https://github.com/pangramlabs/EditLens>. This copy holds its code at commit `05a588f`
  (2026-03-23). The data folder of that commit, about 94 MB, stays out.
- The gated weights come from `huggingface.co/pangram/editlens_roberta-large` at revision `f93e1ac`.
- The README of the repository licenses the code, the data, and the weights under CC BY-NC-SA 4.0, for
  non-commercial use only. PeerCheck itself uses GPL-3.0 and therefore runs its own code.

## What PeerCheck takes

- The inference of `scripts/inference.py`. The text is lowercased with its white space collapsed and cut at 512
  tokens. The score is the expected bucket of the four buckets divided by three.
- The calibration of the Open Pangram release post. Two thresholds maximize the F1 score on `data/val.csv` of
  that commit, over 1,000 even steps from 0 to 1. A score below 0.0971 reads as Human. A score of 0.997 or more
  reads as AI. Unlike `scripts/eval/ternary_eval.py`, PeerCheck keeps the scores on their own scale, since it
  labels one review at a time.
- PeerCheck reports the EditLens label beside the label of CoCoDet as a second opinion that marks no review,
  since EditLens labels most reviews that AI polished as AI-Edited. The Benchmark section of the main README gives
  the labels of the two detectors on a test set of reviews.

## Differences

- `clean_text` of `scripts/preprocess.py` also replaces emoji by their names and drops think tags and the opening
  line of a chat answer. PeerCheck keeps them, since a review keeps its evidence for the person who checks the
  review.
- PeerCheck runs only the RoBERTa-large model. The Llama-3.2-3B model adapts the gated Llama 3.2 base model and
  loads in 4 bits.
