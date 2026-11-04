<h1 align="center">PeerCheck</h1>

<p align="center">PeerCheck checks the submissions and peer reviews of software engineering conferences on your own machine.</p>

<p align="center">
  <a href="https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-3.10%2B-3776AB">
  <a href="LICENSE"><img alt="License GPL-3.0" src="https://img.shields.io/badge/license-GPL--3.0-blue"></a>
  <img alt="Runs locally" src="https://img.shields.io/badge/runs-locally-2ea44f">
</p>

It reports format violations, anonymity leaks, hidden text, unverifiable references, machine-written reviews,
and conflicts of interest.

## What it checks

### Submissions, with `peercheck papers`

- **layout** (banal, from HotCRP) checks the page size, columns, margins, fonts, page limits, page numbers, and
  missing sections.
- **sigsoft** (the ACM SIGSOFT submission checker, revised) checks the template and finds anonymity leaks, such as
  author names, emails, affiliations, and links that reveal the authors.
- **hidden-text** (pdfguardrail and PyMuPDF, with the phrases of PhantomLint) finds white, invisible, or tiny text,
  invisible Unicode characters, and hidden prompts aimed at AI reviewers.
- **references** (Hallucinator with an offline DBLP database and the Retraction Watch list) finds references that no
  database holds and references that were retracted.

### Reviews, with `peercheck reviews`

- **detectors** (CoCoDet and EditLens) are two detectors of AI-written text. CoCoDet labels a review as Human, Mix,
  or AI. EditLens labels it as Human, AI-Edited, or AI. A review is flagged only when the two agree that AI wrote
  the review, as ICLR 2026 required.
- **canary** (the method of Rao et al., as ICML 2026 used it) finds reviews that repeat a made-up citation hidden
  in the PDF of their paper.
- **duplicates** (the MinHash search of datasketch) finds paragraphs copied between reviews, at a Jaccard similarity
  of 0.5 or more.
- **citations** (DBLP) finds works that a review asks the authors to cite, including works of the reviewers.

### Conflicts of interest, with `peercheck conflicts`

- **conflicts** (DBLP, the affiliation word lists of HotCRP, and the webmail list of OpenReview) finds
  co-authorship in the past three years, the window of the ACM SIGSOFT Policy on Program Committees. It also finds
  shared email domains, affiliations that match, and declared conflicts that no data supports.

Each finding is an error, a warning, or an info. An error breaks a stated rule of the venue. A warning marks a
likely problem. An info gives context. A person checks every flagged paper or review.

## Example reports

![HTML report of peercheck papers on six example papers](docs/papers-report.png)

![HTML report of peercheck reviews on eight example reviews](docs/reviews-report.png)

The example papers are made up. The example reviews come from the public CoCoNUTS test set (MIT license), which
holds peer reviews of ICLR and NeurIPS with labels for human and machine-written text. The canary hit in review
example-6 is made up.

## Requirements

- Python 3.10 or newer
- Perl and poppler, for the layout check
- Java 11 or newer, for the sigsoft check

```bash
sudo apt install perl poppler-utils default-jre   # Debian or Ubuntu
brew install poppler openjdk                      # macOS, which already has Perl
```

## Install

```bash
git clone https://github.com/aalramadan/PeerCheck.git
cd PeerCheck
python -m pip install -e ".[reviews]"   # all checks, with PyTorch for the review detectors
peercheck doctor                        # lists missing programs
```

To check only submissions and conflicts, `python -m pip install -e .` installs PeerCheck without PyTorch.

Some checks need data or models, which these commands download once.

```bash
peercheck setup references   # Hallucinator, the DBLP database, and the Retraction Watch list
peercheck setup cocodet      # the CoCoDet model, about 600 MB
peercheck setup editlens     # the EditLens model, about 1.4 GB, after the steps below
```

### EditLens access

Pangram Labs, the authors of EditLens, share its model only with users who accept its license. The license allows
non-commercial use only.

