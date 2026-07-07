import os
import json
import subprocess
import re
import shutil
import glob
import csv
import html
import sys
import openpyxl
from huggingface_hub import hf_hub_download

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# BANAL and SIGSOFT configurations
SUBMISSIONS_DIR = os.path.join(BASE_DIR, "submissions") # PDFs should be placed here
SUBMISSIONS_FILE = os.path.join(BASE_DIR, "submissions.xlsx") # Metadata
REPORT_FILE = os.path.join(BASE_DIR, "report.xlsx") # Output report with checker results
BANAL_DIR = os.path.join(BASE_DIR, "banal", "banal.txt")
SIGSOFT_DIR = os.path.join(BASE_DIR, "sigsoft", "sigsoft.jar")
ID_COLUMN_HEADER = "#"
TARGET_STYLE = "IEEE"

# CoCoNUTS configurations
COCODET_DIR = os.path.join(BASE_DIR, "cocodet")
MODEL_FILE = os.path.join(COCODET_DIR, "model", "CoCoDet.bin")
SCRIPT_FILE = os.path.join(COCODET_DIR, "cocodet.py")
REVIEWS_DIR = os.path.join(BASE_DIR, "reviews")
REVIEWS_FILE = os.path.join(BASE_DIR, "reviews", "reviews.jsonl")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
REVIEWS_REPORT_FILE = os.path.join(RESULTS_DIR, "report.jsonl")
REVIEWS_CSV_FILE = os.path.join(RESULTS_DIR, "ai_detection_report.csv")

# Extracts the ID from the filename based on the pattern: ICSME_2026_paper_0108.pdf -> 108
def extract_paper_id(filename):
    match = re.search(r'_paper_(\d+)\.pdf$', filename, re.IGNORECASE)
    if match: 
        return int(match.group(1))
    return None

# Prepares the review data by parsing XML files and extracting relevant text for CoCoDet analysis
# Already skips non-review fields (Overall evaluation, Reviewer's confidence, and IEEE Policy) as they use <score> instead of <text> and normalizes whitespace for better model performance.
def prepare_review_data():
    with open(REVIEWS_FILE, 'w', encoding='utf-8') as f_out:
        for xml_file in glob.glob(os.path.join(REVIEWS_DIR, '*.xml')):
            # Store the filename (e.g., 'review_0044_1.xml') for traceability
            xml_filename = os.path.basename(xml_file)

            with open(xml_file, 'r', encoding='utf-8') as f:
                raw_xml = f.read()
                
            # Extract main attributes from the <review> tag
            rev_match = re.search(r'id="([^"]+)"', raw_xml)
            sub_match = re.search(r'submission="([^"]+)"', raw_xml)
            ttl_match = re.search(r'title="([^"]+)"', raw_xml)
            
            review_id = rev_match.group(1) if rev_match else 'unknown'
            submission_id = sub_match.group(1) if sub_match else 'unknown'
            title = ttl_match.group(1) if ttl_match else 'unknown'
            
            review_parts = []
            # Isolate <field> blocks to extract substantive text
            field_blocks = re.findall(r'<field[^>]*>.*?</field>', raw_xml, re.DOTALL)
            
            for block in field_blocks:
                # Find the <text> tags
                text_match = re.search(r'<text[^>]*>(.*?)</text>', block, re.DOTALL)
                
                if text_match:
                    name_match = re.search(r'name="([^"]+)"', block)
                    field_name = name_match.group(1) if name_match else 'Unnamed Field'
                    
                    # html.unescape converts symbols like &amp; back to normal
                    raw_content = text_match.group(1).strip()
                    content = html.unescape(raw_content)
                    
                    if content:
                        review_parts.append(f"{field_name}: {content}")
                        
            if not review_parts:
                continue 
                
            # Final join and whitespace normalization for the model
            combined_text = " ".join(review_parts)
            full_review_text = re.sub(r'\s+', ' ', combined_text).strip()
            
            json_obj = {
                "review": full_review_text,
                "review_id": review_id,
                "submission_id": submission_id,
                "title": title,
                "xml_filename": xml_filename
            }
            
            f_out.write(json.dumps(json_obj, ensure_ascii=False) + '\n')
            
