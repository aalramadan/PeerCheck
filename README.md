# PeerCheck

PeerCheck checks conference submissions and peer reviews. It reports format violations, anonymity leaks,
hidden text, unverifiable references, machine-written reviews, and conflicts of interest. Every check runs
locally.

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
```

PeerCheck requires Python 3.10 or newer, Perl, poppler, and Java 11 or newer. On Debian or Ubuntu,
`sudo apt install perl poppler-utils default-jre` installs the three programs. On macOS,
`brew install poppler openjdk` installs the two that macOS lacks.

## Run

```bash
peercheck papers submissions/ --submissions submissions.xlsx --authors authors.csv --out report.xlsx
peercheck reviews reviews/ --out reviews.xlsx
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz --out conflicts.xlsx
peercheck --profile icse-2027 papers pdfs/
python run.py                             # interactive menu
```

Each command writes an Excel workbook. A paper or a review needs review when any of its findings is an error
or a warning. The option `--json` also writes the results as JSON for further analysis. The option `--html`
writes a page for viewing in a browser.

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
| detectors | CoCoDet and Binoculars | the CoCoDet label (Human, Mix, or AI) and the Binoculars score |
| duplicates | datasketch | paragraphs that appear in two reviews, with a Jaccard similarity above 0.5 |
| citations | DBLP | works that a review asks the authors to cite, and requests for works of the reviewers |

A review counts as machine-written only when CoCoDet and Binoculars agree, the rule that ICLR 2026 applied.
Detector results serve as leads for a manual check.

### Conflicts of interest

The conflict check reports co-authorship in DBLP within the past three years, the window of the ACM SIGSOFT
Policy on Program Committees. It also reports email domains outside webmail that an author and a committee
member hold in common, affiliations that match, and declared conflicts that no data supports.

### Severity

Each finding is an error, a warning, or an info. An error breaks a stated rule of the venue. A warning marks
a likely problem. An info gives context.

## Inputs

- PDFs. The file pattern of the profile maps each file to a paper ID, such as `CONF_2026_paper_108.pdf`
  from EasyChair or `icse2027-paper108.pdf` from HotCRP.
- Submission sheet, optional. The EasyChair Excel export or a CSV file with the ID column of the profile.
- Author list. A CSV or Excel file with the columns paper, first, last, email, and affiliation.
- Reviews. The XML files that EasyChair exports. Confidential remarks for the program committee are left out
  of the detector input.
- Committee. A CSV or Excel file with first, last, email, affiliation, and an optional DBLP person ID, or the
  EasyChair files `reviewer.csv` and `assignment.csv`.

## Venue profiles

| Profile | Venue | Format | Pages |
|---|---|---|---|
| conf-2026 (default) | CONF 2026 Research Track | IEEE, two columns, US Letter | 10 plus 2 of references |
| icse-2027 | ICSE 2027 Research Track | IEEE, two columns, US Letter | 10 plus 2 of references |
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
4. `src/peercheck/reviews/duplicates.py`, static. Finds paragraphs that appear in two reviews.
5. `src/peercheck/reviews/citations.py`, static. Finds citation requests.
6. `src/peercheck/report.py`, static. Writes the workbook.

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
