"""Tests of the identity check on the fixtures of tests/fixtures/identity, built by make_fixtures.py there, and on
small PDFs that the tests write."""

import dataclasses
import shutil
from pathlib import Path

import pikepdf
import pymupdf
import pytest

from peercheck import tools
from peercheck.findings import Severity
from peercheck.inputs import read_people
from peercheck.models import Paper, Person
from peercheck.papers import embedded_identity, sigsoft
from peercheck.profile import load

FIXTURES = Path(__file__).parent / "fixtures" / "identity"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
SAMPLES = Path(__file__).parents[1] / "examples"
PROFILE = load("icse-2027")
LENA = Person("Lena", "Brandt", "lena.brandt@uni-nowhere.edu", "University of Nowhere")
ERROR, WARNING, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
NO_ACKNOWLEDGMENT_RULE = dataclasses.replace(
    PROFILE, checks={**PROFILE.checks, "anonymity": {"flag_acknowledgments": False}})
CLEAN = sorted((SAMPLES / "papers").glob("*.pdf")) + sorted(p for p in PAPERS.glob("*.pdf") if p.name != "corrupt.pdf")
XMP_CREATOR = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
               '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator><rdf:Seq>'
               '<rdf:li>{name}</rdf:li></rdf:Seq></dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>')
needs_jar = pytest.mark.skipif(not shutil.which("java") or not tools.submission_checker().is_file(),
                               reason="needs Java and the bundled jar")


def run(pdf: str | Path, *authors: Person, profile=PROFILE) -> list:
    """Run the check on a fixture, named without its suffix, or on a PDF, with the given authors."""
    path = pdf if isinstance(pdf, Path) else FIXTURES / f"{pdf}.pdf"
    return embedded_identity.check(Paper(1, path, "", authors), profile, path.parent)


def summary(findings: list) -> set[tuple[str, Severity, str]]:
    """Return the check, the severity, and the evidence of each finding."""
    return {(f.check, f.severity, f.evidence) for f in findings}


def write_pdf(path: Path, build) -> Path:
    """Write a one-page PDF with a line of text, changed by build(document, page), and return its path."""
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Flaky tests pass and fail on the same code.", fontsize=11)
        build(document, page)
        document.save(path)
    return path


def shown(text: str):
    """Return a build step that prints the text on the page."""
    return lambda document, page: page.insert_text((72, 100), text, fontsize=11)


def described(text: str):
    """Return a build step that embeds a file with the text as its description."""
    return lambda document, page: document.embfile_add("notes.txt", b"notes", desc=text)


def show_figure(document: pymupdf.Document, page: pymupdf.Page, keys: dict[str, str]) -> None:
    """Show a PDF figure on the page and set the keys on the form that holds it, as pdfTeX writes them."""
    with pymupdf.open() as figure:
        figure.new_page(width=100, height=50).draw_rect(pymupdf.Rect(5, 5, 95, 45))
        page.show_pdf_page(pymupdf.Rect(72, 100, 272, 200), figure, 0)
    form = next(xref for xref, _, invoker, _ in document.get_page_xobjects(page.number) if invoker == 0)
    for key, value in keys.items():
        document.xref_set_key(form, key, value)


@pytest.mark.parametrize("authors", [(), (LENA,)])
def test_figure_in_a_home_folder_gives_a_warning_and_leaves_its_author_to_the_sigsoft_checker(authors):
    found = run("figure-author-home", *authors)
    assert summary(found) == {("identity.home-folder", WARNING, "/Users/lbrandt/paper/figures/pipeline.pdf")}
    assert found[0].page == 1
    assert found[0].message == "Home folder of a user account in the file path of an included figure (PTEX.FileName)"


@pytest.mark.parametrize("authors", [(), (LENA,)])
def test_figure_without_author_included_by_a_relative_path_gives_no_finding(authors):
    assert run("figure-clean", *authors) == []


def test_linearized_pdf_is_one_revision_and_gives_no_note():
    assert run("figure-clean-linearized", LENA) == []