def export_coconuts_to_csv():
    headers = [
        "Source XML File",
        "Submission ID", 
        "Review ID", 
        "Paper Title", 
        "Verdict", 
        "Fine-Grained Verdict", 
        "Idea/Content Source", 
        "Polishing/Style Source"
    ]
    
    # Human-readable mapping for CoCoDet technical labels
    fine_grained_map = {
        "hw": "Human-Written",
        "hwmt": "Human-Written, Machine-Translated",
        "hwmp": "Human-Written, Machine-Polished",
        "hwmg": "Human-Written, Machine-Generated",
        "mg": "Machine-Generated",
        "mgmp": "Machine-Generated, Machine-Polished"
    }
    
    os.makedirs(os.path.dirname(REVIEWS_CSV_FILE), exist_ok=True)
    
    with open(REVIEWS_REPORT_FILE, 'r', encoding='utf-8') as f_in, \
         open(REVIEWS_CSV_FILE, 'w', encoding='utf-8', newline='') as f_out:
        
        writer = csv.writer(f_out)
        writer.writerow(headers)
        
        for line in f_in:
            data = json.loads(line)
            
            # Map the technical label to our new Fine-Grained Verdict
            raw_fg = data.get("predicted_fine_grained_class", "unknown")
            descriptive_fg = fine_grained_map.get(raw_fg, raw_fg.upper())

            # Helper to join lists into clean strings
            def list_to_str(val):
                return ", ".join(val) if isinstance(val, list) else str(val)

            # Write row in the requested order
            writer.writerow([
                data.get("xml_filename", "unknown"),
                data.get("submission_id", "unknown"),
                data.get("review_id", "unknown"),
                data.get("title", "unknown"),
                data.get("predicted_class", "unknown").upper(),
                descriptive_fg,
                list_to_str(data.get("predicted_content_sources", [])),
                list_to_str(data.get("predicted_style_sources", []))
            ])

