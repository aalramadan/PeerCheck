# PeerCheck

PeerCheck screens conference submissions and peer reviews for program chairs on the chair's own machine.
It grew out of the ICSME Submission Checker Suite and builds on tools that conferences already run, such as
banal from HotCRP, the ACM SIGSOFT submission checker from ICSE, and Hallucinator from the chairs of ACSAC
2025 and ICWSM 2026.

## Install

```bash
git clone https://github.com/aalramadan/PeerCheck.git
cd PeerCheck
python -m pip install -e .                # paper checks and conflict check
python -m pip install -e ".[reviews]"     # review checks with CoCoDet and Binoculars
peercheck doctor                          # names each missing program
peercheck setup references                # Hallucinator, its DBLP database, and the Retraction Watch list
peercheck setup cocodet                   # CoCoDet weights, about 600 MB
peercheck setup binoculars                # Falcon-7B and Falcon-7B-Instruct, about 29 GB
```

The paper checks need Python 3.10 or newer, Perl and poppler for banal, and Java 11 or newer for the
SIGSOFT checker. On Debian or Ubuntu, `sudo apt install perl poppler-utils default-jre` installs all three.
On macOS, `brew install poppler openjdk` adds the two programs that macOS lacks.

## Run

```bash
# Check the PDFs of a folder against the ICSME 2026 rules.
peercheck papers submissions/ --submissions submissions.xlsx --authors authors.csv --out report.xlsx

# Check the review XML files that EasyChair exports.
peercheck reviews reviews/ --out reviews.xlsx

# Find conflicts of interest between the authors and the program committee.
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz --out conflicts.xlsx

# Use another venue profile, or open the menu of the original suite.
peercheck --profile icse-2027 papers pdfs/
python run.py
```

Each command writes one Excel workbook. Every paper and every review gets a Needs Review cell, set to yes
when any finding is an error or a warning. The option `--json` of `papers` and `reviews` also writes the
results as JSON.

## Checks

### Submission PDFs

| Check | Built on | Reports |
|---|---|---|
| layout | banal, the format analyzer of HotCRP | paper size, columns, margins, body and reference fonts, main pages and reference-only pages, page numbers, and a missing abstract, introduction, or conclusion |
| sigsoft | the ACM SIGSOFT submission checker, revised for PeerCheck | the template, author names, emails, and affiliations anywhere in the PDF, its metadata, or its links, links to personal pages or code accounts, acknowledgments, and self-citations in the first person |
| hidden-text | pdfguardrail and PyMuPDF | white, invisible, transparent, covered, clipped, tiny, or off-page text, invisible Unicode characters, and text in the metadata, annotations, or form fields, with an error when the hidden text instructs a model or a reviewer |
| references | Hallucinator and the Retraction Watch data of Crossref | references that no local database holds, references with other authors, and citations of retracted work |

The page rule follows the ICSME 2026 call. The main text holds at most 10 pages, figures and appendices
included, and up to 2 further pages may hold references only. The page where the references begin counts
toward the main text.

### Reviews

| Check | Built on | Reports |
|---|---|---|
| detectors | CoCoDet and Binoculars | the CoCoDet label (Human, Mix, or AI) with its probability and the Binoculars score, with a warning only when the two detectors agree that a review reads as machine-written |
| duplicates | datasketch | paragraphs that appear in two reviews with a Jaccard similarity above 0.5 |
| citations | DBLP | DOIs, arXiv identifiers, and references that a review asks the authors to cite, and requests for works of the reviewers of the same paper |

The agreement rule follows ICLR 2026, whose program chairs notified area chairs only of reviews that two
detectors flagged as entirely written by a language model. The detectors give leads, never verdicts. The
CoCoDet model card states that CoCoDet "should not be used as the sole arbiter of academic misconduct".

### Conflicts of interest

The conflict check flags co-authorship in DBLP within the past three years, the window of the ACM SIGSOFT
Policy on Program Committees. It also flags email domains outside webmail that an author and a committee
member hold in common, affiliations that match by the rules of HotCRP, and declared conflicts that no data
supports.

### Severity

Each finding is an error, a warning, or an info. An error breaks a rule that the venue states, such as the
page limit. A warning marks a likely problem for a person to look at, such as a link to a GitHub account. An
info gives context, such as the count of references found.

## Inputs

- PDFs. The file pattern of the profile maps each file to a paper ID, such as `ICSME_2026_paper_108.pdf`
  from EasyChair or `icse2027-paper108.pdf` from HotCRP. The Files sheet lists names without an ID and
  second files with a taken ID.
- Submission sheet, optional. The EasyChair Excel export or a CSV file with the ID column of the profile
  (`#` for EasyChair). The report adds its columns to a copy of this sheet and marks each paper without a PDF.
