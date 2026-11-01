# PeerCheck port of the ACM SIGSOFT Submission Checker

This folder holds the Maven project of the ACM SIGSOFT Submission Checker, revised into the whole-paper anonymity scan of PeerCheck.
The upstream project is <https://github.com/acmsigsoft/submission-checker> at commit `3ffa1ebbb772c9647eeab569c8119429844eb01c` (release v0.4.3, 2021-12-11), built by Arie van Deursen and Tao Xie for ICSE 2021 under the Apache License 2.0 in `LICENSE`.
The original is release v0.4.3 of `github.com/acmsigsoft/submission-checker` at commit `3ffa1eb`.
Every modified upstream file names the port in its license header, as section 4 of the license asks.

## Build and run

```bash
mvn package    # JDK 11 or later with Maven 3.9; runs the JUnit tests
cp target/submission-checker-0.4.3-peercheck.1-jar-with-dependencies.jar ../../peercheck/vendor/submission-checker/submission-checker.jar
java -jar ../../peercheck/vendor/submission-checker/submission-checker.jar --json --id-pattern '_paper_(\d+)\.pdf$' \
  --allowed-hosts anonymous.4open.science,zenodo.org,figshare.com,osf.io,doi.org --flag-acknowledgments \
  --meta authors.csv submissions/
```

The port was built with Eclipse Temurin 21.0.13 and Maven 3.9.16.
The labels A5 to A27 and E9 to E16 below number the defects of a code audit and the notes of a tooling survey made for this revision.

## Changes

### 1. Placeholder names and emails match whole words only (A16)

- Upstream treated a metadata author or a page-1 email as anonymous whenever it held a placeholder string anywhere, as `nn` in Anna or Jennifer and `doe` in Doerr.
- `PdfChecker.blindedIdentity` now splits the text into words, drops trailing digits from each word, and calls the text anonymous only if a whole word is a placeholder.
- The placeholder words are the upstream list (`anonymous`, `anon`, `anonymized`, `doe`, `blinded`, `nn`, `nobody`, `none`, `email`, `firstname`, `lastname`, `xyz`, `xxx`, `author`, `example`, `domain`, `address`, `blind`, `review`) with `authors`, the other spelling of `anonymized`, and runs of three or more x added. The whole address `permissions@acm.org` stays a placeholder.
- `PdfChecker.findEmails` now returns the first email on page 1 that is no placeholder. Upstream stopped at the first email found, even when that email was a placeholder.
- Tests are in `PlaceholderIdentityTest`. With the upstream test put back, 11 of its 21 cases fail.

### 2. Paper IDs come from `--id-pattern` (A17)

- The new option `--id-pattern <regex>` takes a regular expression with exactly one group that holds the paper ID. The default is the upstream `-paper(\d+)`.
- The pattern ignores case, like `Profile.paper_id` of PeerCheck. The first match counts.
- A numeric ID is compared as a number. Thus `CONF_2026_paper_0024.pdf` matches the CSV row of paper 24.
- A pattern that does not compile or that has another number of groups is an argument error.
- The code is in `MetaData` (`compileIdPattern`, `paperId`, `numericId`, `setIdPattern`, and `forFile`). Tests are in `PaperIdPatternTest`. With the upstream file name parsing put back, two of its six cases fail.

### 3. Whole-paper identity scan with `--meta` (A18, E15, E16)

