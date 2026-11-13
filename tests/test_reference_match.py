"""Tests of the comparison of a reference with a database record, by the title and the authors of its entry."""

from __future__ import annotations

import pytest

from peercheck.papers import reference_match
from peercheck.papers.reference_match import Citation

TITLE = "A made-up title on the porting of patches"
ENTRY = f"A. Quill and B. Reed, “{TITLE},” in Proc. Int. Conf. Softw. Eng., 2021, pp. 101–112."
QUESTION = ("C. Marsh, D. Okafor, and E. Lindqvist, “Do stable branches receive the fixes they need?” in Proc. Int. "
            "Conf. Softw. Eng., 2022, pp. 44–55.")


def cited(entry: str = ENTRY, title: str = TITLE, authors=("A. Quill", "B. Reed")) -> Citation:
    return Citation(entry, title, authors)


@pytest.mark.parametrize("title", [
    TITLE, "A Made-Up Title on the Porting of Patches.", "A made-up title on the porting of patchs",
    "A made‐up title on the porting of patches"])
def test_reference_bears_a_title_that_is_nearly_the_title_that_hallucinator_read(title):
    assert cited().bears(title)


def test_reference_bears_a_title_that_stands_as_a_whole_field_of_its_entry():
    read = "Do stable branches receive the fixes they need?” in Proc"
    assert cited(QUESTION, read, ()).bears("Do stable branches receive the fixes they need?")


@pytest.mark.parametrize("year", ["(2021)", "[2021]", "(2021a)", "(in press)"])
def test_reference_bears_a_title_that_follows_a_year_in_parentheses_or_brackets(year):
    # The author-year style of Springer sets no period between the year and the title.
    entry = f"Quill A, Reed B {year} {TITLE}. Empir Softw Eng 26(3):1–34"
    assert cited(entry, f"{TITLE}. Empir Softw Eng", ("Quill A", "Reed B")).bears(TITLE)


@pytest.mark.parametrize("title", ["Stable branches receive the fixes", "Do stable branches receive the fixes",
                                   "branches receive the fixes they need"])
def test_reference_bears_no_title_that_is_a_part_of_a_field_of_its_entry(title):
    assert not cited(QUESTION, "Do stable branches receive the fixes they need?” in Proc", ()).bears(title)


def test_reference_bears_no_title_of_fewer_than_16_letters():
    entry = "A. Quill, “Deep patch search,” in Proc. Int. Conf. Softw. Eng., 2021."
    assert not cited(entry, "Deep patch search").bears("Deep patch search")


def test_reference_bears_a_title_whose_subtitle_its_entry_leaves_out():
    assert cited().bears(f"{TITLE}: A field study")


def test_reference_bears_a_title_without_the_subtitle_of_its_entry():
    long = f"{TITLE}: A field study of forty projects and their stable branches"
    assert cited(ENTRY.replace(TITLE, long), long).bears(TITLE)


def test_reference_bears_no_title_whose_part_before_a_colon_is_shorter_than_16_letters():
    entry = "A. Quill, “Patches,” in Proc. Int. Conf. Softw. Eng., 2021."
    assert not cited(entry, "Patches").bears("Patches: a made-up study of another matter entirely")


def test_accent_that_a_pdf_holds_as_a_mark_of_its_own_reads_as_the_accent_of_its_letter():
    entry = "J. Müller, “Über die Portierung von Korrekturen in stabile Zweige,” in Proc. Softw. Eng., 2021."
    read = "U¨ber die Portierung von Korrekturen in stabile Zweige"
    assert cited(entry, read, ("J. Müller",)).bears("Über die Portierung von Korrekturen in stabile Zweige")
    assert cited(entry, read, ("J. Müller",)).same_authors(["Jörg Müller"])


def test_entry_holds_the_words_of_the_name_of_its_venue_in_their_order():
    assert cited().holds_words("Proc. Int. Conf. Softw. Eng.")
    assert not cited().holds_words("Proc. Int. Softw. Conf. Eng.")
    assert not cited().holds_words("")


@pytest.mark.parametrize("authors", [(), ("张伟", "陈丽"), ("Иван Иванов",), ("X", "Y")])
def test_record_without_a_family_name_in_latin_letters_counts_as_a_record_of_the_cited_authors(authors):
    assert cited().same_authors(authors)


@pytest.mark.parametrize("group", ["The Made-up Collaboration", "Made-up Consortium", "Made-up Team",
                                   "The Made-up Working Group", "Made-up Project", "M. U. team"])
def test_name_of_a_group_gives_no_author_to_compare_in_an_entry_and_in_a_record(group):
    members = ["Hana Novak", "Petra Zeller", "Carla Marsh"]
    assert cited(ENTRY.replace("A. Quill and B. Reed", group), authors=(group,)).same_authors(members, TITLE)
    assert cited().same_authors([group])


def test_people_named_beside_a_group_are_compared_as_the_authors():
    names = ("A. Quill", "The Made-up Collaboration")
    assert cited(authors=names).same_authors(["Ada Quill", "Hana Novak"])
    assert not cited(authors=names).same_authors(["Hana Novak", "Petra Zeller"])
    assert cited().same_authors(["The Made-up Team", "Ada Quill"])
    assert not cited().same_authors(["The Made-up Team", "Hana Novak", "Petra Zeller"])


@pytest.mark.parametrize("company", ["Madeup-AI", "Madeupsoft", "Madeupsoft 0002"])
def test_only_author_of_a_record_under_one_word_is_an_organization_and_gives_no_author_to_compare(company):
    assert cited().same_authors([company])
    assert reference_match.compared_authors([company]) == []
    assert not cited().same_authors([company, "Hana Novak"])


def test_names_of_one_word_are_family_names_in_an_entry_and_in_a_record_of_several_authors():
    assert cited(authors=("Quill", "Reed")).same_authors(["Ada Quill", "Ben Reed"])
    assert not cited(authors=("Quill", "Reed")).same_authors(["Hana Novak", "Petra Zeller"])
    assert not cited(authors=("Quill",)).same_authors(["Hana Novak"])
    assert not cited().same_authors(["Novak", "Zeller"])


def test_given_name_of_a_cited_author_names_no_author_of_a_record():
    names = ("Thomas Brennan", "Kenji Ito")
    entry = ENTRY.replace("A. Quill and B. Reed", "Thomas Brennan and Kenji Ito")
    assert not cited(entry, authors=names).same_authors(["David Thomas"], TITLE)
    assert not cited(entry, authors=names).same_authors(["David Thomas", "Brenda Kenji"], TITLE)
    assert cited(entry, authors=names).same_authors(["Tom Brennan", "Kenji Ito"], TITLE)


@pytest.mark.parametrize(("names", "record", "same"), [
    (("J. Yang", "M. Lin"), ("Yang Liu", "Lin Chen", "Wei Zhang", "Yu Wang"), False),
    (("L. Yang", "C. Lin"), ("Yang Liu", "Lin Chen", "Wei Zhang", "Yu Wang"), True),
    (("Yang", "Lin"), ("Yang Liu", "Lin Chen", "Wei Zhang", "Yu Wang"), True),
    (("Kim Sung-Hun",), ("Sung-Hun Kim",), True),
    (("H. Garcia",), ("Hector Garcia-Molina",), True),
    (("P. Garcia",), ("Hector Garcia-Molina",), False)])
def test_cited_family_name_that_is_another_word_of_a_record_name_names_its_author_only_with_a_fitting_initial(
        names, record, same):
    entry = ENTRY.replace("A. Quill and B. Reed", " and ".join(names))
    assert cited(entry, authors=names).same_authors(record, TITLE) is same


@pytest.mark.parametrize(("names", "record", "same"), [
    (("A. Quill", "B. Reed", "C. Marsh", "D. Okafor"), ("Ada Quill", "Ben Reed", "Hana Novak"), True),
    (("A. Quill", "B. Reed", "C. Marsh"), ("Ada Quill", "Hana Novak", "Petra Zeller"), False),
    (("A. Quill", "B. Reed"), ("Hana Novak", "Petra Zeller"), False),
    (("W. Zhang", "L. Chen"), ("Zhang Wei", "Chen Li"), True),
    (("Wilson, E. B.",), ("Edwin Wilson",), True),
    (("Brennan T", "Ito KM"), ("Petra Zeller", "Hana Novak"), False),
    (("Brennan TJ", "Ito KM"), ("Thomas Brennan", "Keiko Ito"), True),
    (("M. L. King Jr.",), ("Martin King",), True),
    (("E. Lindqvist",), ("Erik Lindqvist 0002",), True),
    (("K. Ł. Wójcik",), ("Krzysztof Wojcik",), True)])
def test_record_that_names_half_of_the_cited_authors_is_a_record_of_these_authors(names, record, same):
    assert cited(authors=names).same_authors(record) is same


@pytest.mark.parametrize(("name", "record"), [
    ("E. Mueller", "Erna Müller"), ("K. Schroeder", "Kuno Schröder"), ("L. Soerensen", "Liv Sørensen"),
    ("P. Aagaard", "Pia Ågård"), ("B. Haeusler", "Bea Häusler"), ("T. Maekelae", "Tuula Mäkelä"),
    ("E. Müller", "Erna Mueller"), ("E. Muller", "Erna Mueller")])
