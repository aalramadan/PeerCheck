# CoCoDet port

`infer.py` in this folder is the original inference script of CoCoNUTS (Chen et al., ACL 2026), copied
unchanged from `github.com/icip-cas/CoCoNUTS` at commit `25df60884f` (2025-09-11), the only commit of
that repository. The repository has no license file. The model card of the weights
(`huggingface.co/khaaaaaan/CoCoDet`) states the MIT license.

PeerCheck runs the port in `src/peercheck/reviews/cocodet.py`. Each change from `infer.py` follows.

1. The port keeps inference only. The training labels of `InferenceDataset`, the t-SNE plot, and the
   imports of scikit-learn, matplotlib, and seaborn that only the plot needs are left out.
2. The weights come from revision `7f60a5dcdad3af02767cb57da842ead41424c89d` of `khaaaaaan/CoCoDet` and
   must match the SHA-256 `70506dfe4afbc11612d0c3aa480918250b68b5b9294ffe52aac6490f438b4143` before
   loading. `torch.load` runs with `weights_only=True`.
3. The encoder is `answerdotai/ModernBERT-base` at revision `8949b909ec900327062f0ebf497f51aef5e6f0c8`.
4. Each batch pads to its longest text instead of 2,048 tokens. The two kinds of padding give the same
   three class probabilities on a test review. Short reviews run faster.
5. The dropout layer and the arguments of the training loss (margin, cost margin, and class indexes) are
   left out, since dropout is 0.0 at inference and the loss is not computed.
6. `tokenizer(...)` replaces `encode_plus`, which recent releases of transformers deprecate.
7. Each verdict carries the probabilities of the three main classes and a note when a review exceeds
   2,048 tokens and only its start was read.
8. An empty review gets no verdict instead of stopping the run.

PeerCheck feeds the detector only the review fields meant for the authors, without their field names,
since CoCoNUTS trained on the main analysis and the questions to the authors. The original suite also
sent the confidential remarks for the program committee.