def test_comment_authors_are_warnings_without_an_author_list_except_placeholders():
    assert summary(run("comment-authors")) == {("identity.comment-author", WARNING, "Lena Brandt"),
                                               ("identity.comment-author", WARNING, "lbrandt")}


def test_comment_by_an_author_of_the_paper_is_left_to_the_sigsoft_checker():
    found = run("comment-authors", LENA)
    assert summary(found) == {("identity.comment-author", WARNING, "lbrandt")}
    assert found[0].page == 1


def test_author_name_in_an_earlier_revision_is_an_error_on_its_page():
    found = run("earlier-revision", LENA)
    assert [(f.check, f.severity, f.page) for f in found] == [("identity.earlier-revision", ERROR, 1)]
    assert found[0].message == "Name or email of an author of this paper in the page text of an earlier revision"
    assert "Lena Brandt" in found[0].evidence


def test_earlier_revisions_without_an_author_list_are_an_info_note():
    found = run("earlier-revision")
    assert [(f.check, f.severity, f.evidence) for f in found] == [("identity.revisions", INFO, "2 revisions")]
    assert found[0].message == "The PDF holds 2 revisions, and the earlier ones stay readable"


def test_incremental_save_that_names_no_author_is_an_info_note_that_says_so(tmp_path):
    pdf = tmp_path / "edited.pdf"
    shutil.copy(FIXTURES / "figure-clean.pdf", pdf)
    with pymupdf.open(pdf) as document:
        document.set_metadata({"title": "Order-Dependent Flaky Tests"})
        document.saveIncr()
    found = run(pdf, LENA)
    assert [(f.check, f.severity) for f in found] == [("identity.revisions", INFO)]
    assert found[0].message.endswith("no earlier revision names an author of this paper")


def test_author_removed_from_the_document_metadata_by_an_incremental_save_is_an_error(tmp_path):
    pdf = write_pdf(tmp_path / "metadata.pdf", lambda document, page: document.set_metadata({"author": "Lena Brandt"}))
    with pymupdf.open(pdf) as document:
        document.set_metadata({"author": ""})
        document.saveIncr()
    found = run(pdf, LENA)
    assert summary(found) == {("identity.earlier-revision", ERROR, "Lena Brandt")}
    assert found[0].page is None
    assert "the document metadata of an earlier revision" in found[0].message


def test_author_name_that_the_final_revision_still_shows_is_left_to_the_sigsoft_checker(tmp_path):
    pdf = write_pdf(tmp_path / "named.pdf", lambda document, page: page.insert_text((72, 100), "Lena Brandt"))
    with pymupdf.open(pdf) as document:
        document.set_metadata({"title": "Order-Dependent Flaky Tests"})
        document.saveIncr()
    assert summary(run(pdf, LENA)) == {("identity.revisions", INFO, "2 revisions")}


def test_author_name_in_jpeg_xmp_is_an_error_and_its_home_folder_a_warning():
    path = ("identity.home-folder", WARNING, "/Users/lbrandt/Pictures/setup.jpg")
    assert summary(run("jpeg-xmp", LENA)) == {("identity.author", ERROR, "Lena Brandt"), path}
    assert summary(run("jpeg-xmp")) == {path}


@pytest.mark.parametrize("pdf", CLEAN, ids=lambda pdf: pdf.name)
def test_clean_paper_gives_no_finding_with_or_without_authors(pdf):
    authors = [person for people in read_people(SAMPLES / "authors.csv", with_paper=True).values() for person in people]
    assert run(pdf, *authors) == []
    if pdf.name != "conf2027-paper3.pdf":
        assert run(pdf) == []


def test_anonymous_paper_with_placeholders_and_an_anonymized_artifact_gives_no_finding():
    assert run("anonymous-artifact") == []
    assert run("anonymous-artifact", LENA) == []


def test_author_in_the_page_text_and_the_document_metadata_is_left_to_the_sigsoft_checker():
    pdf = SAMPLES / "papers" / "conf2027-paper3.pdf"
    with pymupdf.open(pdf) as document:
        assert document.metadata["author"] == "Lena Brandt"
    assert run(pdf, LENA) == []


