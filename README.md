# 🔎 PeerCheck

[![Tests](https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml/badge.svg)](https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml) ![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white) [![Release](https://img.shields.io/github/v/release/aalramadan/PeerCheck)](https://github.com/aalramadan/PeerCheck/releases/latest) [![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

**PeerCheck** checks the **submissions**, the **reviews**, and the **conflicts of interest** of a conference or a journal.

- 📄 For **papers**, it checks the format and page limits, anonymity leaks, hidden text and prompts, and references
  that no bibliographic database confirms.
- 📝 For **reviews**, it runs two AI detectors, CoCoDet and EditLens, and finds text copied between reviews, excessive
  citation requests, and planted citations.
- 🤝 For **conflicts of interest**, it compares the co-authorship, the email domains, and the affiliations of the
  authors and the committee members.

> [!IMPORTANT]
> PeerCheck assists program chairs. A human should verify every flagged paper or review.

> [!TIP]
> The [live demo](https://aalramadan.github.io/PeerCheck/) shows the reports of PeerCheck on the files of
> [`examples/`](examples/). [`external/README.md`](external/README.md) lists every check with the tools and the papers
> it builds on.

## 📦 Requirements

- **Python 3.10** or newer with venv (`python3-venv`)
- **Java 11** or newer (`default-jre`)
- **Perl** (`perl`) and **poppler** (`poppler-utils`)
- Approximately **3 GB** of disk space for DBLP and the two AI detectors

## 🔧 Installation

```bash
git clone https://github.com/aalramadan/PeerCheck.git  # clone the repository
cd PeerCheck                                            # enter the repository folder
python3 -m venv .venv                                   # create a virtual environment
source .venv/bin/activate                               # activate the virtual environment
pip install .                                           # install PeerCheck and its two AI detectors
peercheck --setup                                       # download Hallucinator, DBLP, and the Retraction Watch list
```

> [!NOTE]
> EditLens requires a free [Hugging Face token](https://huggingface.co/settings/tokens) in `HF_TOKEN`. Without a
> token, PeerCheck skips EditLens.

## 🐳 Docker

The image `ghcr.io/aalramadan/peercheck` contains PeerCheck and its requirements.

```bash
docker pull ghcr.io/aalramadan/peercheck   # pull or update the image
alias peercheck='docker run --rm -v "$PWD:/data" -v peercheck-cache:/cache -e HF_TOKEN ghcr.io/aalramadan/peercheck'  # run PeerCheck inside the container
peercheck --setup                          # download Hallucinator, DBLP, and the Retraction Watch list
```

## 🚀 Usage

PeerCheck reads the submission PDFs or the XML and CSV review files of a conference, checks them against the rules of
the venue, and writes an HTML report together with an Excel workbook of every detail.

For example, these commands check the submissions and the reviews of a conference whose files are stored in the
folder `my-conference`.

```bash
my-conference/
  venue.yaml     # the rules of the venue, a copy of profiles/default.yaml
  submissions/   # the PDFs of the submissions
  reviews/       # the reviews, as the XML files of a review export or one CSV file
```

```bash
cd my-conference
peercheck --profile venue.yaml --papers submissions/   # check the PDFs
peercheck --profile venue.yaml --reviews reviews/      # check the reviews
```

The first command writes `report.html` and `report.xlsx`. The second writes `reviews.html` and `reviews.xlsx`.

PeerCheck takes the paper number from the PDF name, such as 12 in `CONF_2027_paper_12.pdf`.

> [!NOTE]
> Without `--profile`, PeerCheck applies the default rules of `profiles/default.yaml`, which set IEEE, two columns,
> US Letter, and 10 pages plus 2 for references.

### Checks

Each check has a section in `venue.yaml`, where `enabled: false` turns it off.

#### Papers (`--papers`)

| Check | Section | Detects |
|---|---|---|
| Format | `layout` | Page size, columns, margins, fonts, page limits, unusual density, damaged files, unresolved references, title mismatches, and oversized images |
| Anonymity and template | `sigsoft` | Author names, email addresses, affiliations, and identifying links in the text and the metadata, and a wrong template |
| Hidden text | `hidden_text` | White, invisible, or tiny text, hidden prompts, and embedded scripts |
| References | `references` | Unconfirmed and retracted references |

#### Reviews (`--reviews`)

| Check | Section | Detects |
|---|---|---|
| AI detection | `cocodet`, `editlens` | Reviews likely written or edited by a language model |
| Copied text | `duplicates` | Paragraphs shared between reviews |
| Citation requests | `citations` | Requests to cite works, including works of the reviewer |
| Planted citation | `canary` | Reviews that cite the planted work |

#### Conflicts of interest (`--conflicts`)

| Check | Section | Detects |
|---|---|---|
| Conflicts of interest | `conflicts` | Co-authorship, shared email domains, and matching affiliations |

### Commands

| Command | Description |
|---|---|
| `--papers <folder>` | Checks the submission PDFs (`.pdf`) of a folder |
| `--reviews <folder or file>` | Checks the reviews (`.xml`, `.csv`) |
| `--conflicts` | Finds conflicts of interest |
| `--canary <folder>` | Inserts a fictitious citation into each PDF of a folder |
| `--setup` | Downloads Hallucinator, DBLP, and the Retraction Watch list |
| `--gui` | Opens the browser interface |
| `--profile <file>` | Venue rules and settings (`.yaml`) |
| `--out <file or folder>` | Excel report (`.xlsx`) with the HTML report (`.html`) beside it, or the folder of the marked PDFs of `--canary` |
| `--json <file>` | JSON output (`.json`) |
| `--submissions <file>` | Submission sheet (`.csv`, `.xlsx`) |
| `--authors <file>` | Author list (`.csv`, `.xlsx`) |
| `--pc <file>` | Committee list (`.csv`, `.xlsx`) |
| `--canaries <file>` | Canary key file (`.csv`) that `--canary` writes and `--reviews` reads |
| `--dblp-dump <file>` | DBLP dump (`.xml.gz`) from dblp.org/xml |
| `--save-index <file>` | Co-author index (`.json.gz`) to save from the DBLP dump |
| `--dblp-index <file>` | Co-author index (`.json.gz`) saved by an earlier run |
| `--retraction-csv <file>` | Local Retraction Watch list (`.csv`) for `--setup` |
| `--refresh` | New download of every file of `--setup` |
| `--host <address>` | Address of the browser interface |
| `--port <number>` | Port of the browser interface |
| `--no-browser` | Browser interface without a browser window |
| `--help` | Help of a command |

### Lists

Each list is a CSV or Excel file with a header row and one row per entry. Common variants of the header names are
accepted, such as `First Name` or `Submission #`. The corresponding files in [`examples/`](examples/) serve as
templates.

| List | One row per | Columns |
|---|---|---|
| Author list (`--authors`) | Author of a paper | `paper` (paper number), `first`, `last`, `email`, and `affiliation` |
| Committee list (`--pc`) | Committee member | `first`, `last`, `email`, `affiliation`, and an optional `dblp` (DBLP person ID) |
| Submission sheet (`--submissions`) | Paper | `paper` and `title` |
| Reviews (`--reviews`) | Review | `paper`, `review` (review ID, such as A), and one column per field of the review form |

Fields intended for the committee only, such as `Comments for PC`, are excluded from AI detection.

```bash
# authors.csv, the author list for --authors, as examples/authors.csv
paper,first,last,email,affiliation
1,Maria,Okafor,maria.okafor@lakeside.example,Lakeside Institute of Technology

# pc.csv, the committee list for --pc, as examples/committee.csv, with an optional dblp person ID
first,last,email,affiliation,dblp
Paul,Meier,paul.meier@uni-nowhere.edu,University of Nowhere,

# submissions.csv, the submission sheet for --submissions
paper,title
1,A Study of Flaky Tests

# reviews.csv, reviews as one CSV file, as examples/reviews.csv, with one column per field of the review form
paper,review,Comments for authors
1,A,"The paper proposes ..."
```

`--canary` generates the key file of `--canaries`.

### Venue rules

The file `venue.yaml` contains the rules of the venue, such as its template and page limit, and every setting of the
checks. `profiles/default.yaml` lists each rule and setting with its default.

1. Copy `profiles/default.yaml` into the folder of the conference as `venue.yaml`.
2. Set each value according to the call for papers. A line that starts with `#` is inactive until the `#` is
   removed.
3. Pass the copy with `--profile venue.yaml`.

Every check runs unless its section sets `enabled: false`, as in this excerpt of a `venue.yaml`.

```yaml
checks:
  references:
    online_titles: false   # send only DOIs and arXiv IDs, never titles
  editlens:
    enabled: false         # turn the AI detector EditLens off
  conflicts:
    coauthor_years: 2      # count joint papers of the last two years
```

Two venues serve as examples, each with the address of its call for papers.

| Profile | Venue | Format | Pages |
|---|---|---|---|
| `icse-2027` | ICSE 2027 Research Track | IEEE, two columns, US Letter | 10 plus 2 for references |
| `fse-2027` | FSE 2027 Research Track | ACM acmsmall, one column | 18 plus 4 for references |

### Other commands

```bash
peercheck --conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz   # find conflicts of interest
peercheck --canary submissions/ --out marked/ --canaries canaries.csv               # insert a fictitious citation into each PDF
peercheck --profile venue.yaml --reviews reviews/ --canaries canaries.csv           # find reviews that cite the planted work
peercheck --gui                                                                     # open the browser interface
```

With Docker, the browser interface requires a published port, as in `docker run --rm -p 127.0.0.1:8765:8765 -v
peercheck-cache:/cache -e HF_TOKEN ghcr.io/aalramadan/peercheck --gui`.

> [!TIP]
> Check the original PDFs with `--papers` before `--canary`, since the hidden-text check reports the
> planted citation. Then upload the marked copies to the conference system in place of the originals, before the
> reviewers download the papers.

> [!WARNING]
> Keep the key file of `--canary` private, since it reveals the planted citation of each paper.

### Reports

- An **error** breaks a stated rule of the venue.
- A **warning** marks a likely problem.
- An **info** note gives context.
- A **red bar** marks a paper or a review with an error or a warning.
- **CoCoDet** labels a review as Human, Mix (partly human and partly AI), or AI. Its label AI marks the review for a
  closer look.
- **CoCoDet P(AI)** is the probability, from 0 to 1, that CoCoDet gives to the label AI.
- **EditLens** labels a review as Human, AI-Edited (human writing that AI edited), or AI, as a second opinion.
- **EditLens Score** runs from 0 for human writing to 1 for AI writing. A score below 0.0971 reads as Human, a
  score of 0.997 or more as AI, and a score between them as AI-Edited.

## 📊 Benchmark

We tested the two AI detectors on 1,409 reviews of ICLR 2017 papers, in three groups.

- 1,014 human reviews, the official reviews in [PeerRead](https://github.com/allenai/PeerRead), a public dataset of
  peer reviews, written in 2016 before AI writing tools.
- 98 polished reviews, each a copy of one of these human reviews that a model polished.
- 297 AI reviews, written by DiffusionGemma 26B, Gemma 4 31B, Mistral Large 4, Nemotron 3 Ultra, and Step 5.

| Written by | Reviews | CoCoDet (AI) | EditLens (AI-Edited) | EditLens (AI) |
|---|---|---|---|---|
| People | 1,014 | 0 | 51 | 0 |
| People, then polished by a model | 98 | 0 | 89 | 0 |
| DiffusionGemma 26B | 58 | 58 | 58 | 0 |
| Gemma 4 31B | 60 | 60 | 60 | 0 |
| Mistral Large 4 | 60 | 52 | 60 | 0 |
| Nemotron 3 Ultra | 60 | 56 | 60 | 0 |
| Step 5 | 59 | 47 | 58 | 0 |
| **Total** | **1,409** | **273** | **436** | **0** |

- CoCoDet detected 273 of the 297 AI reviews (91.9%) and flagged none of the human or polished reviews.
- EditLens, the second detector, labeled 296 of the 297 AI reviews (99.7%) as AI-Edited. It also detected AI
  polishing in 89 of the 98 polished reviews (90.8%). Of the 1,014 human reviews, it labeled 51 (5.0%) as
  AI-Edited.

## 🧪 Tests

The tests reside in `tests/` and run offline. GitHub Actions runs the full suite on every push.

- **Check tests** run each check on the small PDFs, review files, and lists of `tests/fixtures/` and on the example
  papers.
- **Command tests** run the commands and check their reports and their messages.
- **Interface tests** start the browser interface and run checks through its forms.
- The tests of the review checks require PyTorch, which `pip install` provides. One test requires a graphics card.

### Test commands

Run these commands in the repository folder after `pip install -e ".[dev]"`. The option `-e` installs PeerCheck in
editable mode. The group `[dev]` adds pytest and ruff.

| Command | Description |
|---|---|
| `python -m pytest` | All tests |
| `python -m pytest tests/test_references.py` | Tests of one check |
| `python -m pytest -k gui` | Tests that match a keyword |
| `python -m pytest -x` | All tests, up to the first failure |
| `ruff check src tests` | Code style check |
| `mvn -f external/submission-checker/pom.xml package` | Rebuild of the SIGSOFT jar of the anonymity check |

## 🔒 Privacy

- PeerCheck runs all checks locally, including the two AI detectors.
- The reference check first looks up each cited work in a local copy of DBLP.
- Two settings under `references` in `venue.yaml` control the data that PeerCheck sends to online databases. Each
  is `true` by default.

| Setting | Data sent | Destination |
|---|---|---|
| `online: true` and `online_titles: true` | Titles, DOIs, and arXiv IDs of references missing from DBLP | CrossRef, arXiv, Semantic Scholar, OpenAlex, PubMed, doi.org, and other sources of Hallucinator |
| `online: true` and `online_titles: false` | DOIs of references, and arXiv IDs of references missing from DBLP | doi.org and arXiv |
| `online: false` | None | None |

## 📜 License

PeerCheck is free software under the GNU General Public License version 3, as `LICENSE` states. `NOTICE.md` lists
the tools and the data of other authors with their licenses. To cite PeerCheck, use *Cite this repository* on
GitHub, which reads `CITATION.cff`.
