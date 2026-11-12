"""Tests of the accessibility check on the tagged fixtures of tests/fixtures/accessibility, each built twice with
lualatex from the LaTeX source beside it, on the untagged text and paper fixtures, and on tagged PDFs that pikepdf
writes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pikepdf
import pymupdf
import pytest

from peercheck.findings import Severity
from peercheck.models import Paper
from peercheck.papers import accessibility
from peercheck.profile import ProfileError, load

ACCESSIBILITY = Path(__file__).parent / "fixtures" / "accessibility"
TEXT = Path(__file__).parent / "fixtures" / "text"
PAPERS = Path(__file__).parent / "fixtures" / "papers"
UNTAGGED = ["accessibility.untagged", "accessibility.no-language", "accessibility.no-title"]


def run(pdf: Path, **options) -> list:
    """Run the check, with its key in the template, on a PDF under the ICSE 2027 template with the given options."""
    profile = load("icse-2027")
    profile = dataclasses.replace(profile, checks={**profile.checks, "accessibility": options})
    return accessibility.check(Paper(1, pdf), profile, pdf.parent)


def test_check_stays_silent_while_the_template_leaves_out_its_key():
    assert accessibility.check(Paper(1, TEXT / "clean.pdf"), load("icse-2027"), TEXT) == []


def tagged_pdf(path: Path, *elements: dict, lang: str = "en-US", title: str = "Flaky Tests", marked=True,
               role_map: dict | None = None) -> Path:
    """Write a one-page tagged PDF whose document element holds the given structure elements."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[0].obj
    kids = pikepdf.Array(pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.StructElem, Pg=page, K=number, **element)) for number, element in enumerate(elements))
    document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, K=kids))
    tree = pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot, K=document)
    if role_map:
        tree.RoleMap = pikepdf.Dictionary({key: pikepdf.Name(value) for key, value in role_map.items()})
    pdf.Root.StructTreeRoot = pdf.make_indirect(tree)
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=marked)
    if lang:
        pdf.Root.Lang = pikepdf.String(lang)
    if title:
        pdf.docinfo["/Title"] = title
    pdf.save(path)
    return path


def figure(**keys) -> dict:
    """Return the keys of a structure element of the type Figure, or of the type that keys name."""
    return {"S": pikepdf.Name.Figure, **{key: pikepdf.String(value) if isinstance(value, str) and key != "S" else value
                                         for key, value in keys.items()}}


def test_tagged_paper_with_language_title_and_described_figures_gives_no_finding():
    assert run(ACCESSIBILITY / "tagged.pdf") == []


@pytest.mark.parametrize("pdf", [TEXT / "clean.pdf", PAPERS / "ieee-over-page-limit.pdf"], ids=["clean", "paper"])
def test_untagged_paper_gives_notes_on_the_tags_the_language_and_the_title(pdf):
    findings = run(pdf)
    assert [(f.check, f.severity, f.page) for f in findings] == [(code, Severity.INFO, None) for code in UNTAGGED]
    assert findings[0].message == "PDF is not tagged (no structure tree, /Marked not true in /MarkInfo)"


def test_required_option_turns_each_note_into_an_error():
    assert [(f.check, f.severity) for f in run(TEXT / "clean.pdf", required=True)] == [
        (code, Severity.ERROR) for code in UNTAGGED]


def test_required_option_that_is_no_boolean_raises():
    with pytest.raises(ProfileError):
        run(TEXT / "clean.pdf", required="yes")


def test_alt_text_that_only_names_the_image_file_leaves_the_figure_undescribed():
    (finding,) = run(ACCESSIBILITY / "tagged-missing-alt.pdf")
    assert (finding.check, finding.severity, finding.page) == ("accessibility.figure-alt", Severity.INFO, 1)
    assert finding.message == ("1 of 2 figures without alternative text (/Alt or /ActualText), 1 of them with only "
                               "the name of the image file")


def test_figure_without_alt_or_with_an_empty_alt_is_undescribed(tmp_path):
    pdf = tagged_pdf(tmp_path / "figures.pdf", figure(), figure(Alt="  "), figure(Alt="A chart of the failures."),
                     figure(ActualText=""), {"S": pikepdf.Name.P})
    (finding,) = run(pdf)
    assert (finding.check, finding.page) == ("accessibility.figure-alt", 1)
    assert finding.message == "2 of 4 figures without alternative text (/Alt or /ActualText)"


def test_custom_type_that_the_role_map_maps_to_figure_counts_as_a_figure(tmp_path):
    pdf = tagged_pdf(tmp_path / "roles.pdf", figure(S=pikepdf.Name("/Chart")), role_map={"/Chart": "/Graphic",
                                                                                         "/Graphic": "/Figure"})
    assert [f.message for f in run(pdf)] == ["1 of 1 figures without alternative text (/Alt or /ActualText)"]


def test_role_map_that_maps_in_a_circle_ends(tmp_path):
    pdf = tagged_pdf(tmp_path / "circle.pdf", figure(S=pikepdf.Name("/Chart")), role_map={"/Chart": "/Plot",
                                                                                          "/Plot": "/Chart"})
    assert run(pdf) == []


def test_structure_tree_that_refers_back_to_itself_ends(tmp_path):
    path = tagged_pdf(tmp_path / "loop.pdf", figure())
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        document = pdf.Root.StructTreeRoot.K
        document.K.append(document)
        pdf.save(path)
    assert [f.check for f in run(path)] == ["accessibility.figure-alt"]


def test_array_of_kids_that_holds_itself_ends(tmp_path):
    path = tagged_pdf(tmp_path / "self.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        kids = pdf.make_indirect(pikepdf.Array())
        kids.append(kids)
        kids.append(pikepdf.Dictionary(S=pikepdf.Name.Figure))
        pdf.Root.StructTreeRoot.K.K = kids
        pdf.save(path)
    assert [f.check for f in run(path)] == ["accessibility.figure-alt"]


def test_structure_tree_without_marked_true_is_untagged(tmp_path):
    (finding,) = run(tagged_pdf(tmp_path / "unmarked.pdf", marked=False))
    assert (finding.check, finding.message) == ("accessibility.untagged",
                                                "PDF is not tagged (/Marked not true in /MarkInfo)")


def test_language_that_is_no_language_tag_is_named(tmp_path):
    (finding,) = run(tagged_pdf(tmp_path / "language.pdf", lang="en_US"))
    assert (finding.check, finding.message) == ("accessibility.no-language",
                                                "document language 'en_US' is not a language tag")


def test_title_in_the_xmp_metadata_alone_counts(tmp_path):
    path = tagged_pdf(tmp_path / "xmp.pdf", title="")
    assert [f.check for f in run(path)] == ["accessibility.no-title"]
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            metadata["dc:title"] = "Flaky Tests"
        pdf.save(path)
    assert run(path) == []


def test_unreadable_pdf_gives_a_warning_that_names_no_path_or_file(tmp_path):
    bad = tmp_path / "icse2027-paper7.pdf"
    bad.write_bytes(b"not a pdf at all")
    for pdf in (bad, tmp_path / "icse2027-paper8.pdf"):
        (finding,) = run(pdf)
        assert (finding.check, finding.severity) == ("accessibility.error", Severity.WARNING)
        assert str(pdf.parent) not in finding.message and pdf.name not in finding.message


def test_pdf_locked_with_a_password_gives_a_warning(tmp_path):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Flaky tests pass and fail.", fontname="tiro")
    document.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="user", owner_pw="owner")
    assert [(f.check, f.severity) for f in run(tmp_path / "locked.pdf")] == [
        ("accessibility.error", Severity.WARNING)]