def test_unreadable_pdf_gives_a_warning_that_names_no_file():
    found = run(PAPERS / "corrupt.pdf", LENA)
    assert [(f.check, f.severity) for f in found] == [("identity.error", WARNING)]
    assert "corrupt" not in found[0].message
    assert str(PAPERS) not in found[0].message


@pytest.mark.parametrize("case", ["figure-author-home", "comment-authors", "earlier-revision", "jpeg-xmp",
                                  "funding-footnote", "orcid-number", "email-hyphen-domain", "document-home-folder"])
def test_findings_name_no_path_or_file_of_the_submission(case):
    for finding in run(case, LENA):
        assert case not in finding.message + finding.evidence
        assert str(FIXTURES) not in finding.message + finding.evidence


def test_author_name_in_the_name_or_description_of_an_embedded_file_is_an_error(tmp_path):
    def embed(document, page):
        document.embfile_add("lena_brandt_interviews.csv", b"id,answer\n", desc="Interviews by L. Brandt")

    pdf = write_pdf(tmp_path / "embedded.pdf", embed)
    found = run(pdf, LENA)
    assert summary(found) == {("identity.author", ERROR, "lena_brandt_interviews.csv"),
                              ("identity.author", ERROR, "Interviews by L. Brandt")}
    assert {f.message for f in found} == {
        "Name or email of an author of this paper in the name of an embedded file",
        "Name or email of an author of this paper in the description of an embedded file"}
    assert run(pdf) == []


def test_home_folder_in_the_name_of_a_file_attached_to_a_comment_is_a_warning(tmp_path):
    def attach(document, page):
        page.add_file_annot((72, 200), b"1,2\n", "C:\\Users\\lbrandt\\Desktop\\scores.csv")

    found = run(write_pdf(tmp_path / "attached.pdf", attach))
    assert summary(found) == {("identity.home-folder", WARNING, "C:\\Users\\lbrandt\\Desktop\\scores.csv")}
    assert found[0].page == 1


def test_author_name_in_the_xmp_stream_of_an_image_is_an_error(tmp_path):
    def image(document, page):
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
        xref = page.insert_image(pymupdf.Rect(72, 100, 144, 172), pixmap=pixmap)
        metadata = document.get_new_xref()
        document.update_object(metadata, "<< /Type /Metadata /Subtype /XML >>")
        document.update_stream(metadata, XMP_CREATOR.format(name="Lena Brandt").encode())
        document.xref_set_key(xref, "Metadata", f"{metadata} 0 R")

    found = run(write_pdf(tmp_path / "image.pdf", image), LENA)
    assert summary(found) == {("identity.author", ERROR, "Lena Brandt")}
    assert found[0].page == 1
    assert found[0].message == "Name or email of an author of this paper in the XMP metadata of an image"


def test_metadata_stream_is_read_only_up_to_the_stream_limit(tmp_path):
    def image(document, page):
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
        xref = page.insert_image(pymupdf.Rect(72, 100, 144, 172), pixmap=pixmap)
        metadata = document.get_new_xref()
        document.update_object(metadata, "<< /Type /Metadata /Subtype /XML >>")
        padding = " " * embedded_identity.STREAM_LIMIT
        document.update_stream(metadata, (padding + XMP_CREATOR.format(name="Lena Brandt")).encode())
        document.xref_set_key(xref, "Metadata", f"{metadata} 0 R")

    assert run(write_pdf(tmp_path / "padded.pdf", image), LENA) == []


def test_figure_that_no_page_shows_is_checked_for_author_names(tmp_path):
    def unused_figure(document, page):
        xref = document.get_new_xref()
        document.update_object(xref, "<< /Type /XObject /Subtype /Form /BBox [0 0 10 10] "
                                     "/PTEX.InfoDict << /Author (Lena Brandt) >> >>")
        document.update_stream(xref, b"")

    pdf = write_pdf(tmp_path / "unused.pdf", unused_figure)
    found = run(pdf, LENA)
    assert summary(found) == {("identity.author", ERROR, "Lena Brandt")}
    assert found[0].message.endswith("in the metadata of an included figure (PTEX.InfoDict Author)")
    assert run(pdf) == []


