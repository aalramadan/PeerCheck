<h1 align="center">PeerCheck</h1>

<p align="center">PeerCheck checks the submissions and peer reviews of software engineering conferences on your own machine.</p>

<p align="center">
  <a href="https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-3.10%2B-3776AB">
  <a href="LICENSE"><img alt="License GPL-3.0" src="https://img.shields.io/badge/license-GPL--3.0-blue"></a>
  <img alt="Runs locally" src="https://img.shields.io/badge/runs-locally-2ea44f">
</p>

It reports format violations, anonymity leaks, hidden text, unverifiable references, machine-written reviews,
and conflicts of interest. Its venue profiles follow the rules of ICSE and FSE. Its anonymity and conflict checks
follow the policies of ACM SIGSOFT.

## Install

```bash
git clone https://github.com/aalramadan/PeerCheck.git
cd PeerCheck
python -m pip install -e ".[reviews]"    # without [reviews] for the submission and conflict checks only
peercheck doctor                         # lists missing programs
peercheck setup references               # Hallucinator, the DBLP database, and the Retraction Watch list
peercheck setup cocodet                  # CoCoDet weights, about 600 MB
peercheck setup editlens                 # EditLens weights, about 1.4 GB
```

PeerCheck needs Python 3.10 or newer, Perl, poppler, and Java 11 or newer. On Debian or Ubuntu,
`sudo apt install perl poppler-utils default-jre` installs the three programs. On macOS,
`brew install poppler openjdk` installs the two that macOS lacks.

EditLens is gated. Before `peercheck setup editlens`, accept its terms at
`huggingface.co/pangram/editlens_roberta-large` and run `hf auth login` once. The terms allow non-commercial use
only. Without EditLens, check the reviews with `--detectors cocodet`.

## Run

```bash
peercheck papers submissions/ --authors authors.csv --html report.html
peercheck reviews reviews/ --html reviews.html
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz
peercheck --profile fse-2027 papers submissions/
python run.py                            # interactive menu
```

Each command writes an Excel workbook, named by `--out`. The option `--json` adds a JSON file. The option `--html`
adds a page for the browser with a light and a dark theme. A paper or a review needs a closer look when any of
its findings is an error or a warning.

## Example reports

![HTML report of peercheck papers on six example papers](docs/papers-report.png)

![HTML report of peercheck reviews on eight example reviews](docs/reviews-report.png)

The example papers are made up. The example reviews come from the public CoCoNUTS test set (MIT license), which
holds peer reviews of ICLR and NeurIPS with labels for human and machine-written text.

## Checks

### Submissions

| Check | Tool | Reports |
|---|---|---|
| layout | banal of HotCRP | paper size, columns, margins, fonts, main pages, reference-only pages, page numbers, and missing sections |
| sigsoft | ACM SIGSOFT submission checker, revised | template, author names, emails, and affiliations in the text, metadata, or links, links that identify the authors, acknowledgments, and first-person self-citations |
| hidden-text | pdfguardrail and PyMuPDF | white, invisible, transparent, covered, clipped, tiny, or off-page text, invisible Unicode characters, and text in metadata, annotations, or form fields |
| references | Hallucinator and Retraction Watch | references missing from the local databases, references with other authors, and retracted references |

Under the default profile, the main text may hold at most 10 pages, figures and appendices included, followed by
up to 2 pages of references only. The page where the references begin counts as main text.

### Reviews

| Check | Tool | Reports |
|---|---|---|
| detectors | CoCoDet and EditLens (Open Pangram) | the CoCoDet label (Human, Mix, or AI) and the EditLens label (Human, AI-Edited, or AI) with its score |
| canary | made-up citations of Rao et al. | reviews that contain the made-up citation hidden in their paper |
| duplicates | datasketch | paragraphs that appear in two reviews, with a Jaccard similarity above 0.5 |
| citations | DBLP | works that a review asks the authors to cite, and requests for works of the reviewers |

A review counts as machine-written only when CoCoDet and EditLens agree, since ICLR 2026 required two detectors to
agree. The label of one detector alone appears as a note. Every detector result serves as a lead for a manual
check.

### Canary check

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

### Conflicts of interest

The conflict check reports co-authorship in DBLP within the past three years, the window of the ACM SIGSOFT
Policy on Program Committees. It also reports email domains outside webmail that an author and a committee
member hold in common, affiliations that match, and declared conflicts that no data supports.

### Severity

Each finding is an error, a warning, or an info. An error breaks a stated rule of the venue. A warning marks a
likely problem. An info gives context.

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
