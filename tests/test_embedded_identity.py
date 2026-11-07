"""Tests of the identity check on the fixtures of tests/fixtures/identity, built by make_fixtures.py there, and on
small PDFs that the tests write."""

import shutil
from pathlib import Path

import pymupdf
import pytest

from peercheck import tools
from peercheck.checks import embedded_identity, sigsoft
from peercheck.findings import Severity
from peercheck.inputs import read_people
from peercheck.models import Paper, Person
from peercheck.profile import load

FIXTURES = Path(__file__).parent / "fixtures" / "identity"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
SAMPLES = Path(__file__).parents[1] / "samples"
PROFILE = load("icse-2027")
LENA = Person("Lena", "Brandt", "lena.brandt@uni-nowhere.edu", "University of Nowhere")
ERROR, WARNING, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
CLEAN = sorted((SAMPLES / "papers").glob("*.pdf")) + sorted(p for p in PAPERS.glob("*.pdf") if p.name != "corrupt.pdf")
XMP_CREATOR = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
               '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator><rdf:Seq>'
               '<rdf:li>{name}</rdf:li></rdf:Seq></dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>')
needs_jar = pytest.mark.skipif(not shutil.which("java") or not tools.submission_checker().is_file(),
                               reason="needs Java and the bundled jar")


def run(pdf: str | Path, *authors: Person) -> list:
    """Run the check on a fixture, named without its suffix, or on a PDF, with the given authors."""
    path = pdf if isinstance(pdf, Path) else FIXTURES / f"{pdf}.pdf"
    return embedded_identity.check(Paper(1, path, "", authors), PROFILE, path.parent)


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
    assert "Lena Brandt" in found[0].evidence


def test_earlier_revisions_without_an_author_list_are_an_info_note():
    found = run("earlier-revision")
    assert [(f.check, f.severity, f.evidence) for f in found] == [("identity.revisions", INFO, "2 revisions")]


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
    assert run(pdf) == []
    assert run(pdf, *authors) == []


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


@pytest.mark.parametrize("case", ["figure-author-home", "comment-authors", "earlier-revision", "jpeg-xmp"])
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


@pytest.mark.parametrize("text", ["Jürgen König", "Jurgen Konig", "J. König"])
def test_author_list_with_latex_accents_matches_names_with_and_without_accents(tmp_path, text):
    author = Person("J{\\\"u}rgen", "K{\\\"o}nig")
    found = run(write_pdf(tmp_path / "accents.pdf", described(text)), author)
    assert summary(found) == {("identity.author", ERROR, text)}


@needs_jar
def test_no_value_is_reported_by_both_this_check_and_the_sigsoft_checker(tmp_path):
    papers = []
    for number, case in enumerate(("figure-author-home", "comment-authors", "earlier-revision", "jpeg-xmp"), start=1):
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
