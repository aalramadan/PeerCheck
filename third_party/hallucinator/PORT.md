# Hallucinator in PeerCheck

PeerCheck runs Hallucinator, the reference checker of Stringhini and Blackburn, for its reference check
(`peercheck/checks/references.py`). The program chairs of ACSAC 2025 and ICWSM 2026 ran this tool. PeerCheck
calls the unchanged command-line binary and changes no file of the tool.

## Version and license

- The repository is <https://github.com/gianlucasb/hallucinator>.
- PeerCheck uses `hallucinator-cli 0.2.4` of release v0.2.4, published on 2026-09-23.
- The license is AGPL-3.0-or-later, as `Cargo.toml` of the release states. PeerCheck itself uses GPL-3.0.
- PeerCheck holds no copy of the binary or the source. `install_tools()` downloads the CLI archive of the
  user's platform from the release at install time.

## Checksums

`install_tools()` accepts an archive only if its SHA-256 equals the value pinned in `ASSETS` of
`references.py`. The values come from `sha256.sum` of the release and agree with the `.sha256` file beside
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

`install_tools(cache)` fills `$XDG_CACHE_HOME/peercheck` or `~/.cache/peercheck`.

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

## Entity rewrite of the DBLP dump

The DBLP dump writes characters such as é through the named entities of dblp.dtd, such as `&eacute;`. The
DBLP builder of Hallucinator 0.2.4 unescapes text with quick-xml, which knows only the five entities of XML
itself. It drops each text node whose unescaping fails (`hallucinator-dblp/src/xml_parser.rs`). A work whose
title holds such an entity is then missing from the database. An author with such a name is missing from
every author list. Built from the unchanged dump of 2026-10-31, the database held 8,674,397 publications and
4,050,048 authors in 2,838,953,984 bytes. No author name in it held a letter outside ASCII. The real paper
"DéjàVu: A Map of Code Duplicates on GitHub" (OOPSLA 2017) came out as not found.

`numeric_entities()` in `references.py` therefore copies the dump with each named entity written as the
numeric reference of its character, such as `&#233;`. Quick-xml reads numeric references. The rewrite takes
each code point from the HTML entity table of the Python standard library. That table holds all 65 entities
of dblp.dtd with the same code points. The five entities of XML and unknown names stay as written. With the
rewrite, the database holds 137,553 more publications and 281,366 more authors. Of its author names,
248,060 hold a letter outside ASCII. The DéjàVu paper is found in DBLP. The issue belongs upstream. A
release of the tool that fixes the builder makes the rewrite unnecessary.

## How PeerCheck calls the tool

For each PDF, PeerCheck runs the following command.

```text
hallucinator-cli check --config <run>/references/hallucinator.toml --no-color --no-searxng
    --json <run>/references/paper-<id>.json --output <run>/references/paper-<id>.log
    --disable-dbs <list> --dblp-offline <cache>/hallucinator/dblp.db [further offline databases] <pdf>
```

- The empty configuration file keeps the user's own Hallucinator configuration out of the run.
- The process runs in `<run>/references` with a bare environment. `HOME` points to that folder. API keys
  pass only with `online_titles`. Proxy variables pass only with `online` or `online_titles`.
- The online sources of Hallucinator 0.2.4 are CrossRef, arXiv, DBLP, Semantic Scholar, ACL Anthology,
  Europe PMC, PubMed, DOI, OpenAlex, GovInfo, PatentsView, Standards, Open Library, and SSRN.
  `--disable-dbs` lists each one that the mode does not allow. A source with an offline database stays
  enabled, since the offline database replaces its online counterpart.
- `--no-searxng` keeps the web search off. PeerCheck never passes `--url-match`, the live check of URLs and
  of the Wayback Machine.
- Offline mode, the default, allows no online source. The debug log of a run on the sample paper holds DBLP
  queries only.
- With `online`, the DOI source is allowed. It requests `https://doi.org/<DOI>`, which forwards to the
  registration agency. For each reference that stays unverified and carries an arXiv ID, PeerCheck then
  writes a .bib file with the title, the authors, and the arXiv ID and runs the CLI on that file with the
  arXiv source alone. For a reference with an arXiv ID, that source requests `id_list=<ID>` from
  export.arxiv.org and never searches by title.
- With `online_titles`, every source is allowed.
- PeerCheck reads `original_number`, `title`, `raw_citation`, `status`, `source`, `ref_authors`,
  `found_authors`, `failed_dbs`, `doi_info`, `arxiv_info`, and `db_results` of each reference of the JSON
  report. A run that exits with a code other than 0 becomes a `references.error` finding with the last line
  of standard error. A run that writes no JSON report extracted no references.
- Hallucinator reads retractions from the answers of CrossRef, a source that offline mode disables.
  PeerCheck matches the DOIs of the references against the Retraction Watch CSV instead
  (`peercheck/retractions.py`).

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

## Changes to the tool

PeerCheck changes no file of the tool. The entity rewrite of the input dump is the only change on the side
of PeerCheck.