# Runs banal using the Perl interpreter and parses JSON output
def run_banal(filepath):
    command = ["perl", BANAL_DIR, "-json", filepath]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    
    metrics = {
        "Total Pages": "N/A", "Body Pages": "N/A", "Reference Pages": "N/A",
        "Blank Pages": 0, "Appendix Pages": 0, "Figure Pages": 0,
        "Words": "N/A", "Characters": 0, "Body Font": "N/A", "Reference Font": "N/A", "Line Spacing": "N/A",
        "Margins (Top, Right, Bottom, Left)": "N/A",
        "Columns": "N/A", "Paper Size (HxW)": "N/A", 
        "Page Number Position": "N/A", "Banal Issues": []
    }

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        metrics["Banal Issues"].append("JSON Parse Error (Corrupt PDF?)")
        return metrics

    pages = data.get("pages", [])
    total = len(pages)

    all_headings = []
    mixed_paper_size = False
    total_chars = 0

    if total > 0:
        # Banal tags reference pages as "bib"
        # If the start reference page (where the References header is only) contains body content, 
        #  it will not be tagged as "bib" and will be counted as a body page
        #  In this case, we will use the reffontsize tag to identify this page
        # Other reference pages (even if they contain some body content) will be tagged as "bib" and we will count them as pure reference pages

        # 1. Pure reference Pages 
        #    We subtract THESE from the Total to get Body Pages
        pure_ref_count = sum(1 for p in pages if p.get("type") == "bib")
            
        # 2. Total reference Pages (Pure + Mixed)
        total_ref_count = sum(1 for p in pages if p.get("type") == "bib" or "reffontsize" in p)
        
        # Body Count logic: Total - Pure Refs
        # (We do NOT subtract mixed pages, because they count towards the Body limit)
        metrics["Total Pages"] = total
        metrics["Body Pages"] = total - pure_ref_count # We assume everything else is body (including figures/appendices)
        metrics["Reference Pages"] = total_ref_count
        
        # Additional Page Type Counts based on Banal output types
        metrics["Blank Pages"] = sum(1 for p in pages if p.get("type") == "blank")
        metrics["Appendix Pages"] = sum(1 for p in pages if p.get("type") == "appendix")
        metrics["Figure Pages"] = sum(1 for p in pages if p.get("type") == "figure")
        
        # Deep page analysis for characters, mixed paper sizes, and headings
        for p in pages:
            total_chars += p.get("c", 0)
            if "headings" in p:
                all_headings.extend([h.lower() for h in p["headings"]])
            if "papersize" in p:
                mixed_paper_size = True
                
        metrics["Characters"] = total_chars

    words = data.get("w", 0)
    metrics["Words"] = words if words else "N/A"
    
    body_font = data.get("bodyfontsize", 0)
    metrics["Body Font"] = body_font if body_font else "N/A"
    
    # Banal only reports reffontsize if it differs from the bodyfontsize.
    # We scan the pages to find if any page specifically declares a reffontsize.
    ref_font = body_font
    for p in pages:
        if "reffontsize" in p:
            ref_font = p.get("reffontsize")
            break
    metrics["Reference Font"] = ref_font if ref_font else "N/A"

    # Save margins as a single string, with the explicit header
    margin_data = data.get("margin", None)
    metrics["Margins (Top, Right, Bottom, Left)"] = str(margin_data) if margin_data else "N/A"

    cols = data.get("columns", 0)
    metrics["Columns"] = cols if cols else "N/A"
    metrics["Line Spacing"] = data.get("leading", "N/A") 
    metrics["Page Number Position"] = data.get("nummargin", "N/A")
    
    issues = []
    psize = data.get("papersize", None)
    if isinstance(psize, list) and len(psize) == 2:
        height, width = psize[0], psize[1]
        metrics["Paper Size (HxW)"] = f"{height} x {width}"
        
        # Detect PowerPoints: Landscape format (Width > Height)
        if width > height:
            issues.append("Landscape (Slide?)")
        else:
            # Standard Paper Size Check: STRICTLY US Letter (~792x612)
            # We allow a small 5pt tolerance for PDF compiler rounding differences 
            is_letter = abs(height - 792) <= 5 and abs(width - 612) <= 5
            
            if not is_letter:
                issues.append(f"Non-US Letter Paper Size ({height}x{width})")

            ## Use this if you want to allow both US Letter and A4 (~842x595), but flag anything else as non-standard. 
            # is_letter = abs(height - 792) <= 5 and abs(width - 612) <= 5
            # is_a4 = abs(height - 842) <= 5 and abs(width - 595) <= 5
            
            # if not (is_letter or is_a4):
            #     issues.append(f"Non-Standard Paper Size ({height}x{width})")
            
    # Detect PowerPoints/Bad Scans: Abnormally low word count density
    if total > 2 and words < (total * 150):
        issues.append("Low Word Density")
        
    # Detect Drafts/PowerPoints: Font > 10.5pt (IEEE strictly requires ~10pt)
    if body_font and body_font > 10.5:
        issues.append(f"Font > 10pt ({body_font}pt)")
        
    # Detect Illegal Reference Shrinking: Reject if reference font is suspiciously tiny (< 8pt)
    if ref_font and ref_font < 8.0:
        issues.append(f"Ref Font < 8pt ({ref_font}pt)")
        
    # IEEE vs ACM style check based on physical column count
    if str(cols) == "1":
        issues.append("1-Column (ACM/Draft)")
    elif str(cols) != "2" and cols != 0:
        issues.append(f"{cols}-Column")
        
    # Detect Page Numbers
    if metrics["Page Number Position"] != "N/A":
        issues.append("Page Numbers Found")

    # Structure and Formatting Inconsistencies
    if mixed_paper_size:
        issues.append("Mixed Paper Sizes")
        
    if all_headings:
        has_abstract = any("abstract" in h for h in all_headings)
        has_intro = any("introduction" in h for h in all_headings)
        has_conclusion = any("conclusion" in h for h in all_headings)
        
        if not has_abstract: 
            issues.append("Missing Abstract Header")
        if not has_intro: 
            issues.append("Missing Intro Header")
        if not has_conclusion: 
            issues.append("Missing Conclusion Header")

    # Strict Page Limits and Reference Checks
    if metrics["Body Pages"] != "N/A" and metrics["Body Pages"] > 10:
        issues.append(f"Body > 10 Pages ({metrics['Body Pages']})")
        
    if metrics["Total Pages"] != "N/A" and metrics["Total Pages"] > 12:
        issues.append(f"Total > 12 Pages ({metrics['Total Pages']})")

    if metrics["Reference Pages"] != "N/A":
        # Check for missing references on full drafts
        if metrics["Reference Pages"] == 0 and metrics["Body Pages"] != "N/A" and metrics["Body Pages"] > 6:
            issues.append("Zero Reference Pages")
        
        # Check for reference page abuse (max 2 allowed)
        if metrics["Reference Pages"] > 2:
            issues.append(f"Refs > 2 Pages ({metrics['Reference Pages']})")

    # Bad Margins Check: Compare to standard US Letter [52, 48, 72, 48].
    # We pick 18pt (0.25") as a safe buffer to account for Banal's internal fudge factors (0.05"),
    # rounding to a 4pt grid, and general PDF rendering noise from different LaTeX compilers.
    # Since ICSME 2026 strictly requires US Letter, we use a uniform 18pt variance across all 
    # four margins, completely removing the previous 25pt bottom-margin allowance for A4.
    if isinstance(margin_data, list) and len(margin_data) == 4:
        t, r, b, l = margin_data
        if abs(t - 52) > 18 or abs(r - 48) > 18 or abs(b - 72) > 18 or abs(l - 48) > 18:
            issues.append(f"Bad Margins {margin_data}")

    metrics["Banal Issues"] = issues
    return metrics

def run_sigsoft(filepath):
    command = ["java", "-jar", SIGSOFT_DIR, "-p", "10", "-r", "2", "-s", TARGET_STYLE, filepath]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    
    violations = []

    for line in (result.stdout + result.stderr).split('\n'):
        line_lower = line.lower()
        
        # Ignore lines that explicitly say "no-issues" to prevent false positives from paper titles
        if "no-issues" in line_lower or not line_lower.strip():
            continue
            
        if "issues-found" in line_lower:
            # Extract only the content inside the {}
            match = re.search(r'\{(.*?)\}', line)
            if match:
                violations.append(match.group(1).strip())
            elif line.strip(): 
                # Fallback: if "issues-found" is there but no {}, just append the whole line so we don't miss it
                violations.append(line.strip())

    return { "SIGSOFT Issues": violations }

