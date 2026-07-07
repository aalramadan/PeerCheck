# Banal: PDF Formatting Analyzer

Banal is a Perl script widely used by conference management systems (like HotCRP) to automatically analyze the formatting of PDF submissions. It extracts information on formatting, layout, and content statistics to make sure papers comply with submission guidelines.

> Forked from kohler/hotcrp: https://github.com/kohler/hotcrp/blob/master/src/banal

## Overview

Banal analyzes the document as a whole and breaks down specific metrics page by page. It extracts the following information:

**Document & Layout Metrics**
* **Paper Size:** The overall width and height of the document pages.
* **Text Region:** The width and height of the actual text blocks on the pages.
* **Margins:** The left, right, top, and bottom margins.
* **Columns:** The number of columns detected in the text layout.
* **Leading:** The line spacing measured in points.
* **Number Margin:** The lowest point on the page where a page number is detected.

**Font Metrics**
* **Body Font Size:** The primary font size used for the main text, measured in points.
* **Reference Font Size:** The specific font size used in the bibliography/references section, if different from the body font.

**Content & Structural Metrics**
* **Total Pages:** The overall page count of the document.
* **Page Types:** It categorizes each page into specific types based on content: `body`, `blank`, `cover`, `appendix`, `bib` (bibliography/references), or `figure`.
* **Character Count:** The total number of characters per page.
* **Word Count:** The total number of words per page and across the document.
* **Headings:** It extracts section headings from the text.
* **First Section:** It identifies the numerical start of the first main section.

## Prerequisites

To run Banal, install both `perl` and the `poppler-utils` package (which contains `pdftohtml`) based on your operating system:

* **Ubuntu / Debian:** `sudo apt install perl poppler-utils`
* **Fedora / RHEL:** `sudo dnf install perl poppler-utils`
* **Arch Linux:** `sudo pacman -S perl poppler`
* **macOS (Homebrew):** `brew install perl poppler`

## Setup

Make the script executable so it can be run directly:

1. `cp banal.txt banal`
2. `chmod +x banal`

## Usage & Options

Run Banal by specifying an output mode, optional flags, and the target PDF files:

`./banal [-report | -stats | -json] [-zoom=N] files`

### Primary Modes
* **`-report`**: Prints full formatting info for all pages. This is the default mode if no mode is specified.
* **`-stats`**: Prints formatting info condensed into one line with fields separated by tabs. This is highly useful for computing summary stats across many papers.
* **`-json`**: Prints the formatting output in JSON format.

### Additional Flags
* **`-pagenum`**: Includes page numbers and headings in the output.
* **`-no-time`**: Prevents the script from printing a timestamp in the output.
* **`-zoom=N`**: Passes a specific zoom value to the underlying `pdftohtml` tool.
* **`-max-pages=N`**: Sets a maximum number of pages to process when using JSON output.
* **`-debug-words`**: Enables debugging output for word extraction.
* **`-version`**: Reports the current version of the Banal script.

## Examples

**1. Check a single paper**

To get page-by-page breakdown of a submission:
```bash
./banal paper.pdf
```

**2. Check an entire folder of submissions (Summary Stats)**

To quickly analyze a directory full of PDFs and output a condensed, tab-separated list:
```bash
./banal -stats submissions/*.pdf
```

**3. Extract specific metrics from a folder of submissions**

Since the `-stats` mode outputs tab-separated data, you can pipe it to other command-line tools. For example, to extract just the font sizes (the 5th column) from all PDFs in a folder:
```bash
./banal -stats submissions/*.pdf | cut -f 5
```

**4. Get a JSON output**

```bash
./banal -json submissions/paper.pdf > paper_report.json
```
