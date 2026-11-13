"""Tests of the reader of the reference list, on fixtures built twice with pdflatex and on pages that a test draws.

The comment at the top of each LaTeX source names the entries that its fixture is built around.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from peercheck.papers import reference_list

FIXTURES = Path(__file__).parent / "fixtures"
SPLIT = FIXTURES / "reference-list" / "ieee-split-entries.pdf"
FOREIGN_TEXT = FIXTURES / "reference-list" / "ieee-journal-foreign-text.pdf"
ACCENTS = FIXTURES / "reference-list" / "ieee-ot1-accents.pdf"
LOOP_ENTRY = ("Q. Author and R. Author, “Made-up title number {} on the maintenance of stable branches and the porting "
              "of patches,” in Proc. Int. Conf. Softw. Testing, Verification and Validation, 2020, pp. 1–10.")
FOOTER = "Manuscript submitted to a made-up venue"
BODY = "A line of the made-up body text of the paper."
WIDE_BODY = "A line of the made-up body text of the paper that runs across the whole width of the made-up page."
GUTTER_BODY = "A line of the made-up body text of the paper, up to the gutter."
# The two halves of a running head, which change places and words between even and odd pages.
EVEN_HEAD = [(50, 40, "Made-up Venue, July 2026"), (460, 40, "A. Author and B. Author")]
ODD_HEAD = [(50, 40, "A Made-up Paper on Patches"), (440, 40, "Made-up Venue, July 2026")]
NUMBERED = "{name}. Author, A made-up title on the porting of patches to stable branches, in Proc. Conf., {year}."
HANGING = "{name}. Author. {year}. A made-up title on the porting of patches. In Proc. Conf. {number}1-{number}9."


def texts(pdf: Path) -> list[str]:
    return [entry.text for entry in reference_list.read(pdf)]


def draw(path: Path, *pages: list[tuple]) -> Path:
    """Write a PDF with one page per group of lines, each line as (x, y, text) or (x, y, text, font size).

    A group may also hold rules, each as (x, y, right end)."""
    with pymupdf.open() as document:
        for lines in pages:
            page = document.new_page(width=612, height=792)
            for x, y, text, *size in lines:
                if isinstance(text, str):
                    page.insert_text((x, y), text, fontsize=size[0] if size else 9, fontname="helv")
                else:
                    page.draw_line((x, y), (text, y), width=0.4)
        document.save(path)
    return path


def column(*rows: tuple, top: float = 100, pitch: float = 11) -> list[tuple]:
    """Place rows below each other at one pitch, each row as (x, text) or (x, text, font size)."""
    return [(x, top + pitch * index, text, *size) for index, (x, text, *size) in enumerate(rows)]


def stretched(x: float, y: float, text: str, gap: float) -> list[tuple]:
    """Place the words of a line a wide gap apart, each as a text run of its own, as in a line that TeX stretches."""
    rows = []
    for word in text.split():
        rows.append((x, y, word))
        x += pymupdf.get_text_length(word, fontname="helv", fontsize=9) + gap
    return rows


def numbered_entries(x: float, names: str, first: int = 1) -> list[tuple]:
    """Return the rows of numbered entries of two lines each, with the labels at x."""
    return [row for number, name in enumerate(names, start=first) for row in (
        (x, f"[{number}] {name}. Author, A made-up title on the porting of patches"),
        (x + 18, f"to stable branches, in Proc. Conf., {2019 + number}."))]


def hanging_entries(x: float, names: str, first: int = 1) -> list[tuple]:
    """Return the rows of entries without labels of two lines each, with the first lines at x."""
    return [row for number, name in enumerate(names, start=first) for row in (
        (x, f"{name}. Author. {2019 + number}. A made-up title on the porting"),
        (x + 12, f"of patches. In Proc. Conf. {number}1-{number}9."))]


def hanging_texts(names: str) -> list[str]:
    return [HANGING.format(name=name, year=2019 + number, number=number) for number, name in enumerate(names, start=1)]


def numbers_beside(rows: list[tuple], x: float, first: int = 1, every: int = 1) -> list[tuple]:
    """Return the line number of each row in small type at x, or of every few rows, as the lineno package prints."""
    return [(x, y, str(first + index), 5) for index, (_x, y, *_text) in enumerate(rows)
            if (first + index) % every == 0]


def span(*words: tuple[str, float], size: float = 8.0) -> reference_list.Span:
    """Return a span without space glyphs whose words each stand a gap apart, as a share of the font size."""
    glyphs, x = [], 50.0
    for word, gap in words:
        for letter in word:
            glyphs.append((letter, x, x + 0.5 * size))
            x += 0.5 * size
        x += gap * size
    return reference_list.Span(50.0, 100.0, glyphs[-1][2], 100.0 + size, size, "".join(word for word, _gap in words),
                               tuple(glyphs))


def test_every_entry_of_a_list_over_columns_and_pages_is_read_once():
    entries = reference_list.read(SPLIT)
    assert [entry.number for entry in entries] == list(range(1, 75))
    assert [entry.text for entry in entries[7:]] == [LOOP_ENTRY.format(number) for number in range(8, 75)]


def test_entry_that_ends_in_the_next_column_leaves_out_the_footnote_between():
    assert texts(SPLIT)[1] == (
        "C. Marsh, D. Okafor, E. Lindqvist, F. Abara, G. Petrov, and H. Yilmaz, “Do the stable branches of long-lived "
        "open source projects receive the fixes that the users of these branches need?” in Proc. Int. Conf. Softw. "
        "Eng., 2022, pp. 44–55.")


def test_entry_that_ends_on_the_next_page_is_whole():
    assert texts(SPLIT)[22] == LOOP_ENTRY.format(23)


def test_line_that_tex_stretches_keeps_its_words_in_their_order():
    assert texts(SPLIT)[2] == ("F. Tanaka and G. He, “Portbench: A Benchmark-of-backported-patches-for-large-language-"
                               "models,” arXiv preprint arXiv:2401.00001, 2024.")


def test_line_that_opens_like_the_heading_of_an_appendix_stays_in_its_entry():
    assert texts(SPLIT)[3].endswith("open source projects, with supplementary material on the conflicts of 40 "
                                    "projects,” Empirical Softw. Eng., vol. 28, no. 3, pp. 1–34, 2023.")


def test_link_over_two_lines_is_read_without_a_space():
    assert texts(SPLIT)[6].endswith("Available: https://example.org/made-up-project/documentation/maintainers/"
                                    "stable-branches/backport-policy.html")


@pytest.mark.parametrize(("fixture", "count"), [
    ("papers/article-a4-12pt.pdf", 2), ("papers/ieee-9pt-option.pdf", 11), ("papers/ieee-linespread.pdf", 11),
    ("papers/ieee-over-page-limit.pdf", 11), ("margins/acm-review.pdf", 2), ("margins/ieee-clean.pdf", 4),
    ("density/template-acmsmall.pdf", 1),
])
def test_each_layout_gives_one_entry_per_reference(fixture, count):
    assert len(reference_list.read(FIXTURES / fixture)) == count


@pytest.mark.parametrize(("fixture", "count"), [("ieee-refs-start-p10.pdf", 174),
                                                ("ieee-three-reference-pages.pdf", 199)])
def test_number_at_one_place_of_every_entry_does_not_split_the_column(fixture, count):
    assert texts(FIXTURES / "papers" / fixture) == [
        f"A. Author and B. Author, “Title of reference number {number} on software maintenance,” in Proc. ICSE, 2020, "
        "pp. 1–10." for number in range(1, count + 1)]


def test_line_numbers_of_a_review_version_stay_out_of_the_entries():
    assert texts(FIXTURES / "papers" / "acm-small-review.pdf") == [
        f"A. Author and B. Author. 2020. Title of reference number {number} on software maintenance. "
        "In Proc. FSE. 1–10."
        for number in range(1, 40)]


def test_line_numbers_in_the_gutter_that_the_lines_of_the_left_column_touch_stay_out_of_the_entries(tmp_path):
    left = column(*[(50, GUTTER_BODY)] * 6, (50, "References"), *numbered_entries(50, "AB"))
    right = column(*numbered_entries(320, "CDEFG", first=3))
    pdf = draw(tmp_path / "gutter-numbers.pdf", [
        *left, *numbers_beside(left, 30), *right, *numbers_beside(right, 290, first=len(left) + 1)])
    assert texts(pdf) == [NUMBERED.format(name=name, year=2019 + number)
                          for number, name in enumerate("ABCDEFG", start=1)]


def test_line_numbers_of_a_short_right_column_go_on_with_the_count_of_the_left_column(tmp_path):
    left = column(*[(50, BODY)] * 4, (50, "References"), *numbered_entries(50, "ABC"))
    right = column(*numbered_entries(320, "DE", first=4))
    pdf = draw(tmp_path / "short-column.pdf", [
        *left, *numbers_beside(left, 30), *right, *numbers_beside(right, 570, first=len(left) + 1)])
    assert texts(pdf) == [NUMBERED.format(name=name, year=2019 + number)
                          for number, name in enumerate("ABCDE", start=1)]


@pytest.mark.parametrize("tail", [1, 3])
def test_line_numbers_of_a_short_last_page_go_on_with_the_count_of_the_page_before(tmp_path, tail):
    rows = [(72, "[3] C. Author, A third made-up title on the porting of patches to the stable branches"),
            *[(90, f"of the made-up projects that the maintainers keep, as line {line} of the entry tells,")
              for line in range(2, tail + 1)],
            (90, "in Proc. Conf., 2022, pp. 21-30.")]
    first = column(*[(72, WIDE_BODY)] * 6, (72, "References"), *numbered_entries(72, "AB"), *rows[:-tail])
    last = column(*rows[-tail:])
    pdf = draw(tmp_path / "short-page.pdf", [*first, *numbers_beside(first, 50)],
               [*last, *numbers_beside(last, 50, first=len(first) + 1)])
    assert texts(pdf)[2] == " ".join(text.removeprefix("[3] ") for _x, text in rows)


def test_line_numbers_beside_a_double_spaced_list_stay_out_of_the_entries(tmp_path):
    rows = column(*[(72, WIDE_BODY)] * 4, (72, "References"), *numbered_entries(72, "ABCD"), pitch=22)
    pdf = draw(tmp_path / "double-spacing.pdf", [*rows, *numbers_beside(rows, 50, first=486)])
    assert texts(pdf) == [NUMBERED.format(name=name, year=2019 + number) for number, name in enumerate("ABCD", start=1)]


def test_numbers_one_entry_apart_beside_a_double_spaced_list_are_no_line_numbers(tmp_path):
    rows = column((72, "References"), *hanging_entries(72, "ABCDEFGHI"), pitch=22)
    labels = [(50, y, str(number)) for number, (_x, y, _text) in enumerate(rows[1::2], start=1)]
    pdf = draw(tmp_path / "bare-labels.pdf", [*rows, *labels])
    assert [text.split()[0] for text in texts(pdf)] == [str(number) for number in range(1, 10)]


def test_number_of_every_fifth_line_goes_on_with_the_count_of_the_page_before(tmp_path):
    body = column(*[(72, WIDE_BODY.replace("body text", "introduction"))] * 20, pitch=22)
    first = column(*[(72, WIDE_BODY)] * 11, (72, "References"), *numbered_entries(72, "ABCD"), pitch=22)
    last = column(*numbered_entries(72, "EFGHIJ", first=5), pitch=22)
    pdf = draw(tmp_path / "every-fifth-line.pdf", [*body, *numbers_beside(body, 50, every=5)],
               [*first, *numbers_beside(first, 50, first=21, every=5)],
               [*last, *numbers_beside(last, 50, first=41, every=5)])
    assert texts(pdf) == [NUMBERED.format(name=name, year=2019 + number)
                          for number, name in enumerate("ABCDEFGHIJ", start=1)]


def test_dotted_labels_start_the_entries_and_a_number_out_of_order_starts_none(tmp_path):
    pdf = draw(tmp_path / "dotted.pdf", column(
        (72, "References"),
        (72, "1. Author, A.: A first made-up title on the porting of patches. Lecture Notes in Made-up Science, vol."),
        (84, "17. Meadow Press, Springfield (2020)"),
        (72, "2. Author, B.: A second made-up title on the porting of patches. In: Proc. Conf., pp. 1-10 (2021)"),
        (72, "3. Author, C.: A third made-up title on the porting of patches. In: Proc. Conf., pp. 11-20 (2022)")))
    assert texts(pdf) == [
        ("Author, A.: A first made-up title on the porting of patches. Lecture Notes in Made-up Science, vol. 17. "
         "Meadow Press, Springfield (2020)"),
        "Author, B.: A second made-up title on the porting of patches. In: Proc. Conf., pp. 1-10 (2021)",
        "Author, C.: A third made-up title on the porting of patches. In: Proc. Conf., pp. 11-20 (2022)"]


def test_numbered_line_at_the_margin_of_the_entry_text_starts_no_entry(tmp_path):
    pdf = draw(tmp_path / "volume-number.pdf", column(
        (72, "References"),
        (72, "1. Author, A.: A first made-up title on the porting of patches. Lecture Notes in Made-up Science, vol."),
        (84, "2. Meadow Press, Springfield (2020)"),
        (72, "2. Author, B.: A second made-up title on the porting of patches. In: Proc. Conf., pp. 1-10 (2021)"),
        (72, "3. Author, C.: A third made-up title on the porting of patches. In: Proc. Conf., pp. 11-20 (2022)")))
    assert texts(pdf) == [
        ("Author, A.: A first made-up title on the porting of patches. Lecture Notes in Made-up Science, vol. 2. "
         "Meadow Press, Springfield (2020)"),
        "Author, B.: A second made-up title on the porting of patches. In: Proc. Conf., pp. 1-10 (2021)",
        "Author, C.: A third made-up title on the porting of patches. In: Proc. Conf., pp. 11-20 (2022)"]


def test_label_with_more_digits_starts_its_entry_to_the_left_of_the_label_above_it(tmp_path):
    entry = "Author, A.: Made-up title number {} on the porting of patches. In: Proc. Conf., pp. 1-10 (2020)"
    pdf = draw(tmp_path / "longer-labels.pdf", column(
        (72, "References"),
        *[(72 if number < 10 else 67, f"{number}. " + entry.format(number)) for number in range(1, 12)]))
    assert texts(pdf) == [entry.format(number) for number in range(1, 12)]


def test_labels_of_letters_start_the_entries(tmp_path):
    pdf = draw(tmp_path / "keys.pdf", column(
        (72, "References"),
        (72, "[Aut20] A. Author. A first made-up title on the porting of patches. In Proc. Conf., pages 1-10, 2020."),
        (72, "[AB21] A. Author and B. Author. A second made-up title on the porting of patches. In Proc. Conf.,"),
        (110, "pages 11-20, 2021."),
        (72, "[ABC+22] A. Author et al. A third made-up title on the porting of patches. In Proc. Conf., 2022.")))
    assert texts(pdf) == [
        "A. Author. A first made-up title on the porting of patches. In Proc. Conf., pages 1-10, 2020.",
        "A. Author and B. Author. A second made-up title on the porting of patches. In Proc. Conf., pages 11-20, 2021.",
        "A. Author et al. A third made-up title on the porting of patches. In Proc. Conf., 2022."]


@pytest.mark.parametrize("labels", [("[Abe20]", "[Mül22]", "[Özt24]"), ("[Abe20]", "[M¨ul22]", "[Ozt24]¨")])
def test_labels_of_letters_with_accents_start_the_entries(tmp_path, labels):
    pdf = draw(tmp_path / "accented-keys.pdf", column((72, "References"), *[
        (72, f"{label} {name}. Author. A made-up title on the porting of patches. In Proc. Conf., pages 1-10, 2020.")
        for label, name in zip(labels, "ABC")]))
    assert texts(pdf) == [f"{name}. Author. A made-up title on the porting of patches. In Proc. Conf., pages 1-10, "
                          "2020." for name in "ABC"]


def test_entries_without_labels_start_at_the_lines_that_hang_out_to_the_left(tmp_path):
    pdf = draw(tmp_path / "hanging.pdf", column(
        (72, "References"),
        (72, "A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up"),
        (84, "project. In Proc. Conf. 1-10."),
        (72, "B. Author. 2021. A second made-up title on the porting of patches. In Proc. Conf. 11-20.")))
    assert texts(pdf) == [
        ("A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up "
         "project. In Proc. Conf. 1-10."),
        "B. Author. 2021. A second made-up title on the porting of patches. In Proc. Conf. 11-20."]


def test_end_of_an_entry_alone_on_the_next_page_of_a_list_without_labels_stays_in_its_entry(tmp_path):
    pdf = draw(tmp_path / "tail-page.pdf", column(
        (72, "References"),
        (72, "A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up"),
        (84, "project. In Proc. Conf. 1-10."),
        (72, "B. Author. 2021. A second made-up title on the porting of patches to the stable branches of a made-up")),
        [(84, 100, "project. In Proc. Conf. 11-20.")])
    assert texts(pdf) == [
        ("A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up "
         "project. In Proc. Conf. 1-10."),
        ("B. Author. 2021. A second made-up title on the porting of patches to the stable branches of a made-up "
         "project. In Proc. Conf. 11-20.")]


def test_entry_alone_on_the_next_page_of_a_list_without_labels_starts_after_an_entry_that_ended(tmp_path):
    pdf = draw(tmp_path / "entry-page.pdf", column(
        (72, "References"),
        (72, "A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up"),
        (84, "project. In Proc. Conf. 1-10.")),
        [(72, 100, "B. Author. 2021. A second made-up title on the porting of patches. In Proc. Conf. 11-20.")])
    assert texts(pdf) == [
        ("A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up "
         "project. In Proc. Conf. 1-10."),
        "B. Author. 2021. A second made-up title on the porting of patches. In Proc. Conf. 11-20."]


def test_end_of_an_entry_alone_in_the_next_column_of_a_list_without_labels_stays_in_its_entry(tmp_path):
    pdf = draw(tmp_path / "tail-column.pdf", [*column(
        (50, "References"),
        (50, "A. Author. 2020. A first made-up title on the"),
        (62, "porting of patches to the stable branches"),
        (62, "of a made-up project. In Proc. Conf. 1-10."),
        (50, "B. Author. 2021. A second made-up title on the"),
        (62, "porting of patches to the stable branches of several")),
        *column((332, "made-up projects that the maintainers keep for"),
                (332, "years, with the fixes that the users of these"),
                (332, "branches need, and with the tests of the fixes."),
                (332, "In Proc. Conf. 11-20."))])
    assert texts(pdf) == [
        ("A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up "
         "project. In Proc. Conf. 1-10."),
        ("B. Author. 2021. A second made-up title on the porting of patches to the stable branches of several "
         "made-up projects that the maintainers keep for years, with the fixes that the users of these branches "
         "need, and with the tests of the fixes. In Proc. Conf. 11-20.")]


def test_list_ends_at_the_heading_of_an_appendix(tmp_path):
    pdf = draw(tmp_path / "appendix.pdf", column(
        (72, "References"),
        (72, "[1] A. Author, A first made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."),
        (72, "[2] B. Author, A second made-up title on the porting of patches, in Proc. Conf., 2021, pp. 11-20."),
        (72, "A Appendix", 12),
        (72, "[3] is the label of a made-up list item of the appendix that names no cited work at all.")))
    assert len(texts(pdf)) == 2


@pytest.mark.parametrize("heading", ["References Cited", "REFERENCES CITED", "References:", "7. References:",
                                     "Bibliography:"])
def test_heading_that_ends_in_cited_or_in_a_colon_opens_the_list(tmp_path, heading):
    pdf = draw(tmp_path / "heading.pdf", column(
        (72, BODY), (72, heading, 12),
        (72, "[1] A. Author, A made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10.")))
    assert texts(pdf) == ["A. Author, A made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."]


@pytest.mark.parametrize("heading", ["Selected References", "Literature", "Further Reading", "References: a list"])
def test_heading_that_names_a_part_of_the_literature_opens_no_list(tmp_path, heading):
    pdf = draw(tmp_path / "heading.pdf", column(
        (72, BODY), (72, heading, 12),
        (72, "[1] A. Author, A made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10.")))
    assert texts(pdf) == []


def test_last_heading_of_the_pdf_opens_the_list(tmp_path):
    pdf = draw(tmp_path / "two-headings.pdf", column(
        (72, "References"),
        (72, "[1] A line of a made-up table of contents that follows the word references on an early page."),
        (72, "[2] A second line of the made-up table of contents on the early page.")), column(
        (72, "References"),
        (72, "[1] A. Author, A made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10.")))
    assert texts(pdf) == ["A. Author, A made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."]


def test_footer_of_every_page_stays_out_of_an_entry_that_reaches_down_to_it(tmp_path):
    body = column(*[(72, "A line of the made-up body text of the paper that runs across the page.")] * 12)
    entries = [(72 if line % 2 == 0 else 90,
                f"[{line // 2 + 1}] A. Author, A made-up title on the porting of patches to the stable branches"
                if line % 2 == 0 else "of made-up projects, in Proc. Conf., 2020, pp. 1-10.") for line in range(53)]
    pdf = draw(tmp_path / "footer.pdf",
               [*body, (72, 698, FOOTER)], [*body, (72, 698, FOOTER)],
               [*column((72, "References"), *entries), (72, 698, FOOTER)],
               [(90, 100, "of made-up projects, in Proc. Conf., 2020, pp. 1-10."), (72, 698, FOOTER)])
    found = texts(pdf)
    assert len(found) == 27
    assert set(found) == {("A. Author, A made-up title on the porting of patches to the stable branches of made-up "
                           "projects, in Proc. Conf., 2020, pp. 1-10.")}


def test_running_heads_that_differ_on_even_and_odd_pages_stay_out_of_a_list_on_the_last_two_of_three_pages(tmp_path):
    body = [*column(*[(50, BODY)] * 8), *column(*[(320, BODY)] * 8)]
    pdf = draw(tmp_path / "three-pages.pdf", body, [
        *EVEN_HEAD,
        *column(*[(50, BODY)] * 3, (50, "References"), *hanging_entries(50, "AB"),
                (50, "C. Author. 2022. A made-up title on the porting")),
        *column((332, "of patches. In Proc. Conf. 31-39."), *hanging_entries(320, "DE", first=4),
                (320, "F. Author. 2025. A made-up title on the porting"))], [
        *ODD_HEAD,
        *column((62, "of patches. In Proc. Conf. 61-69."), *hanging_entries(50, "GH", first=7)),
        *column(*hanging_entries(320, "IJ", first=9))])
    assert texts(pdf) == hanging_texts("ABCDEFGHIJ")


def test_running_head_of_a_page_with_an_empty_right_column_stays_out_of_the_entries(tmp_path):
    body = [*column(*[(50, BODY)] * 8), *column(*[(320, BODY)] * 8)]
    pdf = draw(tmp_path / "left-column-only.pdf", [*EVEN_HEAD, *body], [*ODD_HEAD, *body], [
        *EVEN_HEAD,
        *column(*[(50, BODY)] * 4, (50, "References"), *hanging_entries(50, "ABC")),
        *column(*hanging_entries(320, "DEFG", first=4), (320, "H. Author. 2027. A made-up title on the porting"))], [
        *ODD_HEAD,
        *column((62, "of patches. In Proc. Conf. 81-89."), *hanging_entries(50, "IJ", first=9))],
        EVEN_HEAD)
    assert texts(pdf) == hanging_texts("ABCDEFGHIJ")


def test_last_page_whose_right_column_holds_one_line_is_read_in_two_columns(tmp_path):
    pdf = draw(tmp_path / "one-line-column.pdf", [
        *column((50, "References"), *numbered_entries(50, "ABC")), *column(*numbered_entries(320, "DEF", first=4))], [
        *column(*numbered_entries(50, "GH", first=7),
                (50, "[9] M. Author, A made-up title on the porting of patches")),
        (338, 100, "to stable branches, in Proc. Conf., 2028.")])
    assert texts(pdf) == [NUMBERED.format(name=name, year=2019 + number)
                          for number, name in enumerate("ABCDEFGHM", start=1)]


def test_last_page_of_a_one_column_list_with_a_stretched_line_is_read_in_one_column(tmp_path):
    link = "https://example.org/made-up-project/documentation/maintainers/stable-branches/backport-policy.html"
    pdf = draw(tmp_path / "stretched-line.pdf", column(
        *[(72, WIDE_BODY)] * 12, (72, "References"),
        (72, "[1] A. Author, A first made-up title on the porting of patches to the stable branches, in Proc. Conf."),
        (72, "[2] B. Author, A second made-up title on the porting of patches to the stable branches, in Proc. Conf.")),
        [(72, 100, "[3] C. Author, A third made-up title on the porting of patches to the stable branches of made-up"),
         *stretched(90, 111, "projects, with a guide that the maintainers of all the stable branches keep online,", 10),
         (90, 122, link)])
    assert texts(pdf)[2] == (
        "C. Author, A third made-up title on the porting of patches to the stable branches of made-up projects, with "
        f"a guide that the maintainers of all the stable branches keep online, {link}")


def test_lines_of_a_widely_spaced_list_that_read_alike_on_two_pages_stay_in_their_entries(tmp_path):
    rows = [row for number in range(1, 12) for row in (
        (72, f"[{number}] A. Author, A made-up title on the porting of patches to the stable branches"),
        (90, f"of made-up projects, in Proc. Conf., {2019 + number}, pp. {number}1-{number}9."))]
    pdf = draw(tmp_path / "wide-spacing.pdf",
               column(*[(72, WIDE_BODY)] * 4, (72, "References"), *rows[:3], pitch=22),
               column(*rows[3:11], pitch=22), column(*rows[11:], pitch=22))
    assert texts(pdf) == [
        "A. Author, A made-up title on the porting of patches to the stable branches of made-up projects, in Proc. "
        f"Conf., {2019 + number}, pp. {number}1-{number}9." for number in range(1, 12)]


def test_last_entry_keeps_its_few_lines_below_a_footnote(tmp_path):
    pdf = draw(tmp_path / "tail.pdf", column(
        (72, "References"),
        (72, "[1] A. Author, A first made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."),
        (72, "[2] B. Author, A second made-up title on the porting of patches to the stable branches"),
        (72, "A made-up footnote in smaller type that stands below the first lines of the last entry.", 7),
        (90, "of made-up projects, in Proc. Conf., 2021, pp. 11-20.")))
    assert texts(pdf)[1] == ("B. Author, A second made-up title on the porting of patches to the stable branches of "
                             "made-up projects, in Proc. Conf., 2021, pp. 11-20.")


def test_long_text_below_a_footnote_stays_out_of_the_last_entry(tmp_path):
    pdf = draw(tmp_path / "text-after.pdf", column(
        (72, "References"),
        (72, "[1] A. Author, A first made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."),
        (72, "[2] B. Author, A second made-up title on the porting of patches, in Proc. Conf., 2021, pp. 11-20."),
        (72, "A made-up footnote in smaller type that stands below the last entry.", 7),
        *[(72, "A line of made-up text in the type of the list that follows the footnote on the page.")] * 9))
    assert texts(pdf)[1] == ("B. Author, A second made-up title on the porting of patches, "
                             "in Proc. Conf., 2021, pp. 11-20.")


def test_caption_at_the_top_of_a_column_stays_out_of_the_entry_that_goes_on_below_it(tmp_path):
    pdf = draw(tmp_path / "caption.pdf", [*column(
        (50, "References"),
        (50, "[1] A. Author, A first made-up title on the"), (68, "porting of patches, in Proc. Conf., 2020."),
        (50, "[2] B. Author, A second made-up title on the"), (68, "porting of patches, in Proc. Conf., 2021."),
        (50, "[3] C. Author, A third made-up title on the"), (68, "porting of patches to the stable branches of")),
        *column((320, "Fig. 1. A made-up caption of a figure in the"),
                (320, "type of the list, at the top of its column.")),
        *column((338, "a made-up project, in Proc. Conf., 2022."),
                (320, "[4] D. Author, A fourth made-up title on the"),
                (338, "porting of patches, in Proc. Conf., 2023."),
                (320, "[5] E. Author, A fifth made-up title on the"),
                (338, "porting of patches, in Proc. Conf., 2024."),
                (320, "[6] F. Author, A sixth made-up title on the"),
                (338, "porting of patches, in Proc. Conf., 2025."), top=160)])
    found = texts(pdf)
    assert len(found) == 6
    assert found[2] == ("C. Author, A third made-up title on the porting of patches to the stable branches of "
                        "a made-up project, in Proc. Conf., 2022.")
    assert found[5] == "F. Author, A sixth made-up title on the porting of patches, in Proc. Conf., 2025."


def test_text_in_the_type_of_the_list_in_the_column_after_the_list_stays_out_of_the_last_entry(tmp_path):
    entries = [row for number, name in enumerate("ABCD", start=1) for row in (
        (50, f"[{number}] {name}. Author, A made-up title on the porting of patches"),
        (68, f"to stable branches, in Proc. Conf., {2019 + number}."))]
    pdf = draw(tmp_path / "column-after.pdf", [
        *column(*[(50, "A line of the made-up body text of the paper.")] * 8, (50, "References"), *entries),
        *column(*[(320, "A line of the made-up body text of the paper.")] * 8)])
    assert texts(pdf) == [(f"{name}. Author, A made-up title on the porting of patches to stable branches, "
                           f"in Proc. Conf., {2019 + number}.") for number, name in enumerate("ABCD", start=1)]


def test_entry_goes_on_in_the_next_column_after_a_short_line_that_ends_inside_a_link(tmp_path):
    entries = [row for number, name in enumerate("ABC", start=1) for row in (
        (50, f"[{number}] {name}. Author, A made-up title on the porting of patches"),
        (68, f"to stable branches, in Proc. Conf., {2019 + number}."))]
    pdf = draw(tmp_path / "link-over-columns.pdf", [
        *column(*[(50, "A line of the made-up body text of the paper.")] * 8, (50, "References"), *entries,
                (50, "[4] D. Author, A made-up page on the porting of patches,"),
                (68, "https://example.org/made-up-project/")),
        *column((338, "stable-branches.html, 2023."), *[(320, "A line of the made-up body text of the paper.")] * 8)])
    assert texts(pdf)[3] == ("D. Author, A made-up page on the porting of patches, "
                             "https://example.org/made-up-project/stable-branches.html, 2023.")


def test_footnote_caption_and_biographies_in_the_type_of_the_list_stay_out_of_the_entries():
    found = texts(FOREIGN_TEXT)
    assert len(found) == 8
    assert found[3] == ("H. Yilmaz, I. Petrov, and J. Abara, “Do the stable branches of long- lived projects receive "
                        "the fixes that the users of these branches need?” J. Made-up Softw. Evol., vol. 13, no. 1, "
                        "pp. 1–12, 2023.")
    assert found[4].endswith("Made-up Softw. Maintenance, 2024, pp. 301–312, Supplementary Material.")
    assert found[7] == ("O. Varga and P. Nilsen, “A made-up benchmark of backported patches,” J. Made-up Softw. Evol., "
                        "vol. 15, no. 4, pp. 120–131, 2025.")


def test_footnote_in_the_type_of_the_list_close_below_a_numbered_entry_stays_out_of_it(tmp_path):
    pdf = draw(tmp_path / "close-footnote.pdf", column(
        (72, "References"),
        (72, "[1] A. Author, A first made-up title on the porting of patches to the stable branches"),
        (90, "of made-up projects, in Proc. Conf., 2020, pp. 1-10."),
        (72, "[2] B. Author, A second made-up title on the porting of patches to the stable branches"),
        (90, "of made-up projects, in Proc. Conf., 2021, pp. 11-20."),
        (72, "[3] C. Author, A third made-up title on the porting of patches to the stable branches"),
        (90, "of made-up projects, in Proc. Conf., 2022, pp. 21-30."),
        (72, "1 A made-up footnote in the type of the list, which stands close below the last entry"),
        (72, "of its column.")))
    assert texts(pdf)[2] == ("C. Author, A third made-up title on the porting of patches to the stable branches "
                             "of made-up projects, in Proc. Conf., 2022, pp. 21-30.")


def test_lines_below_the_footnote_rule_of_a_list_without_labels_start_no_entries(tmp_path):
    pdf = draw(tmp_path / "ruled-footnote.pdf", [*column(
        (72, "References"),
        (72, "A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up"),
        (84, "project. In Proc. Conf. 1-10."),
        (72, "B. Author. 2021. A second made-up title on the porting of patches to the stable branches of a made-up"),
        (84, "project. In Proc. Conf. 11-20.")),
        (72, 152, 120),
        *column((72, "1 A made-up footnote in the type of the list, with enough words to fill two lines below the"),
                (72, "last entry of its column."), top=166)])
    assert texts(pdf) == [
        ("A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up "
         "project. In Proc. Conf. 1-10."),
        ("B. Author. 2021. A second made-up title on the porting of patches to the stable branches of a made-up "
         "project. In Proc. Conf. 11-20.")]


def test_rule_for_repeated_authors_in_the_first_line_of_an_entry_is_no_footnote_rule(tmp_path):
    pdf = draw(tmp_path / "repeated-authors.pdf", [*column(
        (72, "References"),
        (72, "A. Author. 2020. A first made-up title on the porting of patches to the stable branches of a made-up"),
        (84, "project. In Proc. Conf. 1-10."),
        (102, "2021. A second made-up title on the porting of patches. In Proc. Conf. 11-20."),
        (72, "B. Author. 2022. A third made-up title on the porting of patches. In Proc. Conf. 21-30.")),
        (72, 133, 99)])
    assert texts(pdf)[-1] == "B. Author. 2022. A third made-up title on the porting of patches. In Proc. Conf. 21-30."


@pytest.mark.parametrize("heading", ["A Proof of Theorem 1", "A Hyper-parameters of the Models",
                                     "A Additional Details for RQ2", "B. Results of the Second Study (RQ2)"])
def test_list_ends_at_the_section_heading_of_an_appendix_in_larger_type(tmp_path, heading):
    pdf = draw(tmp_path / "appendix-section.pdf", column(
        (72, "References"),
        (72, "A. Author. 2020. A first made-up title on the porting of patches. In Proc. Conf. 1-10."),
        (72, "B. Author. 2021. A second made-up title on the porting of patches. In Proc. Conf. 11-20."),
        (72, heading, 12),
        *[(72, "A line of the made-up text of the appendix, in the type of the list.")] * 3))
    assert len(texts(pdf)) == 2


def test_line_in_larger_type_between_numbered_entries_does_not_end_the_list(tmp_path):
    pdf = draw(tmp_path / "table-row.pdf", column(
        (72, "References"),
        (72, "[1] A. Author, A first made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."),
        (72, "A Baseline Without Caching", 11),
        (72, "[2] B. Author, A second made-up title on the porting of patches, in Proc. Conf., 2021, pp. 11-20."),
        (72, "[3] C. Author, A third made-up title on the porting of patches, in Proc. Conf., 2022, pp. 21-30.")))
    assert len(texts(pdf)) == 3


def test_short_last_line_of_a_numbered_entry_that_reads_like_an_end_heading_stays_in_its_entry(tmp_path):
    pdf = draw(tmp_path / "heading-like-line.pdf", column(
        (72, "References"),
        (72, "[1] A. Author, A first made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."),
        (72, "[2] B. Author, A second made-up title on the porting of patches, in Proc. Conf., 2021, pp. 11-20,"),
        (90, "Supplementary Material."),
        (72, "[3] C. Author, A third made-up title on the porting of patches, in Proc. Conf., 2022, pp. 21-30."),
        (72, "[4] D. Author, A fourth made-up title on the porting of patches, in Proc. Conf., 2023, pp. 31-40.")))
    found = texts(pdf)
    assert len(found) == 4
    assert found[1].endswith("in Proc. Conf., 2021, pp. 11-20, Supplementary Material.")


def test_entry_keeps_at_most_25_lines(tmp_path):
    pdf = draw(tmp_path / "long-entry.pdf", column(
        (72, "References"),
        (72, "[1] A. Author, A made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."),
        *[(90, f"made-up line {number} of the text that follows the list without a heading.")
          for number in range(2, 40)]))
    [entry] = texts(pdf)
    assert "made-up line 25 of" in entry and "made-up line 26 of" not in entry


def test_entry_of_many_lines_is_whole_when_the_next_entry_follows_it(tmp_path):
    pdf = draw(tmp_path / "many-authors.pdf", column(
        (72, "References"),
        (72, "[1] A. Author, B. Author, C. Author, D. Author, E. Author, F. Author, G. Author, H. Author,"),
        *[(90, f"I. Author{number}, J. Author{number}, K. Author{number}, L. Author{number}, M. Author{number},")
          for number in range(2, 40)],
        (90, "and N. Author, A made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10."),
        (72, "[2] O. Author, A second made-up title on the porting of patches, in Proc. Conf., 2021, pp. 11-20.")))
    first, second = texts(pdf)
    assert "M. Author39, and N. Author, A made-up title on the porting of patches, in Proc. Conf., 2020" in first
    assert second == "O. Author, A second made-up title on the porting of patches, in Proc. Conf., 2021, pp. 11-20."


def test_pdf_without_a_reference_heading_has_no_entries(tmp_path):
    pdf = draw(tmp_path / "no-list.pdf", column(
        (72, "[1] A. Author, A made-up title on the porting of patches, in Proc. Conf., 2020, pp. 1-10.")))
    assert reference_list.read(pdf) == []


def test_pdf_that_cannot_be_read_has_no_entries(tmp_path):
    assert reference_list.read(FIXTURES / "papers" / "corrupt.pdf") == []
    assert reference_list.read(tmp_path / "missing.pdf") == []


def test_pdf_that_asks_for_a_password_has_no_entries(tmp_path):
    with pymupdf.open(SPLIT) as document:
        document.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="made-up")
    assert reference_list.read(tmp_path / "locked.pdf") == []


def test_tight_line_gets_a_space_at_each_word_gap():
    row = [span(("on", 0.07), ("the", 0.07), ("maintenance", 0.07), ("of", 0.07), ("stable", 0.07), ("branches", 0))]
    assert reference_list._spaced(row) == "on the maintenance of stable branches"


def test_narrow_gap_inside_a_word_of_a_normal_line_adds_no_space():
    row = [span(("the", 0.3), ("pro", 0.07), ("ject", 0.3), ("of", 0.3), ("stable", 0.3), ("branches", 0))]
    assert reference_list._spaced(row) == "the project of stable branches"


def test_letters_that_stand_apart_one_by_one_in_a_tight_line_stay_one_word():
    row = [span(("see", 0.07), ("the", 0.07), ("made-up", 0.07), ("guide", 0.07), ("of", 0.07), ("the", 0.07),
                ("stable", 0.07), ("branches", 0.3), ("h", 0.07), ("t", 0.07), ("t", 0.07), ("p", 0))]
    assert reference_list._spaced(row) == "see the made-up guide of the stable branches http"


def test_narrow_gaps_of_several_widths_add_no_space():
    row = [span(("on", 0.05), ("the", 0.11), ("maintenance", 0.07), ("of", 0.09), ("stable", 0.06), ("branches", 0))]
    assert reference_list._spaced(row) == "onthemaintenanceofstablebranches"


def test_line_in_two_font_sizes_gets_no_space_at_a_narrow_gap():
    words = [("on", 0.07), ("the", 0.07), ("maintenance", 0.07), ("of", 0.07), ("stable", 0.07), ("branches", 0)]
    small = span(*words, size=6.4)
    shifted = tuple((letter, x0 + 200, x1 + 200) for letter, x0, x1 in small.glyphs)
    row = [span(*words), reference_list.Span(250.0, 100.0, 450.0, 108.0, 6.4, small.text, shifted)]
    assert reference_list._spaced(row) == "onthemaintenanceofstablebranches onthemaintenanceofstablebranches"


def test_accent_that_tex_draws_as_a_glyph_of_its_own_stands_on_the_letter_whose_box_holds_it():
    word = reference_list.Span(79.6, 445.0, 96.9, 453.0, 8.0, "P˘as˘ar", (
        ("P", 79.6, 84.0), ("˘", 84.5, 87.2), ("a", 84.0, 87.6), ("s", 87.6, 90.7), ("˘", 91.1, 93.8),
        ("a", 90.7, 94.2), ("r", 94.2, 96.9)))
    assert reference_list._spaced([word]) == "Păsăr"


def test_raised_accent_in_a_span_of_its_own_stands_on_the_capital_below_it():
    word = reference_list.Span(131.0, 445.0, 139.8, 453.0, 8.0, "Sli", (
        ("S", 131.0, 135.4), ("l", 135.4, 137.6), ("i", 137.6, 139.8)))
    accent = reference_list.Span(131.8, 443.2, 134.5, 451.1, 8.0, "´", (("´", 131.8, 134.5),))
    assert reference_list._spaced([word, accent]) == "Śli"


def test_accent_over_a_letter_without_its_dot_gives_the_letter_with_the_accent():
    word = reference_list.Span(50.0, 445.0, 64.0, 453.0, 8.0, "na¨ıve", (
        ("n", 50.0, 54.0), ("a", 54.0, 57.5), ("¨", 57.3, 60.0), ("ı", 57.5, 59.7), ("v", 59.7, 63.7),
        ("e", 63.7, 67.2)))
    assert reference_list._spaced([word]) == "naïve"


def test_mark_between_two_letters_stays_a_mark_of_its_own():
    word = reference_list.Span(50.0, 445.0, 62.2, 453.0, 8.0, "it´s", (
        ("i", 50.0, 52.2), ("t", 52.2, 54.4), ("´", 54.4, 57.1), ("s", 57.1, 60.2)))
    assert reference_list._spaced([word]) == "it´s"


def test_names_of_a_paper_without_a_font_encoding_read_with_each_accent_on_its_letter():
    entries = texts(ACCENTS)
    assert [entry.split(", “")[0] for entry in entries] == [
        "C. Părvenkmăr and Ś. Quíllfeather", "Ž. Oduñale and F. Lârsenbè",
        "Ö. Mirovič and Å. Tanakäwa", "Ő. Holliswőrth and Ż. Abernāthie",
        "Ç. Caştellane and D. Drużhkov"]
    assert "“Tracing naïve patches across the stable branches" in entries[0]


@pytest.mark.parametrize(("lines", "joined"), [
    (["[Online]. Available: https://example.org/tools/", "patch-porting/guide.html"],
     "[Online]. Available: https://example.org/tools/patch-porting/guide.html"),
    (["https://example.org/tools/guide", "-for-maintainers.html, 2024."],
     "https://example.org/tools/guide-for-maintainers.html, 2024."),
    (["https://example.org/made-up-proj", "ect/releases, 2024."],
     "https://example.org/made-up-project/releases, 2024."),
    (["http://example.org/v267/author25n.", "html"], "http://example.org/v267/author25n.html"),
    (["2020, doi: 10.5555/", "3377811.3380362."], "2020, doi: 10.5555/3377811.3380362."),
    (["https://doi.org/10.5555/3377811.", "3380362"], "https://doi.org/10.5555/3377811.3380362"),
    (["arXiv preprint arXiv:2401.", "00001, 2024."], "arXiv preprint arXiv:2401.00001, 2024."),
    (["closing017,” https:", "//example.org/made-up-project/", "tail017.html, 2024."],
     "closing017,” https://example.org/made-up-project/tail017.html, 2024."),
    (["[Online]. Available: http:/", "/example.org/tools/guide.html"],
     "[Online]. Available: http://example.org/tools/guide.html"),
    (["closing017. https:", "//example.org/maintainers/stable-branc", "hes/backport-policy/tail017.html (2018)"],
     "closing017. https://example.org/maintainers/stable-branches/backport-policy/tail017.html (2018)"),
    (["Meadow Press, Springfield, 12101–12109. doi:10", ".5555/made.021.1193715/record_464161443"],
     "Meadow Press, Springfield, 12101–12109. doi:10.5555/made.021.1193715/record_464161443"),
    (["Meadow Press, 2020, doi:1", "0.5555/made.021.1193715"], "Meadow Press, 2020, doi:10.5555/made.021.1193715"),
    (["pp. 1–12, doi: 10.55", "55/made.021.1193715."], "pp. 1–12, doi: 10.5555/made.021.1193715."),
])
def test_line_that_goes_on_with_a_link_joins_without_a_space(lines, joined):
    assert reference_list._joined(lines) == joined


@pytest.mark.parametrize("lines", [
    ["arXiv preprint arXiv:2401.00001", "2024."],
    ["arXiv:2401.00001", "https://arxiv.org/abs/2401.00001"],
    ["Available: https://example.org/tool/", "https://example.org/mirror/"],
    ["Available: https://example.org/tool", "Accessed: Mar. 2024."],
    ["Available: https://example.org/tool.", "(accessed in March 2024)"],
    ["https://doi.org/10.5555/3377811.3380362.", "Meadow Press, 2020."],
    ["https://example.org/tool", "2024"],
    ["Available: https://example.org/maintainers/stable/", "Accessed: 2024-03-01."],
    ["https://example.org/tools/guide-", "Retrieved: March 2024 from the made-up archive"],
    ["https://example.org/made-up-project/notes", "2024-03-01."],
])
def test_line_after_a_whole_link_joins_with_a_space(lines):
    assert reference_list._joined(lines) == " ".join(lines)


def test_gap_before_the_chapter_number_of_a_doi_becomes_its_underscore():
    assert reference_list._joined(["In: Proc. Conf. (2020). https://doi.org/10.1007/978-3-030-58475-7 16"]) == (
        "In: Proc. Conf. (2020). https://doi.org/10.1007/978-3-030-58475-7_16")