def test_figure_author_on_a_page_is_left_to_the_sigsoft_checker(tmp_path):
    pdf = write_pdf(tmp_path / "shown.pdf",
                    lambda document, page: show_figure(document, page, {"PTEX.InfoDict": "<< /Author (Lena Brandt) >>"}))
    assert run(pdf, LENA) == []


def test_home_folder_named_after_an_author_is_left_to_the_sigsoft_checker(tmp_path):
    path = "/home/lena_brandt/paper/plot.pdf"
    pdf = write_pdf(tmp_path / "home.pdf", lambda document, page: show_figure(
        document, page, {"PTEX.FileName": pymupdf.get_pdf_str(path)}))
    assert run(pdf, LENA) == []
    assert summary(run(pdf)) == {("identity.home-folder", WARNING, path)}


def test_home_folders_in_link_targets_form_one_warning(tmp_path):
    def links(document, page):
        page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 60, 200, 80),
                          "uri": "file:///home/lbrandt/notes.txt"})
        page.insert_link({"kind": pymupdf.LINK_LAUNCH, "from": pymupdf.Rect(72, 90, 200, 110),
                          "file": "/Users/lbrandt/run.sh"})

    found = run(write_pdf(tmp_path / "links.pdf", links))
    assert [(f.check, f.severity, f.page) for f in found] == [("identity.home-folder", WARNING, 1)]
    assert found[0].message == "Home folder of a user account in the target of a link"
    assert set(found[0].evidence.split(" | ")) == {"file:///home/lbrandt/notes.txt", "/Users/lbrandt/run.sh"}


@pytest.mark.parametrize("path", [
    "/Users/lbrandt/paper/fig.pdf", "/home/lbrandt/paper/fig.pdf", "C:\\Users\\lbrandt\\Documents\\fig.pdf",
    "c:/users/lbrandt/fig.pdf", "/mnt/c/Users/lbrandt/fig.pdf", "file:///Users/lbrandt/fig.pdf",
    "D:\\Documents and Settings\\lbrandt\\fig.pdf",
])
def test_home_folder_is_recognized_on_macos_linux_and_windows(tmp_path, path):
    found = run(write_pdf(tmp_path / "path.pdf", described(path)))
    assert summary(found) == {("identity.home-folder", WARNING, path)}


@pytest.mark.parametrize("path", [
    "/Users/Shared/fig.pdf", "C:\\Users\\Public\\fig.pdf", "/home/runner/work/paper/fig.pdf",
    "./Users/lbrandt/fig.pdf", "https://example.org/home/lbrandt/fig.pdf", "figures/home/plot.pdf",
    "/usr/local/texlive/2026/texmf-dist/tex/latex/doclicense/images/doclicense-CC-by-88x31.pdf",
])
def test_shared_relative_and_web_folders_are_no_home_folder(tmp_path, path):
    assert run(write_pdf(tmp_path / "path.pdf", described(path))) == []


@pytest.mark.parametrize("text", [
    "Lena Brandt", "Brandt, Lena", "L. Brandt", "Brandt, L.", "Lena M. Brandt", "LENA BRANDT", "Lëna Brandt",
    "lena.brandt@uni-nowhere.edu",
])
def test_author_name_and_email_match_in_the_forms_of_the_sigsoft_checker(tmp_path, text):
    found = run(write_pdf(tmp_path / "name.pdf", described(text)), LENA)
    assert summary(found) == {("identity.author", ERROR, text)}


@pytest.mark.parametrize("text", ["Lena", "Brandt", "Lena Brandtner", "Magdalena Brandt", "Helena Brandt"])
def test_part_of_a_name_or_a_longer_name_is_no_author_match(tmp_path, text):
    assert run(write_pdf(tmp_path / "name.pdf", described(text)), LENA) == []


