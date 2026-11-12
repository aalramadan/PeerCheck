# External tools and data

- Each folder holds a copy of a tool or a data set from another project. The table gives the origin, version,
  and license of each copy and what PeerCheck does with the copy.
- PeerCheck's own code lives in `src/` at the root of the repository. Where PeerCheck runs its own version of a
  tool, the table names that file, such as `src/reviews/cocodet.py`.
- The four folders with a `PORT.md` are `coconuts/`, `editlens/`, `hallucinator/`, and `submission-checker/`. The
  `PORT.md` says what PeerCheck changed or how it uses the tool.
- `NOTICE.md` at the root of the repository lists every license.

| Folder | Origin | Version | License | What PeerCheck does with it |
|---|---|---|---|---|
| `aclpubcheck/` | github.com/acl-org/aclpubcheck | commit `fb584f3` | MIT | keeps `formatchecker.py`, the format checker of ACL venues, whose list of Times fonts `src/papers/fonts.py` takes and whose scan of the margins `src/papers/margins.py` follows, and `metadatachecker.py`, whose comparison of the PDF title with the submission sheet `src/papers/title_match.py` follows |
| `census-surnames/` | U.S. Census Bureau, Frequently Occurring Surnames from the 2010 Census | 2010 census | public domain | reads the 9,999 most common surnames for the made-up citations of the canary check |
| `coconuts/` | github.com/icip-cas/CoCoNUTS | commit `25df608` | MIT, per the CoCoDet model card | keeps `infer.py`, the original of CoCoDet, and runs its own version in `src/reviews/cocodet.py` |
| `editlens/` | github.com/pangramlabs/EditLens | commit `05a588f` | CC BY-NC-SA 4.0 | keeps the code of Open Pangram, the release of EditLens, without its data and runs its own version in `src/reviews/editlens.py` |
| `hallucinator/` | github.com/gianlucasb/hallucinator | release v0.2.4 | AGPL-3.0-or-later | keeps the Rust source of the reference checker, whose built program `peercheck --setup` downloads |
| `hotcrp/` | github.com/kohler/hotcrp | commit `4c1ef77` | GPL-2.0-or-later for `banal`, Click license for the rest | runs `banal` in the format check and reads the affiliation word lists of `affiliationmatchers.json` in the conflict check |
| `mubanal/` | github.com/kohler/mubanal | commit `f185559` | AGPL-3.0 | keeps `src/extract.cc` and `src/mubanal.hh` of the PDF analyzer that HotCRP reads, whose nine categories of active content `src/papers/active_content.py` follows with a scan of its own in pikepdf |
| `openreview-py/` | github.com/openreview/openreview-py | commit `9e8ba8e` | MIT | copies the webmail list of `openreview/tools.py` into `src/conflicts.py` |
| `phantomlint/` | github.com/tobycmurray/phantom-lint | commit `7f62001` | BSD-3-Clause | copies the warning phrases of PhantomLint into `src/papers/hidden_text.py` |
| `publicsuffix/` | publicsuffix.org, the Public Suffix List | version `2026-11-06_09-01-47_UTC`, commit `94ec5df` | MPL-2.0 | reads the public suffixes, such as `ac.uk` and `re.kr`, to find the domain of the organization behind each email address in the conflict check |
| `snowball/` | github.com/snowballstem/snowball-website, the English stop word list of Snowball | commit `dc14fb4` | BSD-3-Clause | reads the 174 English stop words of `stop.txt` as the common words of the text check in `src/papers/unreadable_text.py` |
| `submission-checker/` | github.com/acmsigsoft/submission-checker | release v0.4.3, commit `3ffa1eb` | Apache-2.0 | runs the jar, built from the revised source in this folder, in the anonymity and template check; `src/papers/line_numbers.py` follows the line count of `PdfChecker.java`, which finds the line numbers of the review version of acmart |
| `verapdf/` | github.com/veraPDF/veraPDF-validation-profiles | commit `fc5a92f` | CC BY 4.0 | keeps `PDFUA-1.xml`, the PDF/UA-1 profile of veraPDF, whose rules 6.2-1, 7.1-9, 7.1-11, 7.2-29, and 7.3-1 the accessibility check in `src/papers/accessibility.py` follows |

## Checks

