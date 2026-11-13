# Hallucinator in PeerCheck

PeerCheck runs Hallucinator, the reference checker of Stringhini and Blackburn, for its reference check
(`src/papers/references.py`). ACSAC 2025 and ICWSM 2026 ran this tool. PeerCheck
calls the unchanged command-line binary and changes no file of the tool.

## Version and license

- The repository is <https://github.com/gianlucasb/hallucinator>.
- PeerCheck uses `hallucinator-cli 0.2.4` of release v0.2.4, published on 2026-09-23.
- The license is AGPL-3.0-or-later, as `Cargo.toml` of the release states. PeerCheck itself uses GPL-3.0.
- `hallucinator-rs/` and `LICENSE` here are a copy of the Rust source of release v0.2.4, kept for reference. The
  README of the release stays out. PeerCheck runs no file of this copy. `install_tools()` of
  `src/papers/reference_setup.py` downloads the CLI archive of the user's platform from the release at install
  time.

## Checksums

`install_tools()` accepts an archive only if its SHA-256 equals the value pinned in `ASSETS` of
`reference_setup.py`. The values come from `sha256.sum` of the release and agree with the `.sha256` file beside
each archive.

| Archive | SHA-256 |
|---|---|
| hallucinator-cli-x86_64-unknown-linux-gnu.tar.xz | c3ce1d4081e631151b9493c05c2777b87062ddf3a4c08391dcc6b47a8637a4bc |
| hallucinator-cli-aarch64-apple-darwin.tar.xz | a71db8cd8a2f1434f2722837729b72ab3a946c71cc5ff5aee9f10bb2f25efac4 |
| hallucinator-cli-x86_64-apple-darwin.tar.xz | 8c58e033d86fe675d26aab88ed2d079f39b863ad8cf13ada9d7de02163b6e9d8 |
| hallucinator-cli-x86_64-pc-windows-msvc.zip | d48a958c255d1b01a0ff5cf626b2f13ad969026009e8778d488833862871ba7c |
| source.tar.gz | 6d00d7615ce5b4eb82d993f875a19f7faafc43a23f7db529a462debc16fe26a5 |

The release offers no prebuilt CLI for Linux on ARM. There the binary option of the profile names a binary
built from source with `cargo build --release`.

## Files in the cache

`install_tools(cache)` fills `$XDG_CACHE_HOME/peercheck` or `~/.cache/peercheck`. `peercheck --setup` keeps each
file that the cache already holds, while `peercheck --setup --refresh` downloads every file again.

- `hallucinator/0.2.4/hallucinator-cli` is the binary taken from the archive.
- `hallucinator/dblp.db` is the offline DBLP database, an SQLite file with an FTS5 index. `install_tools`
  takes a local dblp.xml.gz or downloads the dump from the address that the tool itself uses,
  <https://dblp.uni-trier.de/xml/dblp.xml.gz>. dblp.org may answer a download with a bot check. A dump saved
  by hand or taken from Dagstuhl DROPS is therefore the reliable source. `install_tools` then writes a copy
  of the dump with numeric character references, as the next section describes. It runs
  `hallucinator-cli update-dblp <db> --from-file <copy>` on that copy. Built from the dump of 2026-10-31,
  the database holds 8,811,950 publications and 4,331,414 authors in 2,954,477,568 bytes. The rewrite took
  65 seconds. The whole install took 374 seconds.
- `retraction_watch.csv` holds the Retraction Watch data that Crossref publishes at
  <https://gitlab.com/crossref/retraction-watch-data>.
- `dblp/dblp.xml.gz` and `dblp/dblp.dtd` are the DBLP dump and its DTD, which the conflict check reads.
- `hallucinator/online-lookups.db` keeps the answers of the sources of the online run.
  `hallucinator/index-lookups.json` keeps the records that DataCite, OpenAlex, and OpenReview return for a title.
  A title with records stays for seven days and a title without one for a day.

## Entity rewrite of the DBLP dump