- Upstream compared the author CSV with the text of page 1 only. With `--meta`, the scan now reads every page and the places listed below.
  - All string entries of the document information dictionary.
  - The text values and attribute values of the XMP packet of the document.
  - For each form XObject that the page resources reach, the string entries of `/PTEX.InfoDict`, the path in `/PTEX.FileName`, and the XMP packet of the form. The path is read a second time with `.`, `_`, `/`, `\`, and `-` as spaces, to match a folder such as `anna_lindqvist`.
  - For each annotation, the URI of a link, the `/Contents` text, and the `/T` author of a markup annotation.
- `FoldedText` folds case and accents (Unicode decomposition without marks, plus ø, ł, æ, œ, ß, đ, ð, þ, and ı), drops the spacing accents that old TeX fonts produce, reduces each run of white space, and joins a word that a line break hyphenated. Each folded character keeps its place in the original text. Every issue quotes the original words, with each accent composed with its letter.
- `IdentityScanner` matches each author of the paper.
  - Names match as whole words in the forms "First Last", "Last, First", "Last, F.", and "F. Last". The first form allows a middle initial. The initial form allows more initials, as in "A. M. Lindqvist". A first name of several words also matches by its first word alone.
  - LaTeX accent commands in a CSV name are dropped. Thus `K{\"a}stner` matches "Kästner". The upstream test `testLatexMetaData` now expects that match.
  - Emails match as whole addresses, also inside a group of local parts such as `{anna, bob}@kth.se`.
  - Affiliations come from the optional `affiliation` column and match as whole phrases. The values `n/a`, `na`, `none`, `unknown`, and `-` are skipped.
- A match on a page gives `possibly-identity-revealing-data`, the upstream code, with the matched text and its page. A match in another place adds the place in parentheses, such as `Anna Lindqvist (XMP metadata)`. Its page is the page of the figure or annotation and null for document-level metadata.
- A match after the REFERENCES heading gets the new code `identity-data-in-references`. Double-anonymous rules allow a self-citation in the third person, while a reader may still infer the authors from the reference list.
- Each distinct match is reported once per page and place. A paper without CSV rows gets a line on the standard error stream.
- The CSV is read as UTF-8 with or without a byte order mark. Its header names ignore case. A missing column among `paper`, `title`, `first`, `last`, and `email` is an argument error.
- The metadata author check `possibly-author-revealing-meta-data` also reads the creators of the XMP packet and the Author of each figure in `/PTEX.InfoDict`, each with the placeholder test of change 1. This part runs without `--meta`, since a name in an author field needs no author list to count.
- `PdfDocument` extracts the text of each page once. A page whose text cannot be extracted reads as empty and is named in the error of the result.
- Tests are in `FoldedTextTest`, `IdentityScannerTest`, `WholePaperScanTest`, and `PdfCheckerTest`.

### 4. Link check with `--allowed-hosts`

- The link check always runs. The option `--allowed-hosts` takes a comma-separated list of hosts whose links never count. A host also allows its subdomains. A scheme or a path in the list is ignored.
- Links come from link annotations and from the page text (`http://`, `https://`, `www.`, or a host followed by a path). A text link that an annotation on the same page extends is skipped, since a line break cut the text.
- A link becomes `identity-link` with the detail `<link> (<kind>)` and the first page it appears on, once per link. The three kinds follow.
  - A code host account is a link to github.com, gist.github.com, raw.githubusercontent.com, gitlab.com, or bitbucket.org with an account in its first path segment, or a page of a name on github.io, gitlab.io, or bitbucket.io. Pages of the host itself, such as `/features`, do not count.
  - A personal page is a link with a `~user` segment, a host whose first label is a word such as `people`, `homes`, or `staff`, a path segment such as `people`, `staff`, `faculty`, `members`, or `profile` followed by a name, or a profile on ORCID, about.me, Twitter, X, Google Sites, Google Scholar, DBLP, LinkedIn, ResearchGate, or Semantic Scholar.
  - A cloud drive share is a link with a path on Google Drive or Docs, Dropbox, OneDrive, SharePoint, Box, iCloud, MEGA, or WeTransfer.
- A link to the repository of a third-party tool also counts, since its owner is a user or an organization on a code host.
- The checker never fetches a link. The code is in `LinkClassifier`. Tests are in `LinkClassifierTest` and `IdentityLinkTest`.

### 5. Acknowledgments with `--flag-acknowledgments`

- With the new option, a heading Acknowledgment, Acknowledgments, Acknowledgement, or Acknowledgements becomes `acknowledgments-present` with the heading and its page.
- The heading may carry a section number such as `VIII.` or `7`. It may stand alone on its line or open a paragraph with a period or a colon.
- The anonymous mode of acmart hides the `acks` environment. A paper built in that mode therefore shows no heading.
- Tests are in `AcknowledgmentsTest`.

### 6. Self-citation wording beyond the upstream pattern (E9)

- `PdfChecker.previousWork` now searches the folded text of all pages and reports every phrase with its page. The phrase is quoted on one line, where upstream kept the line break inside the phrase (A6).
- The forms are "our" or "my" with previous, earlier, prior, recent, or past and work, paper, study, tool, approach, or publication (one more word may come between), "we previously" with its verb, "in our [12]", "In [12], we", and "In previous work [5], we". A citation that follows is quoted with the phrase.
- A citation is a numeric bracket with spaces, lists, or ranges such as `[3, 4]` or `[5–7]`. An author-year citation in parentheses counts as well.
- The upstream nouns result and finding still need a citation, since "our previous results" often points back into the paper itself.
- Tests are in `PreviousWorkTest` and `PdfCheckerTest.testPreviousWork`.

### 7. Libraries without known advisories (A27)

- PDFBox moves from 2.0.24 to 2.0.37, the newest 2.0 release on Maven Central on 2026-11-01. commons-text moves from 1.9 to 1.15.0, which also brings commons-lang3 3.20.0. Release 1.10.0 fixed CVE-2022-42889 (GHSA-599f-7c49-w659).
- The OSV batch query of 2026-11-01 lists no advisory for any library in the jar (pdfbox and fontbox 2.0.37, commons-text 1.15.0, commons-lang3 3.20.0, commons-cli 1.5.0, commons-csv 1.9.0, commons-logging 1.2, and annotations 23.0.0).
- `maven.compiler.release` 11 replaces the source and target settings. The class files stay at Java 11 (major version 55). The compiler also checks every call against the Java 11 API. The compiler plugin is pinned to 3.14.1.
- Gson 2.15.0 joins at test scope to parse the JSON output in the tests. The jar does not bundle Gson.
- The upstream `distributionManagement` section for GitHub Packages is removed, since the port is never published there. The version is `0.4.3-peercheck.1`.
- Tests are in `DependencyVersionsTest`.

### 8. JSON output with `--json` (A5, A6)

- With the new option, each PDF gives one JSON object on one line of the standard output, with the keys `file`, `paper`, `title`, `pages`, `issues`, and `error`. Each issue holds `code`, `detail`, and `page`.
- `file` is the path as given. `paper` is the number from `--id-pattern`, or null if the name does not match. Every character outside printable ASCII is escaped. The line therefore survives any console encoding.
- A PDF that fails to open, such as a damaged or password-protected file, gives the exception name and message in `error`, 0 pages, a null title, and no issues.
- A check that throws no longer stops the other checks of the paper. Its failure is added to `error`.
- File and folder arguments accept `.pdf` in any case, where upstream skipped `.PDF` (A5).
- Without `--json`, the upstream text line stays. A code may now appear once per page or match. A PDF that fails to open is reported on the standard error stream without a stack trace.
- `--json` together with `--showtext` is an argument error, since page text would break the JSON lines.
- Tests are in `JsonOutputTest`.

### 9. Exit status

- The exit status is 2 if the arguments are wrong and 0 otherwise. Upstream always ended with 0.
- Wrong arguments are an unknown option, a page limit that is no number or below 1 for the main text or below 0 for references, a style other than ACM or IEEE (case is ignored), a wrong `--id-pattern` or `--showtext` value, a missing or incomplete author CSV, no file argument, a file argument that is no existing PDF or folder, and `--json` with `--showtext`.
- Every argument is checked before the first paper. `BatchChecker.run` returns the status. `main` exits only with a status other than 0. A test can therefore call `main` without ending its run.
- Tests are in `ExitCodeTest`.

### Fixes the revisions needed

- `PdfDocument.close` no longer throws a `NullPointerException` after a failed load.
- `PdfChecker.stripNonNumberedHeader` no longer throws when page 3 has no line break.
- The test resources of upstream stay unchanged.