# Runs Banal and SIGSOFT checks on the PDFs directory
def run_formatting_checkers():
    reports = {}

    # Run Checkers
    for filename in os.listdir(SUBMISSIONS_DIR):
        # Skip files that aren't PDFs or don't match the main submission naming convention
        # Supplementary materials that are either PDF or zip are not checked
        if not (filename.startswith("ICSME_2026_paper") and filename.lower().endswith(".pdf")): 
            continue

        filepath = os.path.join(SUBMISSIONS_DIR, filename)
        results = run_banal(filepath)
        results.update(run_sigsoft(filepath))
        
        # Combine Banal and SIGSOFT issues into a single PASS/REJECT column
        all_issues = results.get("Banal Issues", []) + results.get("SIGSOFT Issues", [])
        if all_issues:
            results["Check Result"] = "REJECT: " + " | ".join(all_issues)
        else:
            results["Check Result"] = "PASS"
            
        paper_id = extract_paper_id(filename)
        reports[paper_id] = results

    shutil.copyfile(SUBMISSIONS_FILE, REPORT_FILE)

    wb = openpyxl.load_workbook(REPORT_FILE)
    ws = wb.active # Get active sheet

    # Find ID column
    header_row = list(ws.values)[0]
    id_col_index = header_row.index(ID_COLUMN_HEADER)

    columns_to_write = [
            "Total Pages", "Body Pages", "Reference Pages", 
            "Blank Pages", "Appendix Pages", "Figure Pages",
            "Words", "Characters", "Body Font", "Reference Font", "Line Spacing", 
            "Margins (Top, Right, Bottom, Left)", 
            "Columns", "Paper Size (HxW)", 
            "Page Number Position", "Check Result"
    ]

    start_col = ws.max_column + 1
    col_mapping = {}
    
    for i, header in enumerate(columns_to_write):
        ws.cell(row=1, column=start_col + i).value = header
        col_mapping[header] = start_col + i

    # Fill Data
    for row in ws.iter_rows(min_row=2):
        id_cell = row[id_col_index]
        
        if id_cell.value is None: continue

        row_id_val = int(id_cell.value)

        if row_id_val in reports:
            data = reports[row_id_val]
            for key in columns_to_write:
                ws.cell(row=id_cell.row, column=col_mapping[key]).value = data.get(key, "N/A")

    wb.save(REPORT_FILE)
    print(f"[+] Formatting report generated at: {REPORT_FILE}")

# Runs the CoCoDet AI content detection pipeline and generates the final CSV report
# Behavior is deterministic and repeatable. Thus, we do not need to run it multiple times.
def run_cocodet():
    # 1. Prepare data
    prepare_review_data()
    
    # 2. Ensure the new 'results' directory exists before inference
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    command = [
        sys.executable, SCRIPT_FILE,
        "--model_name_or_path", "answerdotai/ModernBERT-base",
        "--trained_model_path", MODEL_FILE,
        "--test_file", REVIEWS_FILE,
        "--output_file", REVIEWS_REPORT_FILE,
    ]
    
    # 3. Check if the model file exists before running inference. If not, download it from Hugging Face.
    if not os.path.exists(MODEL_FILE):
        print(f"[*] Model not found at {MODEL_FILE}. Downloading from Hugging Face...")
        os.makedirs(os.path.dirname(MODEL_FILE), exist_ok=True)
        
        # Replace 'username/repo' with the actual Hugging Face path for COCONUTS
        hf_hub_download(
            repo_id="khaaaaaan/CoCoDet", 
            filename="CoCoDet.bin", 
            local_dir=os.path.dirname(MODEL_FILE),
            local_dir_use_symlinks=True
        )
        print("[+] Download complete.")

    # 4. Run inference
    subprocess.run(command, check=True)
    
    # 5. Generate the final CSV
    export_coconuts_to_csv()
    print(f"[+] AI Detection report generated at: {REVIEWS_CSV_FILE}")

def main():
    print("========================================")
    print("  ICSME Submission Checker Suite  ")
    print("========================================")
    print("1. Run Submission Format Checkers (Banal & SIGSOFT)")
    print("2. Run CoCoDet AI Content Detection")
    print("3. Exit")
    print("========================================")

    while True:
        choice = input("Enter your choice (1, 2, or 3): ")
        if choice.strip() == '1':
            run_formatting_checkers()
        elif choice.strip() == '2':
            run_cocodet()
        elif choice.strip() == '3':
            print("Exiting.")
            break
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")

if __name__ == "__main__":
    main()