1. Create a free account at huggingface.co.
2. Accept the license at huggingface.co/pangram/editlens_roberta-large.
3. Create a token with read access at huggingface.co/settings/tokens. Then run `hf auth login` or set the
   variable `HF_TOKEN` to the token.
4. Run `peercheck setup editlens`.

To skip EditLens, check the reviews with `--detectors cocodet`.

## Usage

```bash
peercheck papers submissions/ --authors authors.csv --html report.html
peercheck reviews reviews/ --html reviews.html
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz
peercheck --profile fse-2027 papers submissions/
python run.py                           # interactive menu
```

Each command writes an Excel workbook. A paper or a review needs a closer look when any of its findings is an
error or a warning.

## Options

Every command takes `--profile` before its name, such as `peercheck --profile fse-2027 papers submissions/`.
The default profile is `icse-2027`.

### `peercheck papers <folder>`

| Option | What it does |
|---|---|
| `--submissions` | reads the submission sheet, an EasyChair Excel file or a HotCRP CSV file |
| `--authors` | reads the author list with the columns paper, first, last, email, and affiliation |
| `--checks` | runs only the named checks, such as `layout,sigsoft` |
| `--out` | names the Excel workbook, `report.xlsx` by default |
| `--json` | also writes the results as JSON |
| `--html` | also writes a page for the browser, with a light and a dark theme |

### `peercheck reviews <folder>`

| Option | What it does |
|---|---|
| `--detectors` | picks the detectors, `cocodet,editlens` by default |
| `--checks` | picks the other checks, `duplicates,citations` by default |
| `--canaries` | reads the key file of `peercheck canary` and runs the canary check |
| `--device` | runs the models on `cpu` or `cuda` |
| `--dblp-index` | matches requested citations against works of the reviewers |
| `--reviewer-csv`, `--assignment-csv` | read the EasyChair files of the reviewers and their assignments |
| `--out`, `--json`, `--html` | work as for `papers`, with `reviews.xlsx` by default |

### `peercheck conflicts`

| Option | What it does |
|---|---|
| `--authors` | reads the author list |
| `--pc` | reads the committee list with first, last, email, affiliation, and an optional DBLP person ID |
| `--reviewer-csv` | reads the EasyChair file `reviewer.csv` in place of `--pc` |
| `--assignment-csv` | reads the EasyChair file `assignment.csv`, together with `--reviewer-csv` |
| `--conflict-csv` | reads the EasyChair conflict export, together with `--reviewer-csv` |
| `--dblp-dump` | builds the co-author index from `dblp.xml.gz` |
| `--dblp-index`, `--save-index` | load or save that index |
| `--years` | sets the co-authorship window, 3 years by default |
| `--out` | names the Excel workbook, `conflicts.xlsx` by default |

### `peercheck canary <folder>`

| Option | What it does |
|---|---|
| `--out` | names the folder for the marked PDFs |
| `--key` | names the CSV file of the hidden citations, which stays private |

### Other commands

| Command | What it does |
|---|---|
| `peercheck setup <name>` | downloads `references`, `cocodet`, or `editlens` |
| `peercheck doctor` | lists missing programs and files |
| `peercheck profiles` | lists the venue profiles |
| `peercheck menu` | opens the interactive menu, as `python run.py` does |

## Canary check

The canary check follows Rao et al. and the canaries of ICML 2026.

1. Check the original PDFs with `peercheck papers` first, since the hidden-text check reports the canary.
2. Run `peercheck canary submissions/ --out marked/ --key canaries.csv`. Each copy in `marked/` holds a hidden
   instruction in white text that asks any large language model to open its review with a made-up citation, such
   as Smith et al. (2019). Each paper gets one of 109,989 such citations.
3. Upload the marked copies in place of the originals and keep `canaries.csv` private. Tell the reviewers that the
   PDFs hold a canary, since a reviewer who finds the hidden text may take it for misconduct by the authors.
4. Run `peercheck reviews reviews/ --canaries canaries.csv`. A review that contains the citation of its paper is a
   hit. The chance of any wrong hit among all reviews stays at most 0.001, the profile option `fwer`. A person
   checks each hit, since a review may only report the hidden instruction.

