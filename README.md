# PeerCheck

PeerCheck checks the submissions and peer reviews of software engineering conferences. It reports format
violations, anonymity leaks, hidden text, unverifiable references, machine-written reviews, and conflicts of
interest. Its venue profiles follow the rules of ICSE and FSE. Its anonymity and conflict checks follow the
policies of ACM SIGSOFT. Every check runs locally.

![HTML report of peercheck papers on six example papers](docs/papers-report.png)

![HTML report of peercheck reviews on eight example reviews](docs/reviews-report.png)

The example papers are made up. The example reviews come from the public CoCoNUTS test set (MIT license),
which holds peer reviews of ICLR and NeurIPS with labels for human and machine-written text.

## Install

```bash
git clone https://github.com/aalramadan/PeerCheck.git
cd PeerCheck
python -m pip install -e .                # submission and conflict checks
python -m pip install -e ".[reviews]"     # review checks
peercheck doctor                          # lists missing programs
peercheck setup references                # Hallucinator, the DBLP database, and the Retraction Watch list
peercheck setup cocodet                   # CoCoDet weights, about 600 MB
peercheck setup binoculars                # Falcon-7B and Falcon-7B-Instruct, about 29 GB
peercheck setup editlens                  # EditLens (Open Pangram) weights, about 1.4 GB, optional
```

The EditLens weights are gated. Before `peercheck setup editlens`, accept their terms at
`huggingface.co/pangram/editlens_roberta-large` and run `hf auth login`. The terms allow non-commercial use only.

PeerCheck requires Python 3.10 or newer, Perl, poppler, and Java 11 or newer. On Debian or Ubuntu,
`sudo apt install perl poppler-utils default-jre` installs the three programs. On macOS,
`brew install poppler openjdk` installs the two that macOS lacks.

## Run

```bash
peercheck papers submissions/ --submissions submissions.xlsx --authors authors.csv --out report.xlsx
peercheck reviews reviews/ --out reviews.xlsx
peercheck canary submissions/ --out marked/ --key canaries.csv
peercheck reviews reviews/ --canaries canaries.csv --detectors cocodet,binoculars,editlens --out reviews.xlsx
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz --out conflicts.xlsx
peercheck --profile fse-2027 papers pdfs/
python run.py                             # interactive menu
```

Each command writes an Excel workbook. A paper or a review needs review when any of its findings is an error
or a warning. The option `--json` also writes the results as JSON for further analysis. The option `--html`
writes a page for viewing in a browser, with a light and a dark theme.

## Checks

### Submissions

| Check | Tool | Reports |
|---|---|---|
| layout | banal (HotCRP) | paper size, columns, margins, fonts, main pages, reference-only pages, page numbers, and missing sections |
| sigsoft | ACM SIGSOFT submission checker, revised | template, author names, emails, and affiliations in the text, metadata, or links, links that identify the authors, acknowledgments, and first-person self-citations |
| hidden-text | pdfguardrail and PyMuPDF | white, invisible, transparent, covered, clipped, tiny, or off-page text, invisible Unicode characters, and text in metadata, annotations, or form fields |
| references | Hallucinator and Retraction Watch | references missing from the local databases, references with other authors, and retracted references |

The main text may hold at most 10 pages, figures and appendices included, followed by up to 2 pages of
references only. The page where the references begin counts as main text.

### Reviews

| Check | Tool | Reports |
|---|---|---|
| detectors | CoCoDet, Binoculars, and EditLens (Open Pangram) on request | the CoCoDet label (Human, Mix, or AI), the Binoculars score, and the EditLens label (Human, AI-Edited, or AI) with its score |
| canary | made-up citations of Rao et al. | reviews that contain the made-up citation hidden in their paper |
| duplicates | datasketch | paragraphs that appear in two reviews, with a Jaccard similarity above 0.5 |
| citations | DBLP | works that a review asks the authors to cite, and requests for works of the reviewers |

A review counts as machine-written only when two detectors agree, the rule that ICLR 2026 applied. EditLens
runs only with `--detectors cocodet,binoculars,editlens`. Detector results serve as leads for a manual check.

The canary check follows Rao et al. and the canaries of ICML 2026. `peercheck canary` writes a copy of each
submission PDF with a hidden instruction in white text at the foot of its last page. The instruction asks any LLM
that reads the PDF to open its review with a made-up citation, such as Smith et al. (2019), drawn for each paper
from 109,989 such citations. The key file holds the citation of each paper and stays private. Run
`peercheck papers` on the original PDFs first, since the hidden-text check reports the instruction. The marked
copies then replace the PDFs that reviewers download. `peercheck reviews --canaries` reports each review that
contains the citation of its paper. The test keeps the chance of any wrong hit among all reviews at most 0.001,
the profile option `fwer` of the canary check. A person checks each hit, since a review may only report the
hidden instruction. Announce the canary to reviewers before the review period, since a reviewer who finds the
hidden text may take it for misconduct by the authors.

