# External tools and data

This folder holds the tools and data of other authors that PeerCheck runs, ports, or copies from, each in a
folder of its own. PeerCheck runs the files in `hotcrp/`, `submission-checker/`, and `census-surnames/`. The
other folders keep the original for reference beside the port in `src/`. Each `PORT.md` lists the changes of a
port. `NOTICE.md` at the root of the repository lists every license.

| Folder | Origin | Version | License | Use in PeerCheck |
|---|---|---|---|---|
| `census-surnames/` | U.S. Census Bureau, Frequently Occurring Surnames from the 2010 Census | 2010 census | public domain | the 9,999 most common surnames, the pool of the canary check |
| `coconuts/` | github.com/icip-cas/CoCoNUTS | commit `25df608` | no license file | `infer.py`, original of the CoCoDet port, `src/reviews/cocodet.py` |
| `editlens/` | github.com/pangramlabs/EditLens | commit `05a588f` | CC BY-NC-SA 4.0 | code of Open Pangram without its data, original of `src/reviews/editlens.py` |
| `hallucinator/` | github.com/gianlucasb/hallucinator | release v0.2.4 | AGPL-3.0-or-later | Rust source of the reference checker, whose binary `peercheck setup references` downloads |
| `hotcrp/` | github.com/kohler/hotcrp | commit `4c1ef77` | GPL-2.0-or-later for `banal`, Click license for the rest | `banal`, which the layout check runs, and `affiliationmatchers.json`, the source of the word lists of the conflict check |
| `openreview-py/` | github.com/openreview/openreview-py | commit `9e8ba8e` | MIT | `openreview/tools.py`, the source of the webmail list of the conflict check |
| `phantomlint/` | github.com/tobycmurray/phantom-lint | commit `7f62001` | BSD-3-Clause | the PhantomLint package, the source of the phrases of the hidden-text check |
| `submission-checker/` | github.com/acmsigsoft/submission-checker | release v0.4.3, commit `3ffa1eb` | Apache-2.0 | revised source and built jar of the anonymity and template check |

PeerCheck reports the two detectors of AI-written reviews on their own. A test set outside the training data of
CoCoDet shows how each detector labels reviews. Its human reviews are the 1,014 official reviews of ICLR 2017 in
PeerRead (github.com/allenai/PeerRead), written in 2016. Five current models served by NVIDIA build wrote 297
reviews of 60 of these papers. A model also polished one human review of each of 98 papers. CoCoDet labels 273 of
the 297 AI reviews (91.9%) as AI and none of the human or polished reviews. EditLens labels 296 of the 297 AI
reviews as AI-Edited and none as AI. It also labels 89 of the 98 polished reviews (90.8%) and 51 of the 1,014
human reviews (5.0%) as AI-Edited. A rule that flagged only the reviews that the two detectors agreed on caught 208
of the 297 AI reviews (70.0%), therefore PeerCheck dropped that rule.

| Reviews | Count | CoCoDet AI | EditLens AI-Edited | EditLens AI |
|---|---|---|---|---|
| written by people, ICLR 2017 | 1,014 | 0 | 51 | 0 |
| polished by a model | 98 | 0 | 89 | 0 |
| written by DiffusionGemma 26B | 58 | 58 | 58 | 0 |
| written by Gemma 4 31B | 60 | 60 | 60 | 0 |
| written by Mistral Large 4 | 60 | 52 | 60 | 0 |
| written by Nemotron 3 Ultra | 60 | 56 | 60 | 0 |
| written by Step 5 | 59 | 47 | 58 | 0 |

On 900 reviews of the public CoCoNUTS test set (huggingface.co/datasets/khaaaaaan/CoCoNUTS, MIT license), whose
other splits trained CoCoDet, CoCoDet labels 298 of the 300 reviews written by AI as AI and 3 of the 450 written
by people, all three polished by AI.

Model weights and databases stay out, since setup downloads each of these files. These are CoCoDet with
ModernBERT-base, the EditLens weights, DBLP, and the Retraction Watch list. Python dependencies, such as
pdfguardrail and PyMuPDF, install with pip. The canary check follows the paper of Rao et al. (arXiv 2503.15772),
which comes without code.