@pytest.mark.parametrize(("text", "folded", "places"), [
    ("Lena Brandt", "lena brandt", list(range(11))),
    ("Lena \t BRANDT", "lena brandt", [0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12]),
    ("Lena  Brandt", "lena brandt", [0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 11]),
    ("Lena\tBrandt", "lena brandt", list(range(11))),
    ("Ka^stner`", "kastner", [0, 1, 3, 4, 5, 6, 7]),
    ("Kästner", "kastner", list(range(7))),
    ("Straße", "strasse", [0, 1, 2, 3, 4, 4, 5]),
])
def test_text_is_folded_to_lower_case_without_accents_and_each_character_keeps_its_place(text, folded, places):
    result, where = embedded_identity._fold(text)
    assert (result, list(where)) == (folded, places)


@pytest.mark.parametrize("text", ["Jürgen König", "Jurgen Konig", "J. König"])
def test_author_list_with_latex_accents_matches_names_with_and_without_accents(tmp_path, text):
    author = Person("J{\\\"u}rgen", "K{\\\"o}nig")
    found = run(write_pdf(tmp_path / "accents.pdf", described(text)), author)
    assert summary(found) == {("identity.author", ERROR, text)}


def test_home_folder_in_the_document_information_is_a_warning():
    found = run("document-home-folder")
    assert summary(found) == {("identity.home-folder", WARNING, "/home/lbrandt/papers/flaky-tests/main.dvi")}
    assert found[0].page is None
    assert found[0].message == "Home folder of a user account in the document information (Title)"


def test_home_folder_in_the_xmp_metadata_of_the_document_is_a_warning(tmp_path):
    xmp = XMP_CREATOR.format(name="C:\\Users\\lbrandt\\Documents\\flaky-tests.docx")
    found = run(write_pdf(tmp_path / "xmp.pdf", lambda document, page: document.set_xml_metadata(xmp)))
    assert summary(found) == {("identity.home-folder", WARNING, "C:\\Users\\lbrandt\\Documents\\flaky-tests.docx")}
    assert found[0].message == "Home folder of a user account in the XMP metadata of the document"


def test_funding_statement_on_the_first_page_is_a_warning():
    found = run("funding-footnote")
    assert [(f.check, f.severity, f.page) for f in found] == [("identity.funding", WARNING, 1)]
    assert found[0].message == "Funding statement on the first page"
    assert found[0].evidence == ("This work was supported in part by the Nowhere Science Foundation under Grant "
                                 "NSF-0000000.")


def test_funding_statement_is_no_finding_where_the_template_allows_acknowledgments():
    assert run("funding-footnote", profile=NO_ACKNOWLEDGMENT_RULE) == []


def test_funding_statement_is_a_finding_where_the_template_leaves_the_setting_out():
    unset = dataclasses.replace(PROFILE, checks={**PROFILE.checks, "anonymity": {}})
    assert [f.check for f in run("funding-footnote", profile=unset)] == ["identity.funding"]


@pytest.mark.parametrize("support", ["grant", "fellowship", "scholarship", "award", "fund", "funding", "gift",
                                     "donation"])
def test_funding_statement_may_name_a_grant_or_a_gift_in_place_of_a_funder(tmp_path, support):
    found = run(write_pdf(tmp_path / "funding.pdf", shown(f"This work was supported by a research {support}.")))
    assert [f.check for f in found] == ["identity.funding"]


@pytest.mark.parametrize("text", [
    "This work was supported by the Nowhere Science Foundation.",
    "The authors are funded in part by the Ministry of Made-Up Affairs.",
    "Our project has received funding from the Nowhere Research Council.",
    "Lena Brandt holds grant no. 4711 of the fund.",
    "Supported under grants NSF-0000000 and 13/XY/209.",
    "Supported by the Nowhere Science Foundation.",
    "The work of Lena Brandt was supported by the Nowhere Science Foundation.",
    "This research was sponsored by a gift from Tessera Systems.",
    "Our study was financed by the Nowhere Research Council.",
    "This paper was supported by a research grant of the fund.",
    "This material is based upon work supported by the Nowhere Science Foundation.",
    "This publication was funded by the Nowhere Research Council.",
    "This project was funded by the Nowhere Research Council.",
    "The research has been funded by the Ministry of Made-Up Affairs.",
])
def test_funding_statement_is_recognized_by_its_funder_or_its_grant_number(tmp_path, text):
    found = run(write_pdf(tmp_path / "funding.pdf", shown(text)))
    assert [f.check for f in found] == ["identity.funding"]


