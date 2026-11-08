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
| `aclpubcheck/` | github.com/acl-org/aclpubcheck | commit `fb584f3` | MIT | keeps `formatchecker.py`, the format checker of ACL venues, whose list of Times fonts `src/checks/fonts.py` takes and whose scan of the margins `src/checks/margins.py` follows |
| `census-surnames/` | U.S. Census Bureau, Frequently Occurring Surnames from the 2010 Census | 2010 census | public domain | reads the 9,999 most common surnames for the made-up citations of the canary check |
| `coconuts/` | github.com/icip-cas/CoCoNUTS | commit `25df608` | MIT, per the CoCoDet model card | keeps `infer.py`, the original of CoCoDet, and runs its own version in `src/reviews/cocodet.py` |
| `editlens/` | github.com/pangramlabs/EditLens | commit `05a588f` | CC BY-NC-SA 4.0 | keeps the code of Open Pangram, the release of EditLens, without its data and runs its own version in `src/reviews/editlens.py` |
| `hallucinator/` | github.com/gianlucasb/hallucinator | release v0.2.4 | AGPL-3.0-or-later | keeps the Rust source of the reference checker, whose built program `peercheck setup references` downloads |
| `hotcrp/` | github.com/kohler/hotcrp | commit `4c1ef77` | GPL-2.0-or-later for `banal`, Click license for the rest | runs `banal` in the format check and reads the affiliation word lists of `affiliationmatchers.json` in the conflict check |
| `openreview-py/` | github.com/openreview/openreview-py | commit `9e8ba8e` | MIT | copies the webmail list of `openreview/tools.py` into `src/conflicts.py` |
| `phantomlint/` | github.com/tobycmurray/phantom-lint | commit `7f62001` | BSD-3-Clause | copies the warning phrases of PhantomLint into `src/checks/hidden_text.py` |
| `publicsuffix/` | publicsuffix.org, the Public Suffix List | version `2026-11-06_09-01-47_UTC`, commit `94ec5df` | MPL-2.0 | reads the public suffixes, such as `ac.uk` and `re.kr`, to find the domain of the organization behind each email address in the conflict check |
| `submission-checker/` | github.com/acmsigsoft/submission-checker | release v0.4.3, commit `3ffa1eb` | Apache-2.0 | runs the jar, built from the revised source in this folder, in the anonymity and template check |

## Checks

| Command | Check (command-line name) | Finds | Built on |
|---|---|---|---|
| `papers` | Format (`layout`) | page size, columns, margins, font size, line spacing, page limits (without exempt sections such as Data Availability), page numbers, and missing sections; template fonts, title size, and fonts that are not embedded; content that runs into the margins; locked or damaged files; and broken references such as Section ?? | the format checker of HotCRP, a conference system, and checks of PeerCheck with PyMuPDF and pikepdf, with the Times fonts of aclpubcheck, the format checker of ACL |
| `papers` | Anonymity and template (`sigsoft`) | author names, email addresses, affiliations, links that reveal the authors, author names and home folders hidden in images, attachments, comments, and earlier saved versions of the PDF, and a template other than that of the venue | a revised copy of the submission checker of ACM SIGSOFT, the software engineering group of the ACM, and a scan of the PDF objects by PeerCheck |
| `papers` | Hidden text (`hidden-text`) | white, invisible, or tiny text, invisible Unicode characters, and prompts hidden for AI tools | the PDF libraries pdfguardrail and PyMuPDF and the phrases of PhantomLint, a scanner for hidden prompts |
| `papers` | References (`references`) | references that no bibliographic database confirms and retracted references | Hallucinator, a reference checker, with an offline copy of DBLP, the open bibliography of computer science, and the Retraction Watch list |
| `reviews` | AI detection (`cocodet`, `editlens`) | potentially AI-generated reviews, with the label of each detector on its own | CoCoDet, trained on peer reviews, and EditLens, trained on AI-edited text |
| `reviews` | Planted citation (`--canaries`) | reviews that cite the made-up work hidden in their paper | the method of Rao et al. that ICML 2026 used |
| `reviews` | Copied text (`duplicates`) | paragraphs that reviews share, with at least half of their short character sequences alike | MinHash, a fast search for similar text, from the datasketch library |
| `reviews` | Citation requests (`citations`) | works that reviewers ask the authors to cite, their own included, and requests for more works than the paper has pages | DBLP, for the works of the reviewers, through `--dblp-index` |
| `conflicts` | Conflicts of interest | co-authorship within three years (the window of the ACM SIGSOFT Policy on Program Committees), shared email domains other than webmail, affiliations that match, and declared conflicts without evidence | DBLP, the affiliation word lists of HotCRP, the webmail list of OpenReview, and the Public Suffix List |

- Before the review period, `peercheck canary` hides a request to cite a made-up work, such as Smith et al. (2019),
  in white text in a copy of each PDF. A wrong hit among all reviews has a chance of 0.1% or less.

## Not in this folder

- Model weights and databases, which `peercheck setup` downloads. These are CoCoDet with ModernBERT-base, the
  EditLens weights, DBLP, and the Retraction Watch list.
- Python dependencies, such as pdfguardrail and PyMuPDF, which install with pip.
- Code of the canary check, since the paper of Rao et al. (arXiv 2503.15772) that the check follows comes without
  code.
