# Examples

- Made-up submissions and public reviews to try PeerCheck on, with the reports of PeerCheck on these files.
- Every name, email address, and affiliation in these files is made up.
- The review texts come from the public test set of CoCoNUTS (MIT license).
- The review of submission 106 holds a made-up planted citation.

| Path | Holds | Shows |
|---|---|---|
| `papers/conf2027-paper1.pdf` | a clean paper | no error |
| `papers/conf2027-paper2.pdf` | A4 paper, one column, and 12 pt type | format errors |
| `papers/conf2027-paper3.pdf` | an author named in the text, a link, the acknowledgments, and the metadata | anonymity leaks |
| `papers/conf2027-paper4.pdf` | an instruction to AI reviewers in white text and in tiny text | hidden text |
| `papers/conf2027-paper5.pdf` | made-up references and a retracted one | the reference check, after `peercheck setup` and with `enabled: true` under `references` in `venue.yaml` |
| `papers/src/` | the LaTeX sources of the five papers | |
| `authors.csv` | the authors of the five papers | |
| `committee.csv` | a program committee with two conflicts | conflicts of interest |
| `reviews/` | eight reviews as the XML files of a review export, three by people, two that AI polished or extended, and three by AI | AI detection and a planted citation |
| `canaries.csv` | the key of the planted citations of the eight reviews | |
| `reviews.csv` | three reviews in one CSV file, a row per review | the CSV reader |
| `venue.yaml` | the profile of a made-up venue, a copy of `profiles/default.yaml` with its values | a venue profile |
| `reports/` | the reports of PeerCheck on these files, with the page of the live demo | the output of each command |

- The commands below write the reports to [`reports/`](reports/), which the
  [live demo](https://aalramadan.github.io/PeerCheck/) serves.

```bash
peercheck --profile examples/venue.yaml papers examples/papers --authors examples/authors.csv \
  --out examples/reports/report.xlsx
peercheck --profile examples/venue.yaml reviews examples/reviews --canaries examples/canaries.csv \
  --out examples/reports/reviews.xlsx
peercheck --profile examples/venue.yaml reviews examples/reviews.csv --out examples/reports/reviews-csv.xlsx
peercheck --profile examples/venue.yaml conflicts --authors examples/authors.csv --pc examples/committee.csv \
  --out examples/reports/conflicts.xlsx
```