@pytest.mark.parametrize("text", [
    "Much of our work is supported by sophisticated tools.", "The build is supported by the Tessera runner.",
    "The contract 0x52ae12 holds the tokens.", "The tool won an award 2024.", "Grant et al. 2020 report the same.",
    "The contract no longer holds 4711 tokens.",
    "In this paper, we present a tool that is supported by the Tessera runner.",
    "Funding and acknowledgments are withheld for review.",
    "Our study is supported by a dataset of 500 Java projects.",
    "This work is supported by empirical evidence from Stack Overflow.",
    "Our research is further supported by interviews with engineers at Tessera.",
    "Users grant 3rd-party apps access to their contacts.", "We grant GPT-4o access to the repository.",
    "Apps that grant API23-level permissions are excluded.", "The jury gave the award 3-times in a row.",
    "This work was supported by [Anonymized for review].", "This work was supported by Anonymous Funder.",
    "This work was supported by a grant that is omitted for review.",
    "A user behaviour study is supported by the Tessera logs.",
    "Test Selection Supported by Tessera Logs", "The runner, supported by Tessera, reruns each test.",
])
def test_text_that_names_no_funder_and_no_grant_is_no_funding_statement(tmp_path, text):
    assert run(write_pdf(tmp_path / "funding.pdf", shown(text))) == []


def test_funding_statement_on_a_later_page_is_left_to_the_acknowledgments_heading(tmp_path):
    def second_page(document, page):
        document.new_page().insert_text((72, 100), "This work was supported by the Nowhere Science Foundation.")

    assert run(write_pdf(tmp_path / "later.pdf", second_page)) == []


def test_orcid_number_printed_on_the_first_page_is_a_warning_and_a_similar_number_is_none():
    found = run("orcid-number")
    assert summary(found) == {("identity.orcid", WARNING, "0000-0002-1825-0097")}
    assert found[0].page == 1
    assert found[0].message == "ORCID iD on the first page"


@pytest.mark.parametrize("text", ["The run 10000-0002-1825-0097 failed.", "The key 0000-0002-1825-0097-22 is made up.",
                                  "The label v0000-0002-1825-0097 names a build.", "0000-0002-1825-0097a"])
def test_number_inside_a_longer_number_or_word_is_no_orcid_number(tmp_path, text):
    assert run(write_pdf(tmp_path / "number.pdf", shown(text))) == []


def test_orcid_number_whose_record_only_a_later_page_links_is_a_warning(tmp_path):
    def linked_later(document, page):
        page.insert_text((72, 100), "0000-0002-1825-0097")
        document.new_page().insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 90, 200, 104),
                                         "uri": "https://orcid.org/0000-0002-1825-0097"})

    found = run(write_pdf(tmp_path / "orcid.pdf", linked_later))
    assert [(f.check, f.page) for f in found] == [("identity.orcid", 1)]


def test_orcid_number_inside_a_link_of_the_text_is_left_to_the_sigsoft_checker(tmp_path):
    assert run(write_pdf(tmp_path / "orcid.pdf", shown("https://orcid.org/0000-0002-1825-0097"))) == []


def test_orcid_number_under_a_link_to_its_record_is_left_to_the_sigsoft_checker(tmp_path):
    def linked(document, page):
        page.insert_text((72, 100), "0000-0002-1825-0097")
        page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 90, 200, 104),
                          "uri": "https://orcid.org/0000-0002-1825-0097"})

    assert run(write_pdf(tmp_path / "orcid.pdf", linked)) == []