| Command | Check (template key) | Finds | Built on |
|---|---|---|---|
| `papers` | Format (`layout`) | page size, columns, margins, font size, line spacing, page limits (without exempt sections such as Data Availability), page numbers, and missing sections; template fonts, title size, and fonts that are not embedded; content that runs into the margins; and papers far denser than the rest of the batch | the format checker of HotCRP, a submission and review system, and checks of PeerCheck with PyMuPDF, with the Times fonts of aclpubcheck, the format checker of ACL |
| `papers` | File and text (`layout`) | locked, damaged, or unreadable files; garbled or scanned text that the other checks cannot read; broken references such as Section ??; a title that differs from the submission sheet; missing line numbers at a venue that asks for them; images too large or too coarse and a file above the size limit of the venue; and notes on accessibility when a profile asks for them | checks of PeerCheck with PyMuPDF and pikepdf, with the title comparison of aclpubcheck, the line count of the SIGSOFT checker, the English stop words of Snowball, and five rules of the PDF/UA-1 profile of veraPDF |
| `papers` | Anonymity and template (`sigsoft`) | author names, email addresses, affiliations, links that reveal the authors, author names and home folders hidden in images, attachments, comments, and earlier saved versions of the PDF, and a template other than that of the venue | a revised copy of the submission checker of ACM SIGSOFT, a special interest group of the ACM, and a scan of the PDF objects by PeerCheck |
| `papers` | Hidden text (`hidden_text`) | white, invisible, or tiny text, invisible Unicode characters, prompts hidden for AI tools, and active content such as scripts and actions that run on opening | the PDF libraries pdfguardrail and PyMuPDF, the phrases of PhantomLint, a scanner for hidden prompts, and the nine categories of mubanal, the PDF analyzer of HotCRP |
| `papers` | References (`references`) | references that no bibliographic database confirms and retracted references | Hallucinator, a reference checker, with an offline copy of DBLP, the open bibliography of computer science, online lookups in CrossRef, arXiv, Semantic Scholar, OpenAlex, and other databases, and the Retraction Watch list |
| `reviews` | AI detection (`cocodet`, `editlens`) | potentially AI-generated reviews, with the label of each detector on its own | CoCoDet, trained on peer reviews, and EditLens, trained on AI-edited text |
| `reviews` | Planted citation (`canary`) | reviews that cite the made-up work hidden in their paper | the method of Rao et al. that ICML 2026 used |
| `reviews` | Copied text (`duplicates`) | paragraphs that reviews share, with at least half of their short character sequences alike | MinHash, a fast search for similar text, from the datasketch library |
| `reviews` | Citation requests (`citations`) | works that reviewers ask the authors to cite, their own included, and requests for more works than the paper has pages | DBLP, for the works of the reviewers, through `--dblp-index` |
| `conflicts` | Conflicts of interest | co-authorship within three years (the window of the ACM SIGSOFT Policy on Program Committees), shared email domains other than webmail, and affiliations that match (two universities of one city stay apart) | DBLP, the affiliation word lists of HotCRP, the webmail list of OpenReview, and the Public Suffix List |

- Before the review period, `peercheck --canary` hides a request to cite a made-up work, such as Smith et al. (2019),
  in white text in a copy of each PDF. A wrong hit among all reviews has a chance of 0.1% or less.

## Not in this folder

- Model weights and databases. `peercheck --setup` downloads DBLP and the Retraction Watch list. The first review run
  downloads CoCoDet with ModernBERT-base and the EditLens weights.
- Python dependencies, such as pdfguardrail and PyMuPDF, which install with pip.
- Code of the canary check, since the paper of Rao et al. (arXiv 2503.15772) that the check follows comes without
  code.

## References

The papers that the checks of PeerCheck build on.

1. CoCoDet: Chen et al. 2026. *CoCoNUTS: Concentrating on Content while Neglecting Uninformative Textual Styles
   for AI-Generated Peer Review Detection.* ACL 2026.
   [doi.org/10.18653/v1/2026.acl-long.1240](https://doi.org/10.18653/v1/2026.acl-long.1240)
2. EditLens: Thai et al. 2026. *EditLens: Quantifying the Extent of AI Editing in Text.* ICLR 2026.
   [arxiv.org/abs/2510.03154](https://arxiv.org/abs/2510.03154)
3. Canary check: Rao et al. 2025. *Detecting LLM-generated peer reviews.* PLOS ONE.
   [doi.org/10.1371/journal.pone.0331871](https://doi.org/10.1371/journal.pone.0331871)
4. Canary check: ICML. 2026. *On Violations of LLM Review Policies.* ICML Blog.
   [blog.icml.cc](https://blog.icml.cc/2026/03/18/on-violations-of-llm-review-policies/)
5. Hidden-text phrases: Murray. 2025. *PhantomLint: Principled Detection of Hidden LLM Prompts in Structured
   Documents.* arXiv preprint. [arxiv.org/abs/2508.17884](https://arxiv.org/abs/2508.17884)
6. Duplicates check: Day. 2022. *Exploratory analysis of text duplication in peer-review reveals peer-review fraud
   and paper mills.* Scientometrics 127(10), 5965–5987.
   [doi.org/10.1007/s11192-022-04504-5](https://doi.org/10.1007/s11192-022-04504-5)
7. Limit on citation requests: Wren et al. 2019. *Reviewer-coerced citation: case report, update on journal policy
   and suggestions for future prevention.* Bioinformatics 35(18), 3217–3218.
   [doi.org/10.1093/bioinformatics/btz071](https://doi.org/10.1093/bioinformatics/btz071)
8. Citations of works of the reviewers: Barnett. 2025. *Are peer reviewers influenced by their work being cited?*
   eLife 14. [doi.org/10.7554/eLife.108748](https://doi.org/10.7554/eLife.108748)