The DBLP dump writes characters such as é through the named entities of dblp.dtd, such as `&eacute;`. The
DBLP builder of Hallucinator 0.2.4 unescapes text with quick-xml, which knows only the five entities of XML
itself. It drops each text node whose unescaping fails (`hallucinator-dblp/src/xml_parser.rs`). A work whose
title holds such an entity is then missing from the database. An author with such a name is missing from
every author list. Built from the unchanged dump of 2026-10-31, the database held 8,674,397 publications and
4,050,048 authors in 2,838,953,984 bytes. No author name in it held a letter outside ASCII. The real paper
"DéjàVu: A Map of Code Duplicates on GitHub" (OOPSLA 2017) came out as not found.

`numeric_entities()` in `reference_setup.py` therefore copies the dump with each named entity written as the
numeric reference of its character, such as `&#233;`. Quick-xml reads numeric references. The rewrite takes
each code point from the HTML entity table of the Python standard library. That table holds all 65 entities
of dblp.dtd with the same code points. The five entities of XML and unknown names stay as written. With the
rewrite, the database holds 137,553 more publications and 281,366 more authors. Of its author names,
248,060 hold a letter outside ASCII. The DéjàVu paper is found in DBLP. The issue belongs upstream. A
release of the tool that fixes the builder makes the rewrite unnecessary.

## How PeerCheck calls the tool

The reader of Hallucinator may cut an entry at a column or a page break. It also ends the list at a line that
starts like the heading of an appendix. PeerCheck therefore reads the reference list of each PDF
(`src/papers/reference_list.py`) and passes the list to the tool as a PDF with one line per entry. Where
PeerCheck reads no list from a PDF, the tool receives the PDF itself. For each list, PeerCheck runs the following
command, on up to eight papers at the same time.

```text
hallucinator-cli check --config <run>/references/hallucinator.toml --no-color --no-searxng
    --json <run>/references/paper-<id>.json --output <run>/references/paper-<id>.log
    --disable-dbs <list> --dblp-offline <cache>/hallucinator/dblp.db [further offline databases]
    <run>/references/paper-<id>-list.pdf
```

- The empty configuration file keeps the user's own Hallucinator configuration out of the run.
- The process runs in `<run>/references` with a bare environment. `HOME` points to that folder. No API key of
  the user reaches a run. Only the online run receives `CROSSREF_MAILTO` and the proxy variables.
- The online sources of Hallucinator 0.2.4 are CrossRef, arXiv, DBLP, Semantic Scholar, ACL Anthology,
  Europe PMC, PubMed, DOI, OpenAlex, GovInfo, PatentsView, Standards, Open Library, and SSRN.
  `--disable-dbs` lists each one that a run does not ask. A source with an offline database stays
  enabled, since the offline database replaces its online counterpart.
- `--no-searxng` keeps the web search off. PeerCheck never passes `--url-match`, the live check of URLs and
  of the Wayback Machine. Without that option, Hallucinator passes over a reference that the local databases
  lack and that gives a web address outside the sites of publishers and archives.
- The run on a list asks no online source. The debug log of a run on the sample paper holds DBLP queries
  only.
- With `online_titles`, one further run looks up the articles and the papers of all submissions that stay
  open. PeerCheck writes their titles and authors to `online.bib` and runs the CLI on that file with
  `--cache-path <cache>/hallucinator/online-lookups.db`, which keeps the answers of the sources. The run asks
  CrossRef, PubMed, and the ACL Anthology. It stops after the `timeout` of the template plus ten seconds for each
  of its references. An answer counts only under nearly the title that PeerCheck sent, since the tool numbers only
  the entries of `online.bib` that it could parse.
- CrossRef answers one title per second (`rate_limit.rs`). With an address in `CROSSREF_MAILTO`, the rate is
  three titles per second. More workers do not shorten the run. With 16 workers in place of the default four,
  the same lookups took 187.6 seconds, compared with 154.9 seconds.
- PeerCheck reads `original_number`, `title`, `raw_citation`, `status`, `source`, `ref_authors`,
  `found_authors`, `failed_dbs`, and `db_results` of each reference of the JSON report, with the DOI of
  `doi_info` and the arXiv ID of `arxiv_info`. A run that exits with a code other than 0 becomes a
  `references.error` finding with the last line of standard error. A run that writes no JSON report
  extracted no references.