- Author list, needed for the author scan. A CSV or Excel file with the columns paper, first, last, email,
  and affiliation. The headers of the EasyChair author export, such as Submission # and First name, work too.
- Reviews. The XML file that EasyChair exports for each review. Fields for the program committee only, such
  as the confidential remarks, never reach the detectors.
- Committee, for conflicts. A CSV or Excel file with first, last, email, affiliation, and an optional DBLP
  person ID, or the EasyChair `reviewer.csv` through `--reviewer-csv`. The EasyChair `assignment.csv`
  (`--assignment-csv`) adds the reviewers of each paper.

## Venue profiles

A profile holds the format rules and the options of every check for one venue. `peercheck profiles` lists
the shipped profiles.

| Profile | Venue | Format | Pages |
|---|---|---|---|
| icsme-2026 (default) | ICSME 2026 Research Track, EasyChair | IEEE, two columns, US Letter | 10 plus 2 of references only |
| icse-2027 | ICSE 2027 Research Track, HotCRP | IEEE, two columns, US Letter | 10 plus 2 of references only |
| fse-2027 | FSE 2027 Research Track, HotCRP | ACM acmsmall, one column | 18 plus 4 of references only |

Another venue needs a copy of a file in `peercheck/profiles/` with its own values, passed by path, such as
`peercheck --profile myvenue.yaml papers pdfs/`. Each value of a shipped profile names its source in a comment.

## Confidentiality

- Every check and every model runs on the machine of the chair.
- The reference check stays offline by default. The profile option `online: true` lets it send DOIs and
  arXiv identifiers to doi.org and arxiv.org. The option `online_titles: true` also sends the titles of
  references.
- `peercheck setup` downloads tools, models, and data, and sends nothing about the conference.
- `.gitignore` keeps PDFs, review XML files, spreadsheets, CSV files, and the folders `submissions/`,
  `reviews/`, `results/`, and `my_files/` out of git, with the test fixtures as the only exception.

## How it works

`peercheck papers`
1. `peercheck/inputs.py`, static. Maps each PDF to a paper ID and reads the submission sheet and the author list.
2. `peercheck/checks/sigsoft.py`, static. Runs the revised SIGSOFT jar once over all PDFs and turns its JSON lines into findings.
3. `peercheck/checks/layout.py`, static. Runs banal, counts main and reference-only pages, and checks the format rules of the profile.
4. `peercheck/checks/hidden_text.py`, static. Runs pdfguardrail and a clip test with PyMuPDF, then matches hidden text against instruction phrases.
5. `peercheck/checks/references.py`, static. Runs Hallucinator against the local DBLP database. `peercheck/retractions.py` then matches the DOIs of the references against the Retraction Watch list.
6. `peercheck/report.py`, static. Writes the workbook and the optional JSON file.

`peercheck reviews`
1. `peercheck/inputs.py`, static. Reads the review XML and joins the fields meant for the authors.
2. `peercheck/reviews/cocodet.py`, call of a local model. Labels each review with CoCoDet.
3. `peercheck/reviews/binoculars.py`, call of two local models. Scores each review with Binoculars on Falcon-7B and Falcon-7B-Instruct.
4. `peercheck/reviews/duplicates.py`, static. Finds paragraphs that appear in two reviews.
5. `peercheck/reviews/citations.py`, static. Finds citation requests and, with a DBLP index, requests for works of the reviewers.
6. `peercheck/report.py`, static. Writes the workbook.

`peercheck conflicts`
1. `peercheck/dblp.py`, static. Builds an index of the publications of the authors and the committee from the DBLP dump.
2. `peercheck/conflicts.py`, static. Applies the conflict rules to each pair of paper and committee member.
3. `peercheck/report.py`, static. Writes the workbook.

Other files
- `peercheck/cli.py` and `peercheck/reviews/cli.py`, static. The command line and the menu.
- `peercheck/pipeline.py`, static. Runs the paper checks and keeps one failure from stopping the batch.
- `peercheck/findings.py`, `models.py`, `profile.py`, and `tools.py`, static. Findings, data types, profiles, and the paths of the bundled tools.
- `peercheck/vendor/` holds banal and the revised SIGSOFT jar. `third_party/` holds the original tools beside each port, with a `PORT.md` for each change.

## Tests

```bash
python -m pip install -e ".[dev,reviews]"
python -m pytest
mvn -f third_party/submission-checker/pom.xml package    # tests of the revised SIGSOFT checker, with a JDK 11+
```

The tests run offline and need no GPU. Tests of banal skip without Perl and poppler. Tests of the jar skip
without Java.

## License

PeerCheck is free software under the GNU General Public License version 3, as `LICENSE` states.
`NOTICE.md` lists the tools of other authors that PeerCheck bundles, ports, or downloads, with their licenses.
