# Third-party notices

PeerCheck is licensed under the GNU General Public License version 3 (see `LICENSE`). It bundles,
ports, or downloads the work of other authors, each under its own license, as the table lists. Each
port keeps the original untouched beside it and lists its changes in a `PORT.md`.

| Component | Authors | Use in PeerCheck | License | Where |
|---|---|---|---|---|
| banal, the format analyzer of HotCRP | Geoffrey M. Voelker, Eddie Kohler | format check | GPL-2.0-or-later | `peercheck/vendor/banal/banal`, unchanged copy of `kohler/hotcrp` commit `4c1ef77` |
| ACM SIGSOFT submission checker | Arie van Deursen, Tao Xie | anonymity and template check | Apache-2.0 | revised from release v0.4.3 of `acmsigsoft/submission-checker`, source in `external/submission-checker/`, built jar in `peercheck/vendor/submission-checker/` |
| Apache PDFBox 2.0.37, Commons CLI 1.5.0, Commons CSV 1.9.0, Commons Text 1.15.0, Gson 2.15.0 | Apache Software Foundation, Google | libraries inside the jar | Apache-2.0 | `peercheck/vendor/submission-checker/submission-checker.jar` |
| CoCoNUTS inference script | Chen et al. (icip-cas) | base of the CoCoDet port | no license file in the repository | `external/coconuts/infer.py`, port in `peercheck/reviews/cocodet.py` |
| CoCoDet weights | Chen et al. (icip-cas) | detector of AI-written reviews | MIT, per the model card | downloaded from `huggingface.co/khaaaaaan/CoCoDet` |
| ModernBERT-base | Answer.AI, LightOn | encoder of CoCoDet | Apache-2.0 | downloaded from Hugging Face |
| Binoculars | Hans et al. | second detector of AI-written reviews | BSD-3-Clause; its README calls the code "for academic purposes only" | `external/binoculars/`, port in `peercheck/reviews/binoculars.py` |
| Falcon-7B and Falcon-7B-Instruct | Technology Innovation Institute | models of Binoculars | Apache-2.0 | downloaded from Hugging Face |
| Hallucinator | Stringhini and Blackburn | reference check | AGPL-3.0-or-later | downloaded by `peercheck setup references`, never bundled; see `external/hallucinator/PORT.md` |
| pdfguardrail 0.3.0 | GitHub user sugannathan | hidden-text check | MIT | Python dependency |
| PhantomLint phrase list | Toby Murray | phrases of the hidden-text check | BSD-3-Clause | copied into `peercheck/checks/hidden_text.py` |
| HotCRP affiliation word lists | Eddie Kohler | affiliation matching of the conflict check | Click license (BSD style) | copied into `peercheck/conflicts.py` with its notice |
| openreview-py webmail list | OpenReview | email domains of the conflict check | MIT | copied into `peercheck/conflicts.py` |
| PyMuPDF | Artifex | text and layout of PDFs | AGPL-3.0 or commercial | Python dependency |
| datasketch, rapidfuzz, openpyxl, PyYAML, lxml, defusedxml | their authors | near-duplicate search, fuzzy matching, spreadsheets, profiles, XML | MIT, MIT, MIT, MIT, BSD-3-Clause, PSF | Python dependencies |
| DBLP data | Schloss Dagstuhl, University of Trier | conflict check and reference check | CC0 1.0 | downloaded from `dblp.org/xml/` |
| Retraction Watch data | Crossref, Retraction Watch | retracted references | no license stated in its README | downloaded from `gitlab.com/crossref/retraction-watch-data` |
| CrackedPDFs sample | Thienpreecha and Subramanian | test fixtures of the hidden-text check | MIT | `tests/fixtures/hidden/crackedpdfs/` |
