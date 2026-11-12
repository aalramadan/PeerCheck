# Examples

- Made-up submissions and public reviews to try PeerCheck on, with the reports of PeerCheck on these files.
- Every name, email address, and affiliation in these files is made up.
- Reviews 101A to 108A of `reviews/reviews.csv` come from the public test set of CoCoNUTS (MIT license).
- Reviews 109A to 110C of `reviews/reviews.csv` come from the Benchmark of the main README. Four of them are official
  ICLR 2017 reviews from OpenReview under CC BY 4.0, two kept as written and two with text that a model polished.
- The review of submission 106 holds a made-up planted citation.

| Path | Holds | Shows |
|---|---|---|
| `papers/conf2027-paper1.pdf` | a clean paper | no error |
| `papers/conf2027-paper2.pdf` | A4 paper, one column, and 12 pt type | format errors |
| `papers/conf2027-paper3.pdf` | an author named in the text, a link, the acknowledgments, and the metadata | anonymity leaks |
| `papers/conf2027-paper4.pdf` | an instruction to AI reviewers in white text and in tiny text | hidden text |
| `papers/conf2027-paper5.pdf` | made-up references and a retracted one | the reference check, after `peercheck --setup` and without the `#` before `references` in `template.yaml` |
| `papers/src/` | the LaTeX sources of the five papers | |
| `authors.csv` | the authors of the five papers | |
| `committee.csv` | a program committee with two conflicts | conflicts of interest |
| `reviews/reviews.csv` | 14 reviews, a row per review. Submissions 101 to 108 have one review each, three by people, two that AI polished or extended, and three by AI. Submissions 109 and 110 are two ICLR 2017 papers with three reviews each, one by a person (A), one written by a model (B), and one by a person that a model polished (C) | AI detection, a planted citation, and the reviews file |
| `canaries.csv` | the key of the planted citations of submissions 101 to 108 | |
| `template.yaml` | the template of a made-up venue, a copy of `templates/default.yaml` with its values | a template |
| `reports/` | the reports of PeerCheck on these files, with the page of the live demo | the output of each command |

- The commands below write the reports to [`reports/`](reports/), which the
  [live demo](https://aalramadan.github.io/PeerCheck/) serves.

```bash
peercheck --template examples/template.yaml --papers examples/papers --authors examples/authors.csv \
  --out examples/reports/report.csv
peercheck --template examples/template.yaml --reviews examples/reviews/reviews.csv --canaries examples/canaries.csv \
  --out examples/reports/reviews.csv
peercheck --template examples/template.yaml --conflicts --authors examples/authors.csv --pc examples/committee.csv \
  --out examples/reports/conflicts.csv
```
