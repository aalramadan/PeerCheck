<h1 align="center">PeerCheck</h1>

<p align="center">PeerCheck automatically checks submissions, reviews, and conflicts of interest for software engineering conferences.</p>

<p align="center">
  <a href="https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-3.10%2B-3776AB">
  <a href="LICENSE"><img alt="License GPL-3.0" src="https://img.shields.io/badge/license-GPL--3.0-blue"></a>
  <img alt="Runs locally" src="https://img.shields.io/badge/runs-locally-2ea44f">
</p>

It reports format violations, anonymity leaks, hidden text, unverifiable references, potentially AI-generated
reviews, and conflicts of interest.

## Checks

Each check has a plain name and, in parentheses, the name that selects it on the command line.

### Submissions, with `peercheck papers`

- **Format** (`layout`) checks the page size, columns, margins, fonts, page limits, page numbers, and missing
  sections. It uses the format checker of HotCRP, a conference management system.
- **Anonymity and template** (`sigsoft`) verifies that the paper uses the template of the venue and identifies
  anonymity leaks, such as author names, email addresses, affiliations, and revealing links. It uses the
  submission checker of ACM SIGSOFT, the software engineering group of the ACM, revised.
- **Hidden text** (`hidden-text`) finds white, invisible, or tiny text, invisible Unicode characters, and prompts
  or instructions hidden in the PDF and intended for AI systems. It uses the PDF libraries pdfguardrail and
  PyMuPDF and the warning phrases of PhantomLint, a scanner for hidden prompts.
- **References** (`references`) finds references that cannot be verified in bibliographic databases and
  references that were retracted. Hallucinator, a reference checker, looks each reference up in an offline copy
  of DBLP, the open bibliography of computer science. The Retraction Watch list marks retracted papers.

### Reviews, with `peercheck reviews`

- **AI detection** (`cocodet`, `editlens`) labels each review as human-written or AI-generated. A review is
  flagged only when the two detectors label it as AI-generated. This mirrors the policy used by ICLR 2026. The
  two detectors are CoCoDet, trained on peer reviews, with the labels Human, Mix, and AI, and EditLens, trained on
  AI-edited text, with the labels Human, AI-Edited, and AI.
- **Planted citation** (`--canaries`) finds reviews that an AI tool wrote from the paper. Before the review period,
  `peercheck canary` writes a copy of each PDF with an instruction hidden in white text. The instruction asks any
  AI tool to cite a made-up work, such as Smith et al. (2019). A review that cites the made-up work of its paper is
  a hit. The check follows the method of Rao et al. that ICML 2026 used.
- **Copied text** (`duplicates`) identifies highly similar paragraphs across reviews. Two paragraphs count as
  copies when at least half of their short character sequences match. It uses MinHash, a fast search for similar
  text, from the datasketch library.
- **Citation requests** (`citations`) identifies works that reviewers recommend citing, including their own
  publications. It matches the requested works against the publications of the reviewers in DBLP.

### Conflicts of interest, with `peercheck conflicts`

PeerCheck finds co-authorship in DBLP within the previous three years, consistent with the ACM SIGSOFT Policy on
Program Committees. It also finds shared email domains, affiliations that match, and declared conflicts without
supporting evidence. Affiliations match through the word lists of HotCRP. Webmail domains such as gmail.com do not count as
shared. OpenReview, a review platform, provides the list of webmail domains.

Each finding is classified as an error, warning, or informational note. An error breaks a stated rule of the
venue. A warning marks a likely problem. An informational note gives context. PeerCheck assists human reviewers;
every flagged paper or review should be checked by a person.

## Example reports

![HTML report of peercheck papers on six example papers](docs/papers-report.png)

![HTML report of peercheck reviews on eight example reviews](docs/reviews-report.png)

## Requirements

- Python 3.10 or newer
- Perl and poppler, for the format check
- Java 11 or newer, for the anonymity and template check

```bash
sudo apt install perl poppler-utils default-jre   # Debian or Ubuntu
brew install poppler openjdk                      # macOS, which already has Perl
```

## Install

```bash
git clone https://github.com/aalramadan/PeerCheck.git
cd PeerCheck
python -m pip install -e ".[reviews]"   # installs all checks, including the libraries of the review checks
peercheck doctor                        # lists missing programs
```

To check only submissions and conflicts, `python -m pip install -e .` installs PeerCheck without the review checks.

Some checks need data or models, which these commands download once.

```bash
peercheck setup references   # Hallucinator, the DBLP database, and the Retraction Watch list
peercheck setup cocodet      # the CoCoDet model, about 600 MB
peercheck setup editlens     # the EditLens model, about 1.4 GB, after the steps below
```

### EditLens access

The authors of EditLens distribute the model only to users who accept its license. The license allows
non-commercial use only.

1. Create a free account at huggingface.co.
2. Accept the license at huggingface.co/pangram/editlens_roberta-large.
3. Create a token with read access at huggingface.co/settings/tokens. Then run `hf auth login` or set the
   variable `HF_TOKEN` to the token.
4. Run `peercheck setup editlens`.

To skip EditLens, check the reviews with `--detectors cocodet`.

## Usage

```bash
peercheck papers submissions/ --authors authors.csv --html report.html   # checks the submission PDFs
peercheck reviews reviews/ --html reviews.html                           # checks the reviews
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz
peercheck canary submissions/ --out marked/ --key canaries.csv           # plants a citation in each PDF
peercheck reviews reviews/ --canaries canaries.csv                       # finds the planted citations
peercheck --profile fse-2027 papers submissions/                         # uses the rules of FSE 2027
python run.py                                                            # opens an interactive menu
```

