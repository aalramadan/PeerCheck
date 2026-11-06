# External tools and data

- This folder holds the tools and data of other authors that PeerCheck runs, ports, or copies from, one folder
  each.
- PeerCheck runs the files in `hotcrp/`, `submission-checker/`, and `census-surnames/`.
- The other folders keep the original for reference beside the port in `src/`. Each `PORT.md` lists the changes.
- `NOTICE.md` at the root of the repository lists every license.

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

## Not in this folder

- Model weights and databases, which `peercheck setup` downloads. These are CoCoDet with ModernBERT-base, the
  EditLens weights, DBLP, and the Retraction Watch list.
- Python dependencies, such as pdfguardrail and PyMuPDF, which install with pip.
- Code of the canary check, since the paper of Rao et al. (arXiv 2503.15772) that the check follows comes without
  code.
