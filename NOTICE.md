# Third-party notices

PeerCheck is licensed under the GNU General Public License version 3 (see `LICENSE`). It bundles,
ports, or downloads the work of other authors, each under its own license, as the table lists. Each
port keeps the original untouched beside it and lists its changes in a `PORT.md`.

| Component | Authors | Use in PeerCheck | License | Where |
|---|---|---|---|---|
| banal, the format analyzer of HotCRP | Geoffrey M. Voelker, Eddie Kohler | format check | GPL-2.0-or-later | `external/hotcrp/banal`, unchanged copy of `src/banal` of `kohler/hotcrp` commit `4c1ef77` |
| ACM SIGSOFT submission checker | Arie van Deursen, Tao Xie | anonymity and template check | Apache-2.0 | revised from release v0.4.3 of `acmsigsoft/submission-checker`, source in `external/submission-checker/`, built jar `external/submission-checker/submission-checker.jar` |
| Apache PDFBox 2.0.37, Commons CLI 1.5.0, Commons CSV 1.9.0, Commons Text 1.15.0, Gson 2.15.0 | Apache Software Foundation, Google | libraries inside the jar | Apache-2.0 | `external/submission-checker/submission-checker.jar` |
| CoCoNUTS inference script | Chen et al. (icip-cas) | base of the CoCoDet port | MIT, per the CoCoDet model card | `external/coconuts/infer.py`, port in `src/reviews/cocodet.py` |
| CoCoDet weights | Chen et al. (icip-cas) | detector of AI-written reviews | MIT, per the model card | downloaded from `huggingface.co/khaaaaaan/CoCoDet` |
| ModernBERT-base | Answer.AI, LightOn | encoder of CoCoDet | Apache-2.0 | downloaded from Hugging Face |
| EditLens RoBERTa-large (Open Pangram) | Pangram Labs (Thai et al.) | second detector of AI-written reviews | CC BY-NC-SA 4.0, gated, non-commercial use only | downloaded from `huggingface.co/pangram/editlens_roberta-large` at a pinned revision, never bundled; PeerCheck runs its own inference code, and its two thresholds come from the validation scores of `pangramlabs/EditLens` commit `05a588f`, whose code `external/editlens/` copies for reference |
| Frequently Occurring Surnames from the 2010 Census | U.S. Census Bureau | surnames of the canary citations | public domain, a work of the U.S. government | the 9,999 most common surnames in `external/census-surnames/census_surnames.txt` |
| Hallucinator | Stringhini and Blackburn | reference check | AGPL-3.0-or-later | binary downloaded by `peercheck setup references`; the source of release v0.2.4 sits in `external/hallucinator/` for reference, as its `PORT.md` describes |
| pdfguardrail 0.3.0 | GitHub user sugannathan | hidden-text check | MIT | Python dependency |
| aclpubcheck format checker | Association for Computational Linguistics | Times fonts of the font check and the approach of the margin check | MIT | names copied into `src/checks/fonts.py`; `aclpubcheck/formatchecker.py` of `acl-org/aclpubcheck` commit `fb584f3` sits in `external/aclpubcheck/` for reference |
| PhantomLint phrase list | Toby Murray | phrases of the hidden-text check | BSD-3-Clause | copied into `src/checks/hidden_text.py`; the package of `tobycmurray/phantom-lint` commit `7f62001` sits in `external/phantomlint/` for reference |
| HotCRP affiliation word lists | Eddie Kohler | affiliation matching of the conflict check | Click license (BSD style) | `etc/affiliationmatchers.json` of commit `4c1ef77` in `external/hotcrp/`, which the conflict check reads; `src/conflicts.py` follows the affiliation test of `src/authormatcher.php` and carries its notice |
| openreview-py webmail list | OpenReview | email domains of the conflict check | MIT | copied into `src/conflicts.py`; `openreview/tools.py` of commit `9e8ba8e` sits in `external/openreview-py/` for reference |
| Public Suffix List | Mozilla and the publicsuffix.org community | registrable domains of the email addresses in the conflict check | MPL-2.0 | version `2026-11-06_09-01-47_UTC` (commit `94ec5df`) from `publicsuffix.org/list/`, unchanged in `external/publicsuffix/` with its license, which the conflict check reads |
| PyMuPDF | Artifex | text and layout of PDFs | AGPL-3.0 or commercial | Python dependency |
| datasketch, rapidfuzz, openpyxl, PyYAML, lxml, defusedxml, pikepdf | their authors | near-duplicate search, fuzzy matching, spreadsheets, profiles, XML, PDF structure | MIT, MIT, MIT, MIT, BSD-3-Clause, PSF, MPL-2.0 | Python dependencies |
| DBLP data | Schloss Dagstuhl, University of Trier | conflict check and reference check | CC0 1.0 | downloaded from `dblp.org/xml/` |
| Retraction Watch data | Crossref, Retraction Watch | retracted references | no license stated in its README | downloaded from `gitlab.com/crossref/retraction-watch-data` |
| CoCoNUTS test reviews | Chen et al. (icip-cas) | texts of the sample reviews | MIT | `samples/reviews/` and `samples/hotcrp-reviews.csv` |
| CrackedPDFs sample | Thienpreecha and Subramanian | test fixtures of the hidden-text check | MIT | `tests/fixtures/hidden/crackedpdfs/` |
