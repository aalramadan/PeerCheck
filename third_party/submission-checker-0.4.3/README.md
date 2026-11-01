# SIGSOFT Submission Checker (SSC)

The SIGSOFT Submission Checker (SIGSOFT-0.4.3) (SSC) is a Java-based command-line tool designed to check conference paper submissions for formatting (ACM/IEEE styles) and double-anonymous violations. This tool uses Apache PDFBox to extract text and applies heuristic regex matching to find suspicious patterns. 

> Forked from acmsigsoft/submission-checker: https://github.com/acmsigsoft/submission-checker

## Overview

**Formatting & Limits:**
* **Page Limits:** Verifies the main text does not exceed the allowed number of pages.
* **References:** Ensures references start within the permitted range and flags any figures, tables, or appendices that appear in the references-only section.
* **Style:** Checks for general conformance to IEEE (default) or ACM styles.

**Anonymity & Identity:**
* **Metadata:** Detects embedded PDF metadata that might reveal author identities.
* **Emails:** Spots non-anonymous email addresses on the first page.
* **Wording:** Flags suspicious self-referential wording (e.g., *"our previous paper [3]"*).
* **Name Matching:** When provided with a CSV file, it scans the paper for accidental inclusions of author names and emails.

## Prerequisites

The Submission Checker requires **Java 11 or higher**. If you plan to build the tool from source, you will also need **Apache Maven**.

To check if you already have a compatible version of Java installed, run:
`java -version`

### 1. Install Java 11+ and Maven
If you do not have Java 11 or newer installed, then install with the following based on the operating system (Use a newer version if you like):

* **Ubuntu / Debian:** `sudo apt install openjdk-11-jdk maven`
* **Fedora / RHEL:** `sudo dnf install java-11-openjdk-devel maven`
* **Arch Linux:** `sudo pacman -S jdk-openjdk maven`
* **macOS (Homebrew):** `brew install openjdk@11 maven`

### 2. Get the Tool
You have two options to install and run the tool:

**Option A: Use the pre-built `submission-checker-0.4.3-jar-with-dependencies.jar` (Recommended)**

**Option B: Build from Source**
If you prefer to compile it yourself:
1. Clone the repository.
2. Run: `mvn clean package`
3. The `.jar` will be generated in the `target/` directory.

## Author Metadata Check
The tool already scans for  author metadata (PDF properties, Emails, Certain Phrases). But, if you need strict, deterministic name matching, then you need:

### 1] CSV Metadata:
`paper,title,first,last,email`

* **`paper`**: The paper ID (e.g., `71`). **This must match the ID in the PDF file name.**
* **`title`**: The paper's title.
* **`first`**: The author's first name.
* **`last`**: The author's last name.
* **`email`**: The author's email address.

*(Note: `paper` and `email` are strictly required for the tool to function correctly).*

### 2] PDF Naming convention:
Because this tool was originally designed for ICSE (which uses HotCRP), we need the ICSME (EasyChair) submissions to match the expected formats before running the tool. The input PDFs **must** follow this exact naming structure so the tool can parse the paper ID:
`[AnyText]-paper[ID].pdf`
*(Example: `ICSME-paper71.pdf`)*

## Usage & Options

Run the tool via the command line, passing individual PDFs or an entire folder as arguments:

```bash
java -jar submission-checker-0.4.3-jar-with-dependencies.jar [options] <pdf_files_or_folder>
```

### Options
* `-s, --style <style>`: Set style in ACM or IEEE, default IEEE
* `-m, --meta <csv-file>`: `.csv` file with author meta data. One row per author. Columns used: `paper,title,first,last,email`
* `-p, --mainpages <N>`: Main text should be maximum N pages (default = 10)
* `-r, --refpages <N>`: Number of extra pages for references (default = 2)
* `-h, --help`: Show this information
* `-t, --showtext <pages>`: Show plain text of pages on stdout. `<pages>` can be nr or 'all'. Combine with `... | grep ...` to fetch custom patterns.

## Examples

**1. Check a single paper for standard ICSME limits (10 pages main + 2 pages references, IEEE style):**
```bash
java -jar submission-checker-0.4.3-jar-with-dependencies.jar -p 10 -r 2 -s IEEE ICSME-paper71.pdf
```

**2. Bulk check a folder of submissions against an author metadata CSV to find anonymity leaks:**
```bash
java -jar submission-checker-0.4.3-jar-with-dependencies.jar -p 10 -r 2 -m authors.csv ./submissions/
```

**3. Debugging / Custom Pattern Searching:**
Extract all text from page 1 of a specific paper to see how the tool is parsing the title/abstract:
```bash
java -jar submission-checker-0.4.3-jar-with-dependencies.jar -t 1 ICSME-paper71.pdf
```

**4. Search all submissions for a specific custom pattern (e.g., a GitHub link):**
Use the `-t all` flag combined with `grep` to manually hunt for URLs that might violate double-anonymous rules:
```bash
java -jar submission-checker-0.4.3-jar-with-dependencies.jar -t all ./submissions/ | grep -i "github.com"
```