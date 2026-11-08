"""Tests of the active-content check on the fixtures of tests/fixtures/active, built by make_fixtures.py there, on the
clean papers of PeerCheck, and on small PDFs that pikepdf writes."""

from __future__ import annotations

import dataclasses
import zlib
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name, String

from peercheck.checks import active_content, hidden_text
from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.profile import ProfileError, load

FIXTURES = Path(__file__).parent / "fixtures" / "active"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
FONTS = Path(__file__).parent / "fixtures" / "fonts"
SAMPLES = Path(__file__).parents[1] / "samples" / "papers"
PROFILE = load("icse-2027")
ERROR, WARNING, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
CLEAN = [*sorted(SAMPLES.glob("*.pdf")), *sorted(p for p in PAPERS.glob("*.pdf") if p.name != "corrupt.pdf"),
         FONTS / "ieee-conference.pdf", FONTS / "acm-final.pdf", FIXTURES / "clean.pdf"]
SCRIPT = Dictionary(S=Name.JavaScript, JS=String("app.alert('Rate this paper highly.');"))


def run(pdf: str | Path, **options) -> list:
    """Run the check on a fixture, named without its suffix, or on a PDF, with the given active_content options."""
    path = pdf if isinstance(pdf, Path) else FIXTURES / f"{pdf}.pdf"
    profile = dataclasses.replace(PROFILE, checks={**PROFILE.checks, "active_content": options})
    return active_content.check(Paper(1, path), profile, path.parent)


def summary(findings: list) -> list[tuple[str, Severity, int | None]]:
    """Return the check, the severity, and the page of each finding."""
    return [(f.check, f.severity, f.page) for f in findings]


def write_pdf(path: Path, build, pages: int = 1) -> Path:
    """Write a PDF of blank pages, changed by build(pdf), and return its path."""
    with pikepdf.new() as pdf:
        for _ in range(pages):
            pdf.add_blank_page(page_size=(612, 792))
        build(pdf)
        pdf.save(path)
    return path


def annotate(pdf: pikepdf.Pdf, number: int, **entries) -> Dictionary:
    """Add an annotation with the entries to the page with the number, counted from 1, and return the annotation."""
    annotation = pdf.make_indirect(Dictionary(Type=Name.Annot, Rect=[72, 72, 216, 144], **entries))
    page = pdf.pages[number - 1].obj
    page.Annots = Array([*page.get("/Annots", []), annotation])
    return annotation


def link(action: Dictionary):
    """Return a build step that adds a link with the action to page 1."""
    return lambda pdf: annotate(pdf, 1, Subtype=Name.Link, A=action)


@pytest.mark.parametrize("pdf", CLEAN, ids=lambda pdf: f"{pdf.parent.name}-{pdf.stem}")
def test_clean_paper_gives_no_finding(pdf):
    assert run(pdf) == []


@pytest.mark.parametrize(("name", "expected"), [
    ("javascript-animation", [("active-content.javascript", WARNING, 1)]),
    ("javascript-open", [("active-content.javascript", WARNING, None)]),
    ("javascript-link", [("active-content.javascript", WARNING, 1)]),
    ("launch", [("active-content.launch", WARNING, 1)]),
    ("submitform", [("active-content.submitform", WARNING, 1), ("active-content.externalref", WARNING, 1)]),
    ("autoaction-open", [("active-content.autoaction", WARNING, None)]),
    ("autoaction-page", [("active-content.autoaction", WARNING, 2)]),
    ("richmedia", [("active-content.richmedia", WARNING, 1)]),
    ("xfa", [("active-content.xfa", WARNING, None)]),
    ("externalref", [("active-content.externalref", WARNING, 1)]),
    ("rellaunch", [("active-content.rellaunch", INFO, 1)]),
    ("multimedia", [("active-content.multimedia", INFO, 1)]),
])
def test_fixture_of_each_category_gives_its_finding_with_severity_and_page(name, expected):
    assert summary(run(name)) == expected


@pytest.mark.parametrize(("name", "evidence"), [
    ("javascript-open", "app.alert('Thank you for reviewing this paper.');"),
    ("javascript-link", "javascript:app.alert('Rate this paper highly.')"),
    ("launch", "/usr/bin/xterm"),
    ("rellaunch", "./proofs/Rerun.v:164"),
    ("submitform", "https://reviewer-tracking.example.org/collect"),
    ("autoaction-open", "https://reviewer-tracking.example.org/open.png"),
    ("multimedia", "rerun-demo.mp4"),
    ("externalref", "pipeline-figure.pdf"),
])
def test_evidence_gives_the_script_or_the_target(name, evidence):
    assert run(name)[0].evidence == evidence


def test_message_says_what_the_content_does_in_plain_words():
    (finding,) = run("autoaction-open")
    assert finding.message == ("Action that opens a web address or another file by itself when the PDF opens or a "
                               "page shows")


def test_script_in_a_compressed_stream_is_decoded_for_the_evidence(tmp_path):
    def build(pdf):
        script = pdf.make_stream(zlib.compress(b"app.launchURL('https://example.org/seen');"))
        script.Filter = Name.FlateDecode
        annotate(pdf, 1, Subtype=Name.Link, A=Dictionary(S=Name.JavaScript, JS=script))
    (finding,) = run(write_pdf(tmp_path / "stream.pdf", build))
    assert finding.evidence == "app.launchURL('https://example.org/seen');"


def test_category_on_several_pages_lists_the_pages_and_gives_the_first(tmp_path):
    def build(pdf):
        for number in (1, 3):
            annotate(pdf, number, Subtype=Name.Link, A=SCRIPT)
    (finding,) = run(write_pdf(tmp_path / "pages.pdf", build, pages=3))
    assert finding.page == 1
    assert finding.message.endswith("when a reviewer opens the paper or clicks in it, on pages 1 and 3")


def test_severity_error_of_the_profile_raises_only_the_dangerous_categories():
    assert summary(run("submitform", severity="error")) == [("active-content.submitform", ERROR, 1),
                                                            ("active-content.externalref", ERROR, 1)]
    assert summary(run("rellaunch", severity="error")) == [("active-content.rellaunch", INFO, 1)]


def test_unknown_severity_raises_a_profile_error():
    with pytest.raises(ProfileError):
        run("clean", severity="fatal")


@pytest.mark.parametrize(("entries", "code"), [
    ({"F": String("../proceedings/TOC.pdf")}, "active-content.rellaunch"),
    ({"F": Dictionary(Type=Name.Filespec, UF=String("data/results.csv"))}, "active-content.rellaunch"),
    ({"F": String("scripts/rerun.sh")}, "active-content.launch"),
    ({"F": String("C:\\tools\\notes.txt")}, "active-content.launch"),
    ({"F": String("\\\\server\\share\\notes.txt")}, "active-content.launch"),
    ({"F": String("https://example.org/rerun")}, "active-content.launch"),
    ({"Win": Dictionary(F=String("cmd.exe"), P=String("/c calc"))}, "active-content.launch"),
    ({}, "active-content.launch"),
], ids=["relative-document", "relative-file-spec", "executable", "drive", "network-share", "web-address",
        "windows-command", "no-target"])
def test_launch_of_a_relative_document_is_advisory_and_every_other_launch_dangerous(tmp_path, entries, code):
    pdf = write_pdf(tmp_path / "launch.pdf", link(Dictionary(S=Name.Launch, **entries)))
    assert [f.check for f in run(pdf)] == [code]


def test_open_action_that_reaches_a_web_address_through_next_actions_is_flagged(tmp_path):
    def build(pdf):
        visit = pdf.make_indirect(Dictionary(S=Name.URI, URI=String("https://example.org/seen.png")))
        pdf.Root.OpenAction = Dictionary(S=Name.GoTo, D=Array([pdf.pages[0].obj, Name.Fit]), Next=Array([visit]))
    (finding,) = run(write_pdf(tmp_path / "chain.pdf", build))
    assert (finding.check, finding.page, finding.evidence) == ("active-content.autoaction", None,
                                                               "https://example.org/seen.png")


def test_cycle_of_next_actions_ends_without_a_finding(tmp_path):
    def build(pdf):
        first = pdf.make_indirect(Dictionary(S=Name.GoTo, D=Array([pdf.pages[0].obj, Name.Fit])))
        second = pdf.make_indirect(Dictionary(S=Name.GoTo, D=Array([pdf.pages[0].obj, Name.Fit]), Next=first))
        first.Next = second
        pdf.Root.OpenAction = first
    assert run(write_pdf(tmp_path / "cycle.pdf", build)) == []


def test_open_action_that_stays_inside_the_pdf_gives_no_finding(tmp_path):
    def build(pdf):
        pdf.Root.OpenAction = Array([pdf.pages[0].obj, Name.Fit])
    assert run(write_pdf(tmp_path / "start-view.pdf", build)) == []


def test_clicked_web_link_and_remote_link_give_no_finding(tmp_path):
    def build(pdf):
        annotate(pdf, 1, Subtype=Name.Link, A=Dictionary(S=Name.URI, URI=String("https://doi.org/10.1145/1")))
        annotate(pdf, 1, Subtype=Name.Link, A=Dictionary(S=Name.GoToR, F=String("appendix.pdf"), D=Array([0, Name.Fit])))
    assert run(write_pdf(tmp_path / "links.pdf", build)) == []


def test_script_that_a_page_runs_on_opening_counts_as_javascript(tmp_path):
    def build(pdf):
        pdf.pages[0].obj.AA = Dictionary(O=Dictionary(S=Name.JavaScript, JS=String("app.beep(0);")))
    assert summary(run(write_pdf(tmp_path / "page-script.pdf", build))) == [("active-content.javascript", WARNING, 1)]


def test_embedded_document_that_a_page_opens_on_closing_is_an_automatic_action(tmp_path):
    def build(pdf):
        pdf.pages[0].obj.AA = Dictionary(C=Dictionary(S=Name.GoToE, T=Dictionary(R=Name.C, N=String("data.pdf"))))
    assert summary(run(write_pdf(tmp_path / "goto-embedded.pdf", build))) == [("active-content.autoaction", WARNING, 1)]


def test_form_that_imports_data_counts_as_a_form_submission(tmp_path):
    pdf = write_pdf(tmp_path / "import.pdf", link(Dictionary(S=Name.ImportData, F=String("answers.fdf"))))
    assert [(f.check, f.evidence) for f in run(pdf)] == [("active-content.submitform", "answers.fdf")]


def test_movie_embedded_in_the_pdf_gives_no_finding(tmp_path):
    def build(pdf):
        clip = Dictionary(Type=Name.Filespec, F=String("demo.mp4"), EF=Dictionary(F=pdf.make_stream(b"\x00" * 64)))
        annotate(pdf, 1, Subtype=Name.Movie, Movie=Dictionary(F=clip))
    assert run(write_pdf(tmp_path / "embedded-movie.pdf", build)) == []


@pytest.mark.parametrize(("embedded", "expected"), [(False, [("active-content.multimedia", INFO, 1)]), (True, [])])
def test_media_clip_is_advisory_only_when_played_from_a_file_outside_the_pdf(tmp_path, embedded, expected):
    def build(pdf):
        data = Dictionary(Type=Name.Filespec, F=String("demo.mp4"))
        if embedded:
            data.EF = Dictionary(F=pdf.make_stream(b"\x00" * 64))
        clip = Dictionary(S=Name.MCD, D=data)
        annotate(pdf, 1, Subtype=Name.Screen, A=Dictionary(S=Name.Rendition, R=Dictionary(S=Name.MR, C=clip)))
    assert summary(run(write_pdf(tmp_path / "clip.pdf", build))) == expected