def test_family_name_with_a_written_out_umlaut_is_the_name_with_the_umlaut(name, record):
    assert cited(authors=(name,)).same_authors([record])
    entry = ENTRY.replace("A. Quill and B. Reed", name)
    assert cited(entry, authors=()).same_authors([record], TITLE)


@pytest.mark.parametrize(("name", "record"), [("B. Reed", "Ben Red"), ("L. Lie", "Lars Li"), ("M. Moor", "Mia Mor")])
def test_second_letter_that_spells_no_umlaut_stays_a_letter_of_a_family_name(name, record):
    assert not cited(authors=(name,)).same_authors([record])


def test_record_with_a_cut_author_list_that_names_only_authors_of_the_entry_is_a_record_of_these_authors():
    names = ("A. Quill", "B. Reed", "C. Marsh", "D. Okafor", "E. Lindqvist")
    assert cited(authors=names).same_authors(["Ada Quill"])
    assert cited(authors=()).same_authors(["Ada Quill", "Ben Reed"], TITLE)


def test_entry_that_names_half_of_the_authors_of_a_record_counts_when_hallucinator_read_no_author():
    assert cited(authors=()).same_authors(["Ada Quill", "Hana Novak"], TITLE)
    assert not cited(authors=()).same_authors(["Ada Quill", "Hana Novak", "Petra Zeller"], TITLE)


def test_et_al_after_the_first_author_of_a_record_stands_for_its_other_authors():
    entry = ENTRY.replace("A. Quill and B. Reed", "A. Quill et al.")
    record = ["Ada Quill", "Hana Novak", "Petra Zeller", "Carla Marsh"]
    assert cited(entry, authors=()).same_authors(record, TITLE)
    assert not cited(entry, authors=()).same_authors(record[1:], TITLE)
    assert not cited(authors=()).same_authors(record, TITLE)


@pytest.mark.parametrize(("authors", "entry"), [
    (("Hoh Peter In", "Petra Zeller"), ENTRY),
    (("Jonathan May", "Petra Zeller"), ENTRY.replace("2021", "May 2021")),
    (("Bo An", "Petra Zeller"), ENTRY.replace(TITLE, "An empirical made-up study of ported patches"))])
def test_family_name_that_is_a_word_of_the_entry_from_its_title_on_names_no_author(authors, entry):
    title = entry.split("“")[1].split(",”")[0]
    assert not cited(entry, title).same_authors(authors, title)


@pytest.mark.parametrize(("name", "family"), [
    ("A. Quill", "quill"), ("Wilson, E. B.", "wilson"), ("Brennan TJ", "brennan"), ("King Jr.", "king"),
    ("Erik Lindqvist 0002", "lindqvist"), ("Jörg Müller", "muller"), ("Søren Ørsted", "orsted"),
    ("Łukasz Wójcik", "wojcik"), ("Claire Le Goues", "goues"), ("J. von Neumann III", "neumann")])
def test_family_name_is_the_last_word_before_a_comma_or_before_the_initials_and_the_generation(name, family):
    assert reference_match.family_names([name]) == {family}


@pytest.mark.parametrize("name", ["", "张伟", "Иван Иванов", "A. B.", "0002"])
def test_name_without_a_word_of_two_latin_letters_or_more_gives_no_family_name(name):
    assert reference_match.family_names([name]) == set()


def test_titles_are_near_when_few_of_their_letters_and_digits_differ():
    assert reference_match.near(TITLE, "A made-up title: on the porting of patchs")
    assert not reference_match.near(TITLE, "Another made-up title on flaky builds")
    assert not reference_match.near("", "")


def test_two_titles_of_one_work_share_half_of_the_longer_words_of_the_title_with_fewer_of_them():
    atlas = ("Observation of a new particle in the search for the Standard Model Higgs boson with the ATLAS detector "
             "at the LHC")
    assert reference_match.share_words(atlas, "Observation of a new boson with the ATLAS detector")
    assert not reference_match.share_words(TITLE, "A real work on something else entirely")
    assert not reference_match.share_words("On it", "On it")


@pytest.mark.parametrize(("text", "latin"), [
    (TITLE, True), ("Über die Portierung", True), ("", True), ("机器学习软件工程的虚构标题", False),
    ("Заголовок статьи о переносе исправлений", False), ("BERT 模型", True), ("BERT 模型的虚构标题", False)])
def test_text_is_in_latin_letters_when_half_of_its_letters_and_digits_are(text, latin):
    assert reference_match.in_latin_letters(text) is latin


def test_folded_text_is_in_lower_case_without_accents_and_with_plain_letters():
    assert reference_match.folded("Łódź, Straße, Ærø, Çelik, İstanbul") == "lodz, strasse, aero, celik, istanbul"
    assert reference_match.letters("A made-up title: 2nd ed. (αβγ)") == "amadeuptitle2ndedαβγ"