def test_email_at_a_domain_with_a_hyphen_on_the_first_page_is_an_error():
    found = run("email-hyphen-domain")
    assert summary(found) == {("identity.email", ERROR, "lena.brandt@uni-nowhere.edu")}
    assert found[0].page == 1
    assert found[0].message == "Email address on the first page"


def test_email_of_an_author_of_the_paper_is_left_to_the_sigsoft_checker():
    assert run("email-hyphen-domain", LENA) == []


@pytest.mark.parametrize("text", ["anonymous@uni-nowhere.edu", "lena.brandt@nowhere.edu", "uni-nowhere.edu"])
def test_placeholder_email_and_email_that_the_sigsoft_checker_reads_are_no_finding(tmp_path, text):
    assert run(write_pdf(tmp_path / "email.pdf", shown(text))) == []


@pytest.mark.parametrize("text", ["We report precision @ top-5.The gain holds.", "It reaches hit@top-10.Each run"])
def test_measure_at_a_cutoff_before_a_sentence_that_lost_its_space_is_no_email(tmp_path, text):
    assert run(write_pdf(tmp_path / "measure.pdf", shown(text))) == []


def test_emails_and_orcid_numbers_of_several_authors_form_one_finding_each(tmp_path):
    text = "lena.brandt@uni-nowhere.edu omar.haddad@hill-crest.edu\n0000-0002-1825-0097 0000-0000-0000-001X"
    found = run(write_pdf(tmp_path / "authors.pdf", shown(text)))
    assert summary(found) == {
        ("identity.orcid", WARNING, "0000-0002-1825-0097 | 0000-0000-0000-001X"),
        ("identity.email", ERROR, "lena.brandt@uni-nowhere.edu | omar.haddad@hill-crest.edu")}


def test_findings_of_the_first_page_stand_between_those_of_the_document_and_those_of_later_pages(tmp_path):
    def build(document, page):
        document.set_metadata({"title": "/home/lbrandt/papers/flaky-tests/main.dvi"})
        page.insert_text((72, 100), "This work was supported by the Nowhere Science Foundation.")
        note = document.new_page().add_text_annot((72, 72), "Check the second order.")
        note.set_info(title="Omar Haddad")
        note.update()

    found = run(write_pdf(tmp_path / "pages.pdf", build))
    assert [(f.check, f.page) for f in found] == [
        ("identity.home-folder", None), ("identity.funding", 1), ("identity.comment-author", 2)]


def test_pdf_without_a_page_gives_no_finding(tmp_path):
    pdf = tmp_path / "empty.pdf"
    with pikepdf.new() as document:
        document.save(pdf)
    assert run(pdf) == []


def test_group_of_emails_at_a_domain_with_a_hyphen_is_an_error(tmp_path):
    found = run(write_pdf(tmp_path / "emails.pdf", shown("{lena.brandt, omar.haddad}@uni-nowhere.edu")))
    assert summary(found) == {("identity.email", ERROR, "{lena.brandt, omar.haddad}@uni-nowhere.edu")}


@needs_jar
def test_no_value_is_reported_by_both_this_check_and_the_sigsoft_checker(tmp_path):
    papers = []
    cases = ("figure-author-home", "comment-authors", "earlier-revision", "jpeg-xmp", "email-hyphen-domain",
             "orcid-number", "document-home-folder")
    for number, case in enumerate(cases, start=1):
        copy = tmp_path / f"conf-paper{number}.pdf"
        shutil.copy(FIXTURES / f"{case}.pdf", copy)
        papers.append(Paper(number, copy, "", (LENA,)))
    jar = sigsoft.check_batch(papers, PROFILE, tmp_path)
    for paper in papers:
        theirs = " ".join(f.evidence for f in jar[paper.paper_id])
        for finding in embedded_identity.check(paper, PROFILE, tmp_path):
            assert not any(value in theirs for value in finding.evidence.split(" | "))
    reported = {f.evidence for f in jar[1] + jar[2]}
    assert "Lena Brandt (figure metadata (PTEX.InfoDict Author))" in reported
    assert "Lena Brandt (annotation author)" in reported
