# ICSME Submission Checker Suite

This script automates the compliance checks for the ICSME conference submissions. It features an interactive menu that allows you to run a dual-pass formatting inspection or an AI content detection scan.

It uses **Banal** (for formatting analysis) and the **Sigsoft Submission Checker** (for IEEE style violations and anonymity analysis). It combines all findings into a single Excel report and flags papers that violate strict formatting rules.

It uses **CoCoDet** to detect AI-generated content in peer-reviews.

> This script is specifically configured for IEEE formatting standards, ICSME 2026 Research Track guidelines, and EasyChair exports. All rule checks, page limits, and layout constraints are strictly aligned with these requirements.

## Prerequisites

1. You must have **Python 3.12.x** installed on your system before creating the virtual environment as the model was tested on this specific version. You also need the Python development headers and build tools installed so PyTorch can compile its GPU optimizations.
* **Ubuntu / Debian:** `sudo apt install python3.12 python3.12-venv python3.12-dev build-essential`
* **Fedora / RHEL:** `sudo dnf install python3.12 python3.12-devel gcc gcc-c++`
* **Arch Linux:** `yay -S python312 base-devel`
* **macOS:** `brew install python@3.12`


2.  **Create a virtual environment:**
```bash
# Create the virtual environment using Python 3.12 (This version is needed for CoCoDet)
python3.12 -m venv checkers_env

# Activate the environment
source checkers_env/bin/activate
```

3. **Install these dependencies:**
```bash
pip install openpyxl huggingface_hub
```

4. **Install all necessary dependencies for Banal, Sigsoft, and CoCoDet by referring to their respective README files.**

## Project Structure
```text
/ICSME_Submission_Checker_Suite/
│── Banal/
│   └── banal.txt
│── sigsoft/
│   └── sigsoft.jar
│── cocodet/
│   ├── model/                  # Contains CoCoDet.bin (Initially empty. CoCoDet.bin is downloaded on first run)
│   ├── infer.py                # CoCoDet inference script
│   └── requirements.txt
│── run.py                      # Main execution script
```
You can configure the input/output directories at the top of the `run.py`:

## Running the Suite
Run the main script from your terminal:
```bash
python run.py
```
You will be prompted with an interactive menu to choose between:
1. Running Formatting Checkers
2. Running AI Content Detection

## `report.xlsx` Report Column Reference
* **Total Pages:** The overall page count.
* **Body Pages:** The number of pages containing main research content (Total - Pure References).
* **Reference Pages:** The count of pages containing bibliography, including mixed content pages where references begin.
* **Blank Pages:** Count of empty pages.
* **Appendix Pages:** Count of pages explicitly identified as appendices.
* **Figure Pages:** Count of pages dominated by graphics/tables (detected via low character counts and 0 columns).
* **Words / Characters:** Total counts of words and characters.
* **Body Font / Reference Font:** Primary font sizes in points.
* **Line Spacing:** The vertical leading (spacing) between lines of text.
* **Margins (Top, Right, Bottom, Left):** Detected margins.
* **Columns:** Detected vertical text columns.
* **Paper Size (HxW):** Physical page dimensions in points.
* **Page Number Position:** Detected location of page numbers.
* **Check Result:** The final status (**PASS** or **REJECT**) based on a set of rule-checks (defined below)

## Rule-Checks Performed
* **Strict Page Limits:** Enforces a maximum of 10 body pages and a strict limit of 2 reference pages (max 12 total pages).
* **Paper Size Verification:** Strictly enforces standard US Letter (792x612 pts) and rejects A4 or custom-cropped sizes.
* **Margin Enforcement:** Checks for standard IEEE margins [52, 48, 72, 48] with an 18pt and (25pt for bottom) tolerance to catch manual layout manipulation.
* **Font & Column Rules:** Flags 1-column drafts, tiny reference fonts (< 8pt), and oversized body fonts (> 10.5pt).
* **Structural Integrity:** Detects missing mandatory headers (Abstract, Introduction, Conclusion), blank pages, and leftover page numbers.
* **Anonymity Verification:** Detects metadata for author names, affiliations, and any identifying links that violates strict double-blind compliance.