- Hallucinator reads retractions from the answers of CrossRef, a source that the run on a list never asks.
  PeerCheck matches the DOIs of the references against the Retraction Watch CSV instead
  (`src/papers/retraction_watch.py`).

## Sources that stay off

Eleven of the 14 online sources stay off in every run. The other three answer the online run, namely CrossRef,
PubMed, and the ACL Anthology. The reason for each of the eleven follows.

- DOI. `validate_doi` (`doi.rs`) reports a DOI as invalid after every failed request, such as a timeout or a
  refused request, and the DOI source then counts the DOI as the DOI of another work (`db/doi_resolver.rs`,
  `pool.rs`). In a run on 32 public arXiv papers, seven references with a correct DOI came out this way.
- arXiv. Hallucinator asks arXiv faster than arXiv allows and waits ten seconds after each refused request.
- OpenAlex. Each search counts against a daily budget of the caller, while the source would search for every
  reference. PeerCheck asks OpenAlex only for the references that the check would otherwise report.
- Europe PMC. The source answers slowly and holds what PubMed and CrossRef hold.
- Semantic Scholar. Without an API key, the source answers about 100 requests in five minutes
  (`rate_limit.rs`), while no key of the user reaches a run.
- DBLP. The offline database replaces the online source.
- Open Library, GovInfo, PatentsView, Standards, and SSRN. These sources hold books, laws, patents, standards,
  and preprints of other fields, while the check reports only articles and papers.

## Lookups of PeerCheck beside the tool

PeerCheck adds two kinds of lookups to the runs of the tool. First, it compares each reference that the local
run leaves open with the DBLP records whose title the entry holds (`_confirmed_in_dblp` in `references.py`). The
tool looks up only the title that it reads from an entry and may read a part of the venue into that title.
PeerCheck therefore searches the DBLP copy for the records that hold two of the six rarest words of that title.
Where no such record bears the title, as for a title read from another part of the entry, the search uses two of
the 16 rarest words among all words of the entry. Second, `src/papers/open_indexes.py` asks five services. The lookups by identifier come before the online run
of the tool, while the lookups by title come after that run. A reference that one lookup confirms goes to no
later lookup.

- DataCite and Crossref return the records of the DOIs and the arXiv IDs, 50 per request. DataCite holds
  every arXiv preprint under the DOI 10.48550/arXiv.<ID>. A record of another work goes into the report.
- doi.org names the registration agency of each DOI that neither registry holds. A DOI of another agency,
  such as ISTIC or JaLC, confirms its reference, since the record of such a DOI is often in another script.
- DataCite receives the title of each open reference whose title has four words or more. OpenAlex receives the
  title of each article or paper that the check would otherwise report, first whole and then in two halves.
  OpenReview receives those of this year and the year before, since venues of machine learning show their papers
  on OpenReview before any database.
- An index receives four requests at a time. It receives no further request in a run once three requests in a
  row stay without an answer or once five seconds per title of the run have passed. A request that a service
  turns away with status 429 or 503 goes out once more after the wait that the service names, up to 60 seconds.
- A hidden entry, such as one by Anonymous or with its details left out for the review, goes to no online source
  and counts as not looked up.
- A warning rests on the answers of DBLP, CrossRef, and OpenAlex. A reference whose lookup failed at one of the
  three or at the registry of its DOI counts as not looked up, never as not found. A later run repeats the lookup.
- A reference that the online run passes over, since its title has fewer than four words for the tool, counts
  as not looked up as well. Its note is the note on such entries, since a later run passes over the reference
  again.

## Matching rules of the tool

These rules come from `hallucinator-core` 0.2.4 (`matching.rs`, `authors.rs`).

- Titles are reduced to lowercase ASCII letters and digits and match at a fuzzy ratio of at least 0.95. A
  title of at least 30 characters also matches the start of a longer title. The exception is a pair where
  only one title carries a subtitle after a question mark or an exclamation mark and the shorter title
  covers less than 70% of the longer one.