### Conflicts of interest

The conflict check reports co-authorship in DBLP within the past three years, the window of the ACM SIGSOFT
Policy on Program Committees. It also reports email domains outside webmail that an author and a committee
member hold in common, affiliations that match, and declared conflicts that no data supports.

### Severity

Each finding is an error, a warning, or an info. An error breaks a stated rule of the venue. A warning marks
a likely problem. An info gives context.

## Inputs

- PDFs. The file pattern of the profile maps each file to a paper ID, such as `CONF_2027_paper_12.pdf`
  from EasyChair or `conf2027-paper12.pdf` from HotCRP.
- Submission sheet, optional. The EasyChair Excel export or a CSV file with the ID column of the profile.
- Author list. A CSV or Excel file with the columns paper, first, last, email, and affiliation.
- Reviews. The XML files that EasyChair exports. Confidential remarks for the program committee are left out
  of the detector input.
- Committee. A CSV or Excel file with first, last, email, affiliation, and an optional DBLP person ID, or the
  EasyChair files `reviewer.csv` and `assignment.csv`.

## Venue profiles

| Profile | Venue | Format | Pages |
|---|---|---|---|
| icse-2027 (default) | ICSE 2027 Research Track | IEEE, two columns, US Letter | 10 plus 2 of references |
| fse-2027 | FSE 2027 Research Track | ACM acmsmall, one column | 18 plus 4 of references |

A new venue needs a copy of a file in `src/peercheck/profiles/` with its own values, passed by path, such as
`peercheck --profile myvenue.yaml papers pdfs/`.

## Privacy

- Every check and every model runs locally.
- The reference check stays offline by default. The profile option `online: true` sends DOIs and arXiv
  identifiers to doi.org and arxiv.org. The option `online_titles: true` also sends reference titles.
- `.gitignore` keeps PDFs, review XML files, spreadsheets, and CSV files out of git, test fixtures excepted.

## How it works

`peercheck papers`
1. `src/peercheck/inputs.py`, static. Maps each PDF to a paper ID and reads the submission sheet and the author list.
2. `src/peercheck/checks/sigsoft.py`, static. Runs the revised SIGSOFT jar over all PDFs.
3. `src/peercheck/checks/layout.py`, static. Runs banal and checks the format rules of the profile.
4. `src/peercheck/checks/hidden_text.py`, static. Runs pdfguardrail and a clip test with PyMuPDF.
5. `src/peercheck/checks/references.py` and `src/peercheck/retraction_watch.py`, static. Run Hallucinator offline and match DOIs against Retraction Watch.
6. `src/peercheck/report.py`, static. Writes the workbook and the optional JSON file.

`peercheck reviews`
1. `src/peercheck/inputs.py`, static. Reads the review XML files.
2. `src/peercheck/reviews/cocodet.py`, call of a local model. Labels each review with CoCoDet.
3. `src/peercheck/reviews/binoculars.py`, call of two local models. Scores each review with Binoculars.
4. `src/peercheck/reviews/editlens.py`, call of a local model, on request. Labels each review with EditLens.
5. `src/peercheck/canary.py`, static, with `--canaries`. Finds the hidden citation of each paper in its reviews.
6. `src/peercheck/reviews/duplicates.py`, static. Finds paragraphs that appear in two reviews.
7. `src/peercheck/reviews/citations.py`, static. Finds citation requests.
8. `src/peercheck/report.py`, static. Writes the workbook.

`peercheck canary`
1. `src/peercheck/inputs.py`, static. Maps each PDF to a paper ID.
2. `src/peercheck/canary.py`, static. Draws a citation for each paper, writes the key file, and marks a copy of
   each PDF.

`peercheck conflicts`
1. `src/peercheck/dblp.py`, static. Builds a publication index of the authors and the committee from the DBLP dump.
2. `src/peercheck/conflicts.py`, static. Applies the conflict rules.
3. `src/peercheck/report.py`, static. Writes the workbook.

`src/peercheck/cli.py` and `src/peercheck/reviews/cli.py` hold the command line and the menu. `src/peercheck/vendor/`
holds banal and the revised SIGSOFT jar. `external/` holds the original tools, with a `PORT.md` for each
change.

## Tests

```bash
python -m pip install -e ".[dev,reviews]"
python -m pytest
mvn -f external/submission-checker/pom.xml package
```

The tests run offline.

## License

GNU General Public License version 3. `NOTICE.md` lists the bundled and downloaded tools with their licenses.
