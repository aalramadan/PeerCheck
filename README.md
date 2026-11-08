<h1 align="center">PeerCheck</h1>

<p align="center">PeerCheck automatically checks submissions, reviews, and conflicts of interest for software engineering conferences.</p>

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
> PeerCheck assists the organizers of the review process. Every flagged paper or review should be checked by a
> person.

## 🎬 Demo

These two report pages come from the commands below.

```bash
peercheck --profile samples/venue.yaml papers samples/papers --authors samples/authors.csv \
  --checks layout,sigsoft,hidden-text --html report.html
peercheck --profile samples/venue.yaml reviews samples/reviews --canaries samples/canaries.csv --html reviews.html
```

> [!TIP]
> The [live demo](https://aalramadan.github.io/PeerCheck/) shows the full reports with their Excel workbooks,
> together with a review export of HotCRP and the conflict check. The reports sit in [`examples/`](examples/).

#### Papers

![HTML report of peercheck papers on five sample papers](docs/papers-report.png)

#### Reviews

![HTML report of peercheck reviews on eight sample reviews](docs/reviews-report.png)

## 📊 Benchmark

We tested the two AI detectors on 1,409 reviews.

- 1,014 reviews written by people, the official reviews of ICLR 2017 in
  [PeerRead](https://github.com/allenai/PeerRead), a public dataset of peer reviews, written in 2016 before AI
  writing tools.
- 297 reviews of 60 of these papers, written by five current models on NVIDIA build, the model service of NVIDIA.
- 98 of the human reviews, each polished by a model.

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
- EditLens labeled 296 of the 297 AI reviews as AI-Edited. It also labeled 89 of the 98 polished reviews (90.8%)
  and 51 of the 1,014 human reviews (5.0%) as AI-Edited. It cannot tell a review that AI wrote from one that AI
  polished.
- Flagging only the reviews that the two detectors call AI would have caught 208 of the 297 AI reviews (70.0%).
  PeerCheck therefore reports each detector on its own.
- On 900 reviews of the [CoCoNUTS](https://huggingface.co/datasets/khaaaaaan/CoCoNUTS) test set, from the
  collection that CoCoDet was trained on, CoCoDet caught 298 of the 300 AI reviews and flagged 3 of the 450 human
  reviews, all three polished by AI.

## 📦 Install

- PeerCheck is tested on Linux, including WSL on Windows.
- The models and the DBLP database take about 5 GB of disk.

#### 🐳 Docker

```bash
docker run --rm -v "$PWD:/data" -v peercheck-cache:/cache -e HF_TOKEN ghcr.io/aalramadan/peercheck \
  reviews reviews/ --html reviews.html
docker run --rm -p 127.0.0.1:8765:8765 -v peercheck-cache:/cache -e HF_TOKEN ghcr.io/aalramadan/peercheck gui
```

- The image holds PeerCheck with Python, Java, Perl, and poppler. GitHub Actions rebuilds it at every change.
- `-v "$PWD:/data"` gives the container the current folder.
- `-v peercheck-cache:/cache` keeps the models between runs.
- `-e HF_TOKEN` passes the token of EditLens, as EditLens access below describes.
- The second command serves the page of `peercheck gui` at the address it prints, through the port that
  `-p 127.0.0.1:8765:8765` opens.

#### 🐍 Python

PeerCheck needs these programs.

- Python 3.10 or newer
- Perl and poppler, for the format check
- Java 11 or newer, for the anonymity and template check

```bash
sudo apt install perl poppler-utils default-jre   # Debian or Ubuntu
brew install poppler openjdk                      # macOS, which already has Perl
```

```bash
git clone https://github.com/aalramadan/PeerCheck.git
cd PeerCheck
python -m pip install -e ".[reviews]"   # installs every check
peercheck doctor                        # lists missing programs
peercheck setup references              # downloads Hallucinator, the DBLP database, and the Retraction Watch list
peercheck setup cocodet                 # downloads the CoCoDet model, about 600 MB
peercheck setup editlens                # downloads the EditLens model, about 1.4 GB, after the steps below
```

> [!TIP]
> To check only submissions and conflicts, `python -m pip install -e .` installs PeerCheck without the review
> checks.

#### 🔑 EditLens access

> [!NOTE]
> The authors of EditLens give the model only to users who accept its license, which allows non-commercial use
> only.

1. Create a free account at huggingface.co.
2. Accept the license at huggingface.co/pangram/editlens_roberta-large.
3. Create a token with read access at huggingface.co/settings/tokens. Then run `hf auth login` or set the
   variable `HF_TOKEN` to the token.
4. Run `peercheck setup editlens`.

> [!TIP]
> To skip EditLens, check the reviews with `--detectors cocodet`.

## 🚀 Usage

```bash
peercheck papers submissions/ --authors authors.csv --html report.html   # checks the submission PDFs
peercheck reviews reviews/ --html reviews.html                           # checks the reviews
peercheck conflicts --authors authors.csv --pc pc.csv --dblp-dump dblp.xml.gz
peercheck canary submissions/ --out marked/ --key canaries.csv           # plants a citation in each PDF
peercheck reviews reviews/ --canaries canaries.csv                       # finds the planted citations
peercheck --profile fse-2027 papers submissions/                         # uses the rules of FSE 2027
peercheck gui                                                            # opens the checks as a page in the browser
peercheck menu                                                           # opens an interactive menu
```

- Each command writes an Excel workbook.
- The commands read the unchanged exports of EasyChair and HotCRP, the two conference systems, and plain CSV or
  Excel lists.
  - PDFs named with their paper ID, as EasyChair and HotCRP name them, such as `conf2027-paper12.pdf`.
  - An author list, a CSV or Excel file with the columns paper, first, last, email, and affiliation.
  - Reviews, as the XML files of EasyChair, the review CSV file of HotCRP, or any CSV file with the columns paper
    and review and one column per field of the review form.
  - A committee list with first, last, email, and affiliation, or the EasyChair file `reviewer.csv`. An optional
    column dblp with the DBLP person ID settles a name that several DBLP authors share.

> [!TIP]
> Check the original PDFs with `peercheck papers` before `peercheck canary`, since the hidden-text check reports the
> planted citation. Then upload the marked copies to the conference system in place of the originals, before the
> reviewers download the papers.

> [!WARNING]
> Keep the key file of `peercheck canary` private, since it reveals the planted citation of each paper.

#### ⚙️ Options

| Option | Commands | What it does |
|---|---|---|
| `--profile` | all, before the command | picks the venue profile, the rules of one venue, `icse-2027` by default |
| `--out` | all | names the Excel workbook, or the folder of marked PDFs for `peercheck canary` |
| `--json`, `--html` | papers, reviews | also write a JSON file or a page for the browser |
| `--authors` | papers, conflicts | reads the author list |
| `--submissions` | papers | reads the submission sheet of EasyChair or HotCRP |
| `--checks` | papers, reviews | runs only the checks it names, such as `--checks layout,references`, from the list of checks in `external/README.md` |
| `--detectors` | reviews | picks the AI detectors, `cocodet,editlens` by default |
| `--canaries` | reviews | runs the planted-citation check with the key file of `peercheck canary` |
| `--device` | reviews | runs the detectors on the processor (`cpu`) or an NVIDIA graphics card (`cuda`) |
| `--pc`, `--reviewer-csv` | conflicts | read the committee list |
| `--conflict-csv` | conflicts | reads the declared conflicts that EasyChair exports |
| `--dblp-dump` | conflicts | builds the co-author index from `dblp.xml.gz`, the full download of DBLP at dblp.org/xml |
| `--dblp-index` | reviews, conflicts | reads the index that `--save-index` of `peercheck conflicts` wrote |
| `--years` | conflicts | sets the co-authorship window, 3 years by default |
| `--key` | canary | names the private file that lists the planted citation of each paper |

Run any command with `--help` for every option.

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

## 🏛️ Venue profiles

PeerCheck is tuned for software engineering venues and ships with these profiles.

| Profile | Venue | Format | Pages |
|---|---|---|---|
| icse-2027 (default) | ICSE 2027 Research Track | IEEE, two columns, US Letter | 10 plus 2 of references |
| fse-2027 | FSE 2027 Research Track | ACM acmsmall, one column | 18 plus 4 of references |
| example-easychair | an example venue on EasyChair | IEEE, two columns, US Letter | 10 plus 2 of references |

Any other venue gets a profile in three steps.

1. Copy a file of `src/profiles/`, such as `example-easychair.yaml` for a venue on EasyChair.
2. Change its values.
3. Pass the copy by path, such as `peercheck --profile myvenue.yaml papers submissions/`.

## 🧪 Tests

```bash
python -m pip install -e ".[dev,reviews]"
python -m pytest                                     # offline; GitHub Actions runs it on each push
mvn -f external/submission-checker/pom.xml package   # rebuilds the revised SIGSOFT jar
```

## 🔒 Privacy

- Every check and every model runs locally.
- The reference check stays offline by default. The profile option `online: true` sends DOIs and arXiv
  identifiers to doi.org and arxiv.org. The option `online_titles: true` also sends reference titles.
- `.gitignore` keeps PDFs, review XML files, spreadsheets, and CSV files out of git, except the test fixtures and
  the samples.

## 📄 License

- PeerCheck is licensed under the GNU General Public License version 3.
- `NOTICE.md` lists the tools of other authors with their licenses.
- To cite PeerCheck, use *Cite this repository* on GitHub, which reads `CITATION.cff`.

## 📚 References

1. CoCoDet: Chen et al. 2026. *CoCoNUTS: Concentrating on Content while Neglecting Uninformative Textual Styles
   for AI-Generated Peer Review Detection.* ACL 2026.
   [doi.org/10.18653/v1/2026.acl-long.1240](https://doi.org/10.18653/v1/2026.acl-long.1240)
2. EditLens: Thai et al. 2026. *EditLens: Quantifying the Extent of AI Editing in Text.* ICLR 2026.
   [arxiv.org/abs/2510.03154](https://arxiv.org/abs/2510.03154)
3. Canary check: Rao et al. 2025. *Detecting LLM-generated peer reviews.* PLOS ONE.
   [doi.org/10.1371/journal.pone.0331871](https://doi.org/10.1371/journal.pone.0331871)
4. Canary check: ICML. 2026. *On Violations of LLM Review Policies.* ICML Blog.
   [blog.icml.cc](https://blog.icml.cc/2026/03/18/on-violations-of-llm-review-policies/)
5. Hidden-text phrases: Murray. 2025. *PhantomLint: Principled Detection of Hidden LLM Prompts in Structured
   Documents.* arXiv preprint. [arxiv.org/abs/2508.17884](https://arxiv.org/abs/2508.17884)
6. Duplicates check: Day. 2022. *Exploratory analysis of text duplication in peer-review reveals peer-review fraud
   and paper mills.* Scientometrics 127(10), 5965–5987.
   [doi.org/10.1007/s11192-022-04504-5](https://doi.org/10.1007/s11192-022-04504-5)
7. Limit on citation requests: Wren et al. 2019. *Reviewer-coerced citation: case report, update on journal policy
   and suggestions for future prevention.* Bioinformatics 35(18), 3217–3218.
   [doi.org/10.1093/bioinformatics/btz071](https://doi.org/10.1093/bioinformatics/btz071)
8. Citations of works of the reviewers: Barnett. 2025. *Are peer reviewers influenced by their work being cited?*
   eLife 14. [doi.org/10.7554/eLife.108748](https://doi.org/10.7554/eLife.108748)
