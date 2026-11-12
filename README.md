# 🔎 PeerCheck

[![Tests](https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml/badge.svg)](https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml) ![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white) [![Release](https://img.shields.io/github/v/release/aalramadan/PeerCheck)](https://github.com/aalramadan/PeerCheck/releases/latest) [![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

**PeerCheck** checks the **submissions**, the **reviews**, and the **conflicts of interest** of a conference or a journal.

A check is one test of a file, such as the page limit of a submission, an instruction to AI reviewers hidden in white
text, a reference that no bibliographic database knows, or a review that a language model may have written. Two AI
detectors, CoCoDet and EditLens, give the last of these tests their own labels.

> [!IMPORTANT]
> PeerCheck assists program chairs. A human should verify every flagged paper or review.

> [!TIP]
> The [live demo](https://aalramadan.github.io/PeerCheck/) shows the reports of PeerCheck on the files of
> [`examples/`](examples/). [`external/README.md`](external/README.md) lists every check with the tools and the papers
> it builds on.

## 📦 Requirements

- **Python 3.10** or newer
- **Java 11** or newer, for the anonymity check
- **Perl** and **poppler**, for the format check
- About **3 GB** of disk, 1.1 GB for the reference database and 2 GB for the two AI detectors

On Debian or Ubuntu, `sudo apt install python3-venv default-jre perl poppler-utils` installs these programs. PeerCheck is
tested on Linux, including WSL on Windows.

## 🔧 Installation

```bash
git clone https://github.com/aalramadan/PeerCheck.git  # download the source code
cd PeerCheck                                            # go into the source folder
python3 -m venv .venv && . .venv/bin/activate           # make a Python environment for PeerCheck
pip install -e .                                        # install PeerCheck with its two AI detectors
peercheck setup                                         # download the reference database, once
```

> [!NOTE]
> EditLens needs a free Hugging Face token. Accept its license, which allows non-commercial use only, at
> huggingface.co/pangram/editlens_roberta-large. Then create a read token at huggingface.co/settings/tokens and run
> `export HF_TOKEN=<token>` before PeerCheck. Without a token, PeerCheck skips EditLens and notes the skip in the
> report.

## 🐳 Docker

The image `ghcr.io/aalramadan/peercheck` holds PeerCheck with Java, Perl, and poppler, ready to run without the
requirements or the installation. GitHub Actions rebuilds the image at every change of PeerCheck.

```bash
docker pull ghcr.io/aalramadan/peercheck   # get or update the image
alias peercheck='docker run --rm -v "$PWD:/data" -v peercheck-cache:/cache -e HF_TOKEN ghcr.io/aalramadan/peercheck'
peercheck setup                            # download the reference database, once
```

The commands of the usage example then run in the image, on the files of the current folder. The volume
`peercheck-cache` keeps the reference database and the AI detectors between runs.

## 🚀 Usage

PeerCheck reads a folder of submission PDFs or the review files of a conference, checks them against the rules of the
venue, and writes an HTML report for the browser with an Excel workbook of every detail.

For example, these commands check the submissions and the reviews of a conference whose files sit in the folder
`my-conference`.

```text
my-conference/
  venue.yaml     the rules of the venue, a copy of profiles/default.yaml with its values
  submissions/   the PDFs of the submissions
  reviews/       the reviews, as the XML files of a review export or one CSV file
```

```bash
cd my-conference
peercheck --profile venue.yaml papers submissions/   # check the PDFs, after the submission deadline
peercheck --profile venue.yaml reviews reviews/      # check the reviews, once the reviews are in
```

The first command writes `report.html` and `report.xlsx`. The second writes `reviews.html` and `reviews.xlsx`.

> [!NOTE]
> Without `--profile`, PeerCheck applies the default rules of `profiles/default.yaml`, which set IEEE, two columns,
> US Letter, and 10 pages plus 2 for references.

### Options

| Option | Commands | Description |
|---|---|---|
| `--profile` | all, before the command | The rules and settings of the venue, a copy of `profiles/default.yaml` or an example such as `icse-2027` |
| `--out` | all | The Excel report, with the HTML page beside it, or the folder of marked PDFs for `canary` |
| `--json` | papers, reviews | Also writes the results as JSON |
| `--submissions` | papers | A CSV or Excel list with the number and the title of each paper, for the title check |
| `--authors` | papers, conflicts | A CSV or Excel list of the authors of each paper |
| `--canaries` | reviews | The key file of `canary`, for the check of the planted citations |
| `--pc` | conflicts | A CSV or Excel list of the program committee |
| `--dblp-dump` | conflicts, setup | The DBLP download `dblp.xml.gz` from dblp.org/xml, for the co-author check or the reference database |
| `--dblp-index`, `--save-index` | reviews, conflicts | An index of co-authors that `--save-index` keeps for later runs |
| `--key` | canary | The private file that lists the planted citation of each paper |
| `--retraction-csv`, `--refresh` | setup | A local Retraction Watch list, or a new download of every file |
| `--host`, `--port`, `--no-browser` | gui | The address of the browser page |
| `--help` | all | Prints the options of a command |

### Venue rules

The file `venue.yaml` holds the rules of the venue, such as its template and page limit, and every setting of the
checks. `profiles/default.yaml` lists each rule and setting with its default.

1. Copy `profiles/default.yaml` into the folder of the conference as `venue.yaml`.
2. Set each value from the call for papers. A line that starts with `#` holds a rule that stays unchecked until the
   `#` goes.
3. Pass the copy with `--profile venue.yaml`.

Every check runs until its section sets `enabled: false`, as in this part of a `venue.yaml`.

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
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz   # find conflicts of interest
peercheck canary submissions/ --out marked/ --key canaries.csv                    # plant a made-up citation in each PDF
peercheck --profile venue.yaml reviews reviews/ --canaries canaries.csv           # find reviews that cite it
peercheck gui                                                                     # run the checks from a browser page
```

With Docker, the browser page needs its port, as in `docker run --rm -p 127.0.0.1:8765:8765 -v peercheck-cache:/cache
-e HF_TOKEN ghcr.io/aalramadan/peercheck gui`.

> [!TIP]
> Check the original PDFs with `peercheck papers` before `peercheck canary`, since the hidden-text check reports the
> planted citation. Then upload the marked copies to the conference system in place of the originals, before the
> reviewers download the papers.

> [!WARNING]
> Keep the key file of `peercheck canary` private, since it reveals the planted citation of each paper.

### Inputs

- PDFs with any file names. A number after paper or submission in a name becomes the paper number, such as 12 in
  `CONF_2027_paper_12.pdf`. A PDF without one gets the next free number, which the Files sheet of the report names.
- A submission sheet, any CSV or Excel list with a column of paper numbers, such as # or ID, and a column Title.
- An author list, a CSV or Excel file with the columns paper, first, last, email, and affiliation.
- Reviews, as the XML files of a review export or a CSV file with the columns paper and review (the review ID, such
  as A) and one column per field of the review form, such as the text of the review.
- A committee list with first, last, email, and affiliation. An optional column dblp with the DBLP person ID settles
  a name that several DBLP authors share.

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

- CoCoDet caught 273 of the 297 AI reviews (91.9%) and flagged none of the human or polished reviews.
- EditLens, the second detector, labeled 296 of the 297 AI reviews (99.7%) as AI-Edited. It also caught AI
  polishing in 89 of the 98 polished reviews (90.8%). Of the 1,014 human reviews, it labeled 51 (5.0%) as
  AI-Edited.

## 🧪 Tests

The tests sit in `tests/` and run offline. GitHub Actions runs every test at each push.

- **Check tests** run each check on the small PDFs, review files, and lists of `tests/fixtures/` and on the example
  papers.
- **Command tests** run the commands and check their reports and their messages.
- **Page tests** start the browser page and run checks through its forms.
- The tests of the review checks need PyTorch, which `pip install -e .` installs. One test needs a graphics card.

### Commands

Run these commands in the source folder after `pip install -e ".[dev]"`, which adds pytest and ruff.

| Command | Description |
|---|---|
| `python -m pytest` | Every test |
| `python -m pytest tests/test_references.py` | The tests of one check |
| `python -m pytest -k gui` | The tests whose names hold a word |
| `python -m pytest -x` | Every test, up to the first failure |
| `ruff check src tests` | The style check of the code |
| `mvn -f external/submission-checker/pom.xml package` | Rebuilds the revised SIGSOFT jar of the anonymity check |

## 🔒 Privacy

- Every check and the two AI detectors run on the computer.
- The reference check first looks up each cited work in a local copy of DBLP, which `peercheck setup` downloads.
- Two lines under `references` in `venue.yaml` decide what goes online. Each line is `true` by default.

| Setting | What leaves the computer | Where it goes |
|---|---|---|
| `online: true` and `online_titles: true` | the titles, DOIs, and arXiv IDs of the cited works that DBLP lacks | CrossRef, arXiv, Semantic Scholar, OpenAlex, PubMed, doi.org, and the other sources of Hallucinator, the reference checker |
| `online: true` and `online_titles: false` | the DOIs that the cited works carry, and the arXiv IDs of those that DBLP lacks | doi.org and arXiv |
| `online: false` | nothing | none |

## 📜 License

PeerCheck is free software under the GNU General Public License version 3, as `LICENSE` states. `NOTICE.md` lists
the tools and the data of other authors with their licenses. To cite PeerCheck, use *Cite this repository* on
GitHub, which reads `CITATION.cff`.
