# 🔎 PeerCheck

[![Tests](https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml/badge.svg)](https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml) ![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white) [![Release](https://img.shields.io/github/v/release/aalramadan/PeerCheck)](https://github.com/aalramadan/PeerCheck/releases/latest) [![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

**PeerCheck** checks the **submissions**, the **reviews**, and the **conflicts of interest** of a publication venue.

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
> [`examples/`](examples/). [`external/README.md`](external/README.md) names every check with the tools and the papers
> it builds on.

## 📦 Requirements

- **Python 3.10** or newer with venv (`python3-venv`)
- **Java 11** or newer (`default-jre`)
- **Perl** (`perl`) and **poppler** (`poppler-utils`)
- Approximately **7 GB** of disk space for DBLP and the two AI detectors

## 🔧 Installation

```bash
git clone https://github.com/aalramadan/PeerCheck.git  # clone the repository
cd PeerCheck                                            # enter the repository folder
python3 -m venv .venv                                   # create a virtual environment
source .venv/bin/activate                               # activate the virtual environment
pip install .                                           # install PeerCheck and its two AI detectors
peercheck --setup                                       # download Hallucinator, DBLP, and the Retraction Watch data
```

> [!NOTE]
> EditLens requires a free [Hugging Face token](https://huggingface.co/settings/tokens) in `HF_TOKEN`. Without a
> token, PeerCheck skips EditLens.

## 🐳 Docker

The image `ghcr.io/aalramadan/peercheck` contains PeerCheck and its requirements.

```bash
docker pull ghcr.io/aalramadan/peercheck   # pull or update the image
alias peercheck='docker run --rm -v "$PWD:/data" -v peercheck-cache:/cache -e HF_TOKEN ghcr.io/aalramadan/peercheck'  # run PeerCheck inside the container
peercheck --setup                          # download Hallucinator, DBLP, and the Retraction Watch data
```

## 🚀 Usage

PeerCheck reads the submission PDFs or the reviews file of a venue, checks them against its template, and writes an
HTML report and a CSV file with one row per paper, review, or conflict.

### Templates

A template is a YAML file with the rules of a venue and the settings of every check. `templates/default.yaml` holds
every rule and setting with its default and applies when no `--template` is given.

1. Copy `templates/default.yaml` into the folder of the venue as `template.yaml`.
2. Set each value according to the call for papers. A line that starts with `#` is inactive until the `#` is
   removed.
3. Pass the copy with `--template template.yaml`.

```yaml
checks:
  references:
    online_titles: false   # send only DOIs and arXiv IDs, never titles
  # editlens:              # skip the AI detector EditLens
  conflicts:
    coauthor_years: 2      # count joint papers of the last two years
```

Two templates of real venues serve as examples, each with the address of its call for papers.

| Template | Venue | Format | Pages |
|---|---|---|---|
| `icse-2027` | ICSE 2027 Research Track | IEEE, two columns, US Letter | 10 plus 2 for references |
| `fse-2027` | FSE 2027 Research Track | ACM acmsmall, one column | 18 plus 4 for references |

Each check has a key in the template and runs while the key is present. Commenting out the key and its settings turns
the check off.

#### Papers (`--papers`)

| Check | Template key | Detects |
|---|---|---|
| Format | `layout` | Page size, columns, margins, fonts, page limits, unusual density, damaged files, unresolved references, title mismatches, and oversized images |
| Anonymity and template | `sigsoft` | Author names, email addresses, affiliations, and identifying links in the text and the metadata, and a wrong template |
| Hidden text | `hidden_text` | White, invisible, or tiny text, hidden prompts, and embedded scripts |
| References | `references` | Unconfirmed and retracted references |

#### Reviews (`--reviews`)

| Check | Template key | Detects |
|---|---|---|
| AI detection | `cocodet`, `editlens` | Reviews likely written or edited by a language model |
| Copied text | `duplicates` | Paragraphs shared between reviews |
| Citation requests | `citations` | Requests to cite works, including works of the reviewer |
| Planted citation | `canary` | Reviews that cite the planted work |

#### Conflicts of interest (`--conflicts`)

| Check | Template key | Detects |
|---|---|---|
| Conflicts of interest | `conflicts` | Co-authorship, shared email domains, and matching affiliations |

### Commands

PeerCheck has three main commands, `--papers`, `--reviews`, and `--conflicts`. Each table opens with a main command
and names the options that the command takes.

#### `--papers`

| Command | Description |
|---|---|
| `--papers <folder>` | Checks the submission PDFs (`.pdf`) of a folder |
| `--template <file>` | Template of the venue (`.yaml`), `templates/default.yaml` by default |
| `--submissions <file>` | Submissions file (`.csv`) for the title check |
| `--authors <file>` | Authors file (`.csv`) for the anonymity check |
| `--out <file>` | CSV report (`.csv`) with the HTML report (`.html`) beside it, `papers-report.csv` by default |

#### `--reviews`

| Command | Description |
|---|---|
| `--reviews <file>` | Checks the reviews of a reviews file (`.csv`) |
| `--template <file>` | Template of the venue (`.yaml`), `templates/default.yaml` by default |
| `--canaries <file>` | Canary key file (`.csv`) of `--canary` for the planted-citation check |
| `--out <file>` | CSV report (`.csv`) with the HTML report (`.html`) beside it, `reviews-report.csv` by default |

#### `--conflicts`

| Command | Description |
|---|---|
| `--conflicts` | Finds conflicts of interest between the authors and the committee, with co-authorship from DBLP after `--setup` |
| `--authors <file>` | Authors file (`.csv`), required |
| `--pc <file>` | Committee file (`.csv`), required |
| `--template <file>` | Template of the venue (`.yaml`), `templates/default.yaml` by default |
| `--out <file>` | CSV report (`.csv`) with the HTML report (`.html`) beside it, `conflicts-report.csv` by default |

#### Other commands

| Command | Description |
|---|---|
| `--canary <folder> --out <folder> --canaries <file>` | Copies of the PDFs (`.pdf`) of a folder, each with a fictitious citation, and the canary key file (`.csv`) |
| `--setup` | Downloads Hallucinator, DBLP, and the Retraction Watch data |
| `--setup --refresh` | New download of every file of `--setup` |
| `--setup --retraction-csv <file>` | Local Retraction Watch file (`.csv`) in place of its download |
| `--gui` | Opens the browser interface |
| `--help`, `--version` | Help and version of PeerCheck |

### Input format

PDFs may carry any names. PeerCheck takes the paper number from the name, such as 12 in `CONF_2027_paper_12.pdf`.

The other inputs are CSV files with a header row and one row per entry. `--conflicts` requires the authors
file and the committee file. For `--papers`, the authors file and the submissions file are optional and enable the
checks that the column Purpose names. Common variants of the header names are accepted, such as `First Name` or
`Submission #`. The matching files in [`examples/`](examples/) serve as starting points.

| File | Purpose | One row per | Columns |
|---|---|---|---|
| Authors file (`--authors`) | Author names for the anonymity check of `--papers`, and the authors for `--conflicts` | Author of a paper | `paper` (paper number), `first`, `last`, `email`, and `affiliation` |
| Committee file (`--pc`) | Committee members for `--conflicts` | Committee member | `first`, `last`, `email`, `affiliation`, and an optional `dblp` (DBLP person ID) |
| Submissions file (`--submissions`) | Paper titles for the title check of `--papers`, and the papers without a PDF | Paper | `paper` and `title` |
| Reviews file (`--reviews`) | Reviews for `--reviews` | Review | `paper`, `review` (review ID, such as A), the optional `title`, `reviewername`, and `email`, and one column per field of the review form |

The reviews file gives each field of the review form a column, such as `Overall evaluation`, `Comments for authors`,
or `Comments for PC`. A column of short values, such as -2 or B, counts as a score. The AI detectors read only the
text for the authors and skip the fields for the committee only, such as `Comments for PC`. The optional columns
`reviewername` and `email` allow the citation check to find works of a reviewer whom the committee file names, once
`--conflicts` has run after `--setup`. `--canary` generates the key file of `--canaries`.

```bash
# authors.csv, the authors file for --authors, as examples/authors.csv
paper,first,last,email,affiliation
1,Maria,Okafor,maria.okafor@lakeside.example,Lakeside Institute of Technology

# pc.csv, the committee file for --pc, as examples/committee.csv, with an optional dblp person ID
first,last,email,affiliation,dblp
Paul,Meier,paul.meier@uni-nowhere.edu,University of Nowhere,

# submissions.csv, the submissions file for --submissions
paper,title
1,A Study of Flaky Tests

# reviews.csv, the reviews file for --reviews, as examples/reviews/reviews.csv, with one column per field of the review form
paper,review,Overall evaluation,Comments for authors
1,A,2,"The paper proposes ..."
```

### Examples

These commands check a venue whose files are stored in the folder `my-venue`.

```bash
my-venue/
  template.yaml   # the template of the venue, a copy of templates/default.yaml
  submissions/    # the PDFs of the submissions
  reviews.csv     # the reviews file
  authors.csv     # the authors file
  pc.csv          # the committee file
```

```bash
cd my-venue
peercheck --template template.yaml --papers submissions/                          # check the PDFs
peercheck --template template.yaml --reviews reviews.csv                          # check the reviews
peercheck --conflicts --authors authors.csv --pc pc.csv                           # find conflicts of interest
peercheck --canary submissions/ --out marked/ --canaries canaries.csv             # insert a fictitious citation into each PDF
peercheck --template template.yaml --reviews reviews.csv --canaries canaries.csv  # find reviews that cite the planted work
peercheck --gui                                                                   # open the browser interface
```

The first command writes `papers-report.html` and `papers-report.csv`. The second writes `reviews-report.html` and
`reviews-report.csv`. With Docker, the browser interface requires a published port, as in `docker run --rm -p
127.0.0.1:8765:8765 -v peercheck-cache:/cache -e HF_TOKEN ghcr.io/aalramadan/peercheck --gui`.

> [!TIP]
> Check the original PDFs with `--papers` before `--canary`, since the hidden-text check reports the planted
> citation. Then upload the marked copies to the submission system in place of the originals, before the reviewers
> download the papers.

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

- **Check tests** run each check on the small PDFs and CSV files of `tests/fixtures/` and on the example
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
- Two settings under `references` in the template control the data that PeerCheck sends to online databases. Each
  is `true` by default.

| Setting | Data sent | Destination |
|---|---|---|
| `online: true` and `online_titles: true` | Titles, DOIs, and arXiv IDs of references missing from DBLP | CrossRef, arXiv, Semantic Scholar, OpenAlex, PubMed, doi.org, and other sources of Hallucinator |
| `online: true` and `online_titles: false` | DOIs of references, and arXiv IDs of references missing from DBLP | doi.org and arXiv |
| `online: false` | None | None |

## 📜 License

PeerCheck is free software under the GNU General Public License version 3, as `LICENSE` states. `NOTICE.md` names
the tools and the data of other authors with their licenses. To cite PeerCheck, use *Cite this repository* on
GitHub, which reads `CITATION.cff`.
