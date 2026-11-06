# Samples

Made-up submissions and public reviews to try PeerCheck on. Every name, email address, and affiliation in these
files is made up.

| Path | Holds | Shows |
|---|---|---|
| `papers/conf2027-paper1.pdf` | a clean paper | no error |
| `papers/conf2027-paper2.pdf` | A4 paper, one column, and 12 pt type | format errors |
| `papers/conf2027-paper3.pdf` | an author named in the text, a link, the acknowledgments, and the metadata | anonymity leaks |
| `papers/conf2027-paper4.pdf` | an instruction to AI reviewers in white text and in tiny text | hidden text |
| `papers/conf2027-paper5.pdf` | made-up references and a retracted one | the reference check, after `peercheck setup references` |
| `papers/src/` | the LaTeX sources of the five papers | |
| `authors.csv` | the authors of the five papers | |
| `committee.csv` | a program committee with two conflicts | conflicts of interest |
| `reviews/` | eight reviews as EasyChair XML, three by people, two that AI polished or extended, and three by AI | AI detection and a planted citation |
| `canaries.csv` | the key of the planted citations of the eight reviews | |
| `hotcrp-reviews.csv` | three reviews as a HotCRP export | the HotCRP reader |
| `venue.yaml` | the profile of a made-up venue, with the rules of the default profile | a venue profile |

```bash
peercheck --profile samples/venue.yaml papers samples/papers --authors samples/authors.csv \
  --checks layout,sigsoft,hidden-text --html report.html
peercheck --profile samples/venue.yaml reviews samples/reviews --canaries samples/canaries.csv --html reviews.html
peercheck --profile samples/venue.yaml reviews samples/hotcrp-reviews.csv --html hotcrp.html
peercheck --profile samples/venue.yaml conflicts --authors samples/authors.csv --pc samples/committee.csv
```

The review texts come from the public test set of CoCoNUTS (MIT license). The review of submission 106 holds a
made-up planted citation.