## Inputs

- PDFs. The file pattern of the profile maps each file to a paper ID, such as `CONF_2027_paper_12.pdf` from
  EasyChair or `conf2027-paper12.pdf` from HotCRP.
- Submission sheet, optional. The EasyChair Excel export or a CSV file with the ID column of the profile.
- Author list. A CSV or Excel file with the columns paper, first, last, email, and affiliation.
- Reviews. The XML files that EasyChair exports. Confidential remarks for the program committee stay out of the
  detector input.
- Committee. A CSV or Excel file with first, last, email, affiliation, and an optional DBLP person ID, or the
  EasyChair files `reviewer.csv` and `assignment.csv`.

## Venue profiles

| Profile | Venue | Format | Pages |
|---|---|---|---|
| icse-2027 (default) | ICSE 2027 Research Track | IEEE, two columns, US Letter | 10 plus 2 of references |
| fse-2027 | FSE 2027 Research Track | ACM acmsmall, one column | 18 plus 4 of references |

A new venue needs a copy of a file in `src/profiles/` with its own values, passed by path, such as
`peercheck --profile myvenue.yaml papers submissions/`.

## Privacy

- Every check and every model runs locally.
- The reference check stays offline by default. The profile option `online: true` sends DOIs and arXiv
  identifiers to doi.org and arxiv.org. The option `online_titles: true` also sends reference titles.
- `.gitignore` keeps PDFs, review XML files, spreadsheets, and CSV files out of git, test fixtures excepted.

## How it works

| Folder | Holds |
|---|---|
| `src/` | PeerCheck itself |
| `external/` | the tools and data of other authors, as `external/README.md` lists |
| `tests/` | the tests and their sample files |
| `docs/` | the pictures of this README |

`peercheck papers`
1. `src/inputs.py`, static. Maps each PDF to a paper ID and reads the submission sheet and the author list.
2. `src/checks/sigsoft.py`, static. Runs the revised SIGSOFT jar over all PDFs.
3. `src/checks/layout.py`, static. Runs banal and checks the format rules of the profile.
4. `src/checks/hidden_text.py`, static. Runs pdfguardrail and a clip test with PyMuPDF.
5. `src/checks/references.py` and `src/retraction_watch.py`, static. Run Hallucinator offline and match DOIs
   against Retraction Watch.
6. `src/report.py`, static. Writes the workbook and the optional JSON and HTML files.

`peercheck reviews`
1. `src/inputs.py`, static. Reads the review XML files.
2. `src/reviews/cocodet.py`, call of a local model. Labels each review with CoCoDet.
3. `src/reviews/editlens.py`, call of a local model. Labels each review with EditLens.
4. `src/canary.py`, static, with `--canaries`. Finds the hidden citation of each paper in its reviews.
5. `src/reviews/duplicates.py`, static. Finds paragraphs that appear in two reviews.
6. `src/reviews/citations.py`, static. Finds citation requests.
7. `src/report.py`, static. Writes the workbook and the optional JSON and HTML files.

`peercheck canary`
1. `src/inputs.py`, static. Maps each PDF to a paper ID.
2. `src/canary.py`, static. Draws a citation for each paper, writes the key file, and marks a copy of each PDF.

`peercheck conflicts`
1. `src/dblp.py`, static. Builds a publication index of the authors and the committee from the DBLP dump.
2. `src/conflicts.py`, static. Applies the conflict rules.
3. `src/report.py`, static. Writes the workbook.

`src/cli.py` and `src/reviews/cli.py` hold the command line and the menu.

## Tests

```bash
python -m pip install -e ".[dev,reviews]"
python -m pytest                                     # offline; GitHub Actions runs it on each push
mvn -f external/submission-checker/pom.xml package   # rebuilds the revised SIGSOFT jar
```

## License

PeerCheck is licensed under the GNU General Public License version 3. `NOTICE.md` lists the tools of other authors
with their licenses.