Each command writes an Excel workbook. A paper or a review needs a closer look when any of its findings is an
error or a warning.

The commands read these inputs.

- PDFs named with their paper ID, as the conference systems EasyChair and HotCRP name them, such as
  `conf2027-paper12.pdf`.
- An author list, a CSV or Excel file with the columns paper, first, last, email, and affiliation.
- The review XML files that EasyChair exports.
- A committee list with first, last, email, and affiliation, or the EasyChair file `reviewer.csv`.

## Options

| Option | Commands | What it does |
|---|---|---|
| `--profile` | all, before the command | picks the venue profile, the rules of one venue, `icse-2027` by default |
| `--out` | all | names the Excel workbook, or the folder of marked PDFs for `peercheck canary` |
| `--json`, `--html` | papers, reviews | also write a JSON file or a page for the browser |
| `--authors` | papers, conflicts | reads the author list |
| `--submissions` | papers | reads the submission sheet of EasyChair or HotCRP |
| `--checks` | papers, reviews | runs only the checks it names, such as `--checks layout,references` |
| `--detectors` | reviews | picks the AI detectors, `cocodet,editlens` by default |
| `--canaries` | reviews | runs the planted-citation check with the key file of `peercheck canary` |
| `--device` | reviews | runs the detectors on the processor (`cpu`) or an NVIDIA graphics card (`cuda`) |
| `--pc`, `--reviewer-csv` | conflicts | read the committee list |
| `--dblp-dump` | conflicts | builds the co-author index from `dblp.xml.gz`, the full download of DBLP |
| `--years` | conflicts | sets the co-authorship window, 3 years by default |
| `--key` | canary | names the private file that records the planted citation of each paper |

`peercheck setup <name>` downloads `references`, `cocodet`, or `editlens`. `peercheck doctor` lists missing
programs. Run any command with `--help` for every option.

## Venue profiles

PeerCheck is tuned for software engineering venues and ships with these profiles.

| Profile | Venue | Format | Pages |
|---|---|---|---|
| icse-2027 (default) | ICSE 2027 Research Track | IEEE, two columns, US Letter | 10 plus 2 of references |
| fse-2027 | FSE 2027 Research Track | ACM acmsmall, one column | 18 plus 4 of references |

However, you can check the papers of any other venue. Copy a file of `src/profiles/`, change its values, and pass
the copy by path, such as `peercheck --profile myvenue.yaml papers submissions/`.

## Tests

```bash
python -m pip install -e ".[dev,reviews]"
python -m pytest                                     # offline; GitHub Actions runs it on each push
mvn -f external/submission-checker/pom.xml package   # rebuilds the revised SIGSOFT jar
```

## Privacy

- Every check and every model runs locally.
- The reference check stays offline by default. The profile option `online: true` sends DOIs and arXiv
  identifiers to doi.org and arxiv.org. The option `online_titles: true` also sends reference titles.
- `.gitignore` keeps PDFs, review XML files, spreadsheets, and CSV files out of git, test fixtures excepted.

## License

PeerCheck is licensed under the GNU General Public License version 3. `NOTICE.md` lists the tools of other authors
with their licenses.

## References

1. CoCoDet: Chen et al. 2026. *CoCoNUTS: Concentrating on Content while Neglecting Uninformative Textual Styles
   for AI-Generated Peer Review Detection.* ACL 2026.
   [doi.org/10.18653/v1/2026.acl-long.1240](https://doi.org/10.18653/v1/2026.acl-long.1240)
2. EditLens: Thai et al. 2026. *EditLens: Quantifying the Extent of AI Editing in Text.* ICLR 2026.
   [arxiv.org/abs/2510.03154](https://arxiv.org/abs/2510.03154)
3. Two detectors that agree: ICLR. 2026. *A Retrospective on the ICLR 2026 Review Process.* ICLR Blog.
   [blog.iclr.cc](https://blog.iclr.cc/2026/03/31/a-retrospective-on-the-iclr-2026-review-process/)
4. Canary check: Rao et al. 2025. *Detecting LLM-generated peer reviews.* PLOS ONE.
   [doi.org/10.1371/journal.pone.0331871](https://doi.org/10.1371/journal.pone.0331871)
5. Canary check: ICML. 2026. *On Violations of LLM Review Policies.* ICML Blog.
   [blog.icml.cc](https://blog.icml.cc/2026/03/18/on-violations-of-llm-review-policies/)
6. Hidden-text phrases: Murray. 2025. *PhantomLint: Principled Detection of Hidden LLM Prompts in Structured
   Documents.* arXiv preprint. [arxiv.org/abs/2508.17884](https://arxiv.org/abs/2508.17884)
7. Duplicates check: Day. 2022. *Exploratory analysis of text duplication in peer-review reveals peer-review fraud
   and paper mills.* Scientometrics 127(10), 5965–5987.
   [doi.org/10.1007/s11192-022-04504-5](https://doi.org/10.1007/s11192-022-04504-5)
8. Limit on citation requests: Wren et al. 2019. *Reviewer-coerced citation: case report, update on journal policy
   and suggestions for future prevention.* Bioinformatics 35(18), 3217–3218.
   [doi.org/10.1093/bioinformatics/btz071](https://doi.org/10.1093/bioinformatics/btz071)
9. Citations of works of the reviewers: Barnett. 2025. *Are peer reviewers influenced by their work being cited?*
   eLife 14. [doi.org/10.7554/eLife.108748](https://doi.org/10.7554/eLife.108748)