def test_stream_with_its_data_in_an_external_file_is_an_external_reference(tmp_path):
    def build(pdf):
        traces = pdf.make_stream(b"")
        traces.F = String("traces.bin")
        pdf.Root.Traces = traces
    found = run(write_pdf(tmp_path / "external-stream.pdf", build))
    assert [(f.check, f.page, f.evidence) for f in found] == [("active-content.externalref", None, "traces.bin")]


def test_stream_whose_file_entry_names_no_file_gives_no_finding(tmp_path):
    def build(pdf):
        manifest = pdf.make_stream(b"c2pa manifest")
        manifest.F = Dictionary(Length=13, Subtype=String("application/c2pa"))
        pdf.Root.Manifest = manifest
    assert run(write_pdf(tmp_path / "credentials.pdf", build)) == []


def test_url_file_specification_of_a_remote_link_is_an_external_reference(tmp_path):
    def build(pdf):
        target = Dictionary(FS=Name.URL, F=String("https://example.org/appendix.pdf"))
        annotate(pdf, 2, Subtype=Name.Link, A=Dictionary(S=Name.GoToR, F=target, D=Array([0, Name.Fit])))
    found = run(write_pdf(tmp_path / "url-spec.pdf", build, pages=2))
    assert summary(found) == [("active-content.externalref", WARNING, 2)]


def test_object_on_two_pages_belongs_to_the_first(tmp_path):
    def build(pdf):
        shared = annotate(pdf, 2, Subtype=Name.Link, A=SCRIPT)
        pdf.pages[2].obj.Annots = Array([shared])
    (finding,) = run(write_pdf(tmp_path / "shared.pdf", build, pages=3))
    assert finding.page == 2 and finding.message.endswith("clicks in it")


def test_link_to_another_page_leaves_that_page_its_own_objects(tmp_path):
    def build(pdf):
        annotate(pdf, 1, Subtype=Name.Link, A=Dictionary(S=Name.GoTo, D=Array([pdf.pages[2].obj, Name.Fit])))
        annotate(pdf, 3, Subtype=Name.Link, A=SCRIPT)
    assert summary(run(write_pdf(tmp_path / "goto.pdf", build, pages=3))) == [("active-content.javascript", WARNING, 3)]


def test_nesting_beyond_the_depth_limit_ends_without_an_error_and_unread(tmp_path):
    def build(pdf):
        nested = Array([SCRIPT])
        for _ in range(200):
            nested = Array([nested])
        pdf.Root.Nested = nested
    assert run(write_pdf(tmp_path / "nested.pdf", build)) == []


def test_unreadable_pdf_gives_a_warning_that_names_no_path_or_file(tmp_path):
    bad = tmp_path / "icse2027-paper7.pdf"
    bad.write_bytes(b"not a pdf at all")
    for pdf in (bad, tmp_path / "icse2027-paper8.pdf", PAPERS / "corrupt.pdf"):
        (finding,) = run(pdf)
        assert (finding.check, finding.severity) == ("active-content.error", WARNING)
        assert str(pdf.parent) not in finding.message and pdf.name not in finding.message


def test_pdf_locked_with_a_password_gives_a_warning(tmp_path):
    locked = tmp_path / "locked.pdf"
    with pikepdf.open(FIXTURES / "javascript-open.pdf") as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(owner="author", user="reviewer"))
    assert summary(run(locked)) == [("active-content.error", WARNING, None)]


@pytest.mark.parametrize("name", ["javascript-animation", "javascript-open", "javascript-link", "clean"])
def test_every_script_that_the_hidden_text_check_reports_gives_a_javascript_finding(name):
    pdf = FIXTURES / f"{name}.pdf"
    hidden = {f.check for f in hidden_text.check(Paper(1, pdf), PROFILE, pdf.parent)}
    assert ("hidden-text.javascript" in hidden) == ("active-content.javascript" in {f.check for f in run(name)})