- Authors match when the two lists share at least one name, compared as first initial and surname, or as
  surname alone when the reference gives surnames only. An organization as author skips the comparison.
  For a source with complete author lists, one cited author missing from the record counts as a mismatch.
  DBLP and OpenAlex truncate author lists. A mismatch there therefore needs at least three missing authors
  that make up more than 25% of the cited authors.

## Comparison of a record with a reference

The tool accepts a record once it names one cited author. PeerCheck therefore compares each record again
(`src/papers/reference_match.py`). A record confirms a reference when it bears the title of the entry and names
the cited authors.

- A reference bears the title of a record when the title that the tool read is nearly the title of the record,
  at a ratio of at least 95 of 100 over their letters and digits. It also bears the title when the title of the
  record stands in the entry as a whole field, with or without its subtitle. The comparison ignores case and
  accents.
- A record names the cited authors in three cases. First, it names at least half of the cited authors.
  Second, it names only cited authors, as a record with a cut author list does. Third, it names the first author
  of an entry that goes on with et al. A record without an author to compare counts as a record of the cited
  authors. The same holds for every record of an entry that names a group and no person.
- A record names a cited author by the family name. A record with the cited family name as another word of a
  name, such as a name with the family name first or with two family names, names that author only when a cited
  initial opens one more word of that name or when the entry gives no initial. A given name of a cited author
  names no author of a record.
- A record under nearly the cited title that names other authors gives `references.author-mismatch`, once DBLP,
  CrossRef, OpenAlex, and the registry of the DOI answered. The record of a DOI or an arXiv ID that names another
  work gives `references.identifier-mismatch`. Where the reference also gets `references.not-found`, that warning
  names the other work.

## Options under `checks.references` of the template

- `online` (default true) looks up references online beside the local databases. With false, PeerCheck sends
  nothing.
- `online_titles` (default true) sends the titles of the references that the local databases do not confirm to
  the online run and to the title lookups. The title of a fabricated reference is text of the submission.
  Organizers who keep that text in house therefore set this option to false. The check then sends only DOIs and
  arXiv IDs.
- `online` and `online_titles` take true or false alone. Any other value gives `references.error`, since the
  word false in quotes would turn the lookups on.
- `timeout` (default 600) gives the seconds before a run of the tool on one PDF stops.
- `local_corpus` (default none) names a local corpus of Hallucinator, such as references marked safe in earlier
  reports.
- `cache` (default `$XDG_CACHE_HOME/peercheck` or `~/.cache/peercheck`) names the folder of `install_tools`.
- `binary`, `dblp_db`, and `retraction_csv` name files that replace those of the cache.
- `acl_db`, `arxiv_db`, and `openalex_db` (default none) name further offline databases built with
  `hallucinator-cli update-acl`, `update-arxiv`, or `update-openalex`. Each one joins the lookups of the local
  run.

## Findings

- `references.not-found` (warning) reports an article or a paper that no source holds, with the sources that
  answered. With online lookups, the warning needs an answer of DBLP, CrossRef, and OpenAlex each. With
  `online: false`, the warning rests on the local DBLP copy alone.
- `references.author-mismatch` (warning) names a record under the title of an article or a paper with other
  authors.
- `references.identifier-mismatch` (warning) names a DOI or an arXiv ID whose record is another work.
- `references.retracted` (warning) gives the nature and the date of a retraction notice.
- `references.unconfirmed` (info) lists the references not found that call for no warning, such as a book, a
  report, a web page, or a dataset.
- `references.unchecked` (info) lists the references not looked up, since a lookup failed or since the entry
  hides a work for the review, names a web page, or bears no title of four words or more.
- `references.summary` (info) gives the counts.
- `references.error` (warning) reports a check or an online run that failed.

## Changes to the tool

PeerCheck changes no file of the tool. On the side of PeerCheck, three steps shape each run. PeerCheck rewrites
the entities of the input dump, passes each reference list to the tool as a PDF with one line per entry, and
keeps eleven online sources off.
