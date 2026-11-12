<h1 align="center">PeerCheck</h1>

<p align="center">PeerCheck automatically checks submissions, reviews, and conflicts of interest for conferences and journals.</p>

<p align="center">
  <a href="https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/aalramadan/PeerCheck/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-3.10%2B-3776AB">
  <a href="https://github.com/aalramadan/PeerCheck/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/aalramadan/PeerCheck"></a>
  <a href="LICENSE"><img alt="License GPL-3.0" src="https://img.shields.io/badge/license-GPL--3.0-blue"></a>
  <img alt="Runs locally" src="https://img.shields.io/badge/runs-locally-2ea44f">
</p>

It reports format violations, anonymity leaks, hidden text, unverifiable references, potentially AI-generated
reviews, and conflicts of interest.

> [!IMPORTANT]
> PeerCheck assists program chairs. A human should verify every flagged paper or review.

## 🎬 Demo

These two report pages show PeerCheck on the made-up papers and reviews in [`examples/`](examples/), whose README
gives the commands.

> [!TIP]
> The [live demo](https://aalramadan.github.io/PeerCheck/) shows the full reports with their Excel workbooks,
> together with reviews from a CSV file and the conflict check. The reports sit in [`examples/reports/`](examples/reports/).

#### Papers

![HTML report of peercheck papers on five sample papers](resources/papers-report.png)

#### Reviews

![HTML report of peercheck reviews on eight sample reviews](resources/reviews-report.png)

## 📦 Install

- PeerCheck is tested on Linux, including WSL on Windows.
- The first review run downloads the two AI detectors, about 2 GB.

#### 🐳 Docker

```bash
docker pull ghcr.io/aalramadan/peercheck   # includes Java, Perl, and poppler
docker run --rm -v peercheck-cache:/cache ghcr.io/aalramadan/peercheck setup   # once, about 1.1 GB
```

#### 🐍 Python

```bash
sudo apt install python3-venv perl poppler-utils default-jre   # Debian or Ubuntu
git clone https://github.com/aalramadan/PeerCheck.git && cd PeerCheck
python3 -m venv .venv && . .venv/bin/activate                  # Python 3.10 or newer
pip install -e .                                               # PeerCheck with its two AI detectors
peercheck setup                                                # once, the reference database, about 1.1 GB
```

#### 🔑 EditLens access

> [!NOTE]
> EditLens needs a free Hugging Face token. Accept its license, which allows non-commercial use only, at
> huggingface.co/pangram/editlens_roberta-large. Then create a read token at huggingface.co/settings/tokens and run
> `export HF_TOKEN=<token>` before PeerCheck or `docker run`. Without a token, PeerCheck skips EditLens and notes
> the skip in the report.

## 🚀 Usage

#### ▶️ Run every check

```text
my-conference/
  venue.yaml     the rules of the venue, a copy of profiles/default.yaml with its values
  submissions/   the PDFs of the submissions
  reviews/       the reviews, as the XML files of a review export or one CSV file
```

```bash
cd my-conference
peercheck --profile venue.yaml papers submissions/   # every check of the PDFs, after the submission deadline
peercheck --profile venue.yaml reviews reviews/      # every check of the reviews, once the reviews are in
```

- The first command writes `report.html` for the browser and `report.xlsx` with every detail. The second writes
  `reviews.html` and `reviews.xlsx`.
- Without `--profile`, PeerCheck applies `profiles/default.yaml`, which sets IEEE, two columns, US Letter, and 10
  pages plus 2 for references.
- With Docker, write `docker run --rm -v "$PWD:/data" -v peercheck-cache:/cache -e HF_TOKEN
  ghcr.io/aalramadan/peercheck` in place of `peercheck`.

#### 🎛️ Customize

- `venue.yaml` holds every setting beside the rules of the venue. Every check runs until its section sets
  `enabled: false`. `profiles/default.yaml` lists each check with its settings and their defaults.
- The settings apply to a command that names `venue.yaml` with `--profile` before the command name.
- The reference check looks up each cited work in the local copy of DBLP and online in CrossRef, arXiv, Semantic
  Scholar, OpenAlex, and other databases. Two lines of `venue.yaml` limit the online lookups.

```yaml
checks:
  references:
    online_titles: false   # sends only DOIs and arXiv IDs, never the titles
    online: false          # keeps the reference check offline
  editlens:
    enabled: false         # turns the AI detector EditLens off
  conflicts:
    coauthor_years: 2      # counts joint papers of the last two years
```

- The command line names the files, as in these commands.

```bash
peercheck --profile venue.yaml papers submissions/ --submissions submissions.xlsx   # adds the title check
peercheck --profile venue.yaml papers submissions/ --authors authors.csv            # finds author names in the PDFs
peercheck --profile venue.yaml reviews reviews/ --canaries canaries.csv             # adds the canary check
```

| Option | Commands | What it does |
|---|---|---|
| `--profile` | all, before the command | names `venue.yaml`, the rules and settings of the venue, or an example such as `icse-2027`, which `papers` needs |
| `--out` | all | names the Excel workbook, with the page for the browser beside it, or the folder of marked PDFs for `peercheck canary` |
| `--json` | papers, reviews | also writes a JSON file |
| `--authors` | papers, conflicts | reads the author list |
| `--submissions` | papers | reads a submission sheet with paper numbers and titles |
| `--canaries` | reviews | runs the planted-citation check with the key file of `peercheck canary` |
| `--pc` | conflicts | reads the committee list |
| `--dblp-dump` | conflicts | builds the co-author index from `dblp.xml.gz`, the full download of DBLP at dblp.org/xml |
| `--dblp-index` | reviews, conflicts | reads the index that `--save-index` of `peercheck conflicts` wrote |
| `--key` | canary | names the private file that lists the planted citation of each paper |

Run any command with `--help` for every option.

#### 🧰 More commands

```bash
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz   # dblp.xml.gz comes from dblp.org/xml
peercheck canary submissions/ --out marked/ --key canaries.csv                    # plants a citation in each PDF
peercheck reviews reviews/ --canaries canaries.csv                                # finds the planted citations
peercheck gui                                                                     # the checks on a page in the browser
```

- With Docker, run `docker run --rm -p 127.0.0.1:8765:8765 -v peercheck-cache:/cache -e HF_TOKEN
  ghcr.io/aalramadan/peercheck gui` and open the address it prints.

> [!TIP]
> Check the original PDFs with `peercheck papers` before `peercheck canary`, since the hidden-text check reports the
> planted citation. Then upload the marked copies to the conference system in place of the originals, before the
> reviewers download the papers.

> [!WARNING]
> Keep the key file of `peercheck canary` private, since it reveals the planted citation of each paper.

#### 📂 Inputs

- PDFs with any file names. A number after paper or submission in a name becomes the paper number, such as 12 in
  `CONF_2027_paper_12.pdf` or `conf2027-paper12.pdf`. A PDF without one gets the next free number, which the Files
  sheet of the report names.
- A submission sheet, any CSV or Excel list with a column of paper numbers, such as # or ID, and a column Title.
- An author list, a CSV or Excel file with the columns paper, first, last, email, and affiliation.
- Reviews, as the XML files of a review export or a CSV file with the columns paper and review (the review ID, such
  as A) and one column per field of the review form, such as the text of the review.
- A committee list with first, last, email, and affiliation. An optional column
  dblp with the DBLP person ID settles a name that several DBLP authors share.

#### 📖 Reports

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

## 🏛️ Venue profiles

- A **profile** holds the rules of one venue, a conference or a journal, such as its template, page limit, and
  margins. It also decides which checks run and how strict each one is.
- `profiles/default.yaml` holds every rule and option with its default value. It applies when a command names no
  `--profile`.
- Two filled copies serve as examples. Each copies the call for papers of its venue and links the call.

| Profile | Venue | Format | Pages |
|---|---|---|---|
| icse-2027 | ICSE 2027 Research Track | IEEE, two columns, US Letter | 10 plus 2 of references |
| fse-2027 | FSE 2027 Research Track | ACM acmsmall, one column | 18 plus 4 of references |

#### ➕ Add a venue

1. Copy `profiles/default.yaml` into the folder of the conference as `venue.yaml`.
2. Set each value from the call for papers. A line that starts with `#` holds a rule that stays unchecked until the
   `#` goes.
3. Pass the copy by path, such as `peercheck --profile venue.yaml papers submissions/`.

| Value | Sets | Example |
|---|---|---|
| `name`, `source` | the name of the venue and the address of its call for papers | `Example Conference 2027` |
| `format.style`, `format.columns`, `format.paper_size` | the template, its columns, and the paper size in points | `IEEE`, `2`, and `[792, 612]` for US Letter |
| `format.main_pages`, `format.reference_pages` | the page limit and the extra pages for references only | `10` and `2` |
| `format.margins`, `format.body_font_max` | the margins in points and the largest font size of the body text | `[52, 48, 72, 48]` and `10.5` |
| `checks` | which checks run and their options, such as the hosts that links may name | the comments in the template |

## 🧪 Tests

```bash
python -m pip install -e ".[dev,reviews]"
python -m pytest                                     # offline; GitHub Actions runs it on each push
mvn -f external/submission-checker/pom.xml package   # rebuilds the revised SIGSOFT jar
```

## 🔒 Privacy

- Every check and the two AI detectors, CoCoDet and EditLens, run on the computer.
- The reference check first looks up each cited work in a local copy of DBLP, which `peercheck setup` downloads.
- Two lines under `references` in `venue.yaml` decide what goes online. Each line is `true` by default.

| Setting | What leaves the computer | Where it goes |
|---|---|---|
| `online: true` and `online_titles: true` | the titles, DOIs, and arXiv IDs of the cited works that DBLP lacks | CrossRef, arXiv, Semantic Scholar, OpenAlex, PubMed, doi.org, and the other sources of Hallucinator, the reference checker |
| `online: true` and `online_titles: false` | the DOIs that the cited works carry, and the arXiv IDs of those that DBLP lacks | doi.org and arXiv |
| `online: false` | nothing | none |

## 📄 License

- PeerCheck is licensed under the GNU General Public License version 3.
- `NOTICE.md` lists the tools of other authors with their licenses.
- To cite PeerCheck, use *Cite this repository* on GitHub, which reads `CITATION.cff`.
