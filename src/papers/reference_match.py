"""Tells whether a database record names the work of a reference, by the title and the authors of its entry."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from rapidfuzz import fuzz

from peercheck import dblp

WORD = re.compile(r"[a-z0-9]+")
NAME_WORD = re.compile(r"[^\W\d_]+")
ET_AL = re.compile(r"\bet\s+al\b")
# A name that ends in one of these words names a group, which stands in an entry or a record for its members.
GROUP_NAME = re.compile(r"\b(?:collaboration|consortium|team|group|project)\W*$", re.IGNORECASE)
# Letters that Unicode does not split into a plain letter and an accent.
PLAIN_LETTERS = str.maketrans({"ł": "l", "ø": "o", "đ": "d", "ð": "d", "ß": "ss", "æ": "ae", "œ": "oe", "ı": "i"})
# German and Nordic names write ä, ö, ü, and å also as ae, oe, ue, and aa.
WRITTEN_UMLAUT = re.compile(r"(?<=[aou])e|(?<=a)a")
# A title stands in an entry as a field between these marks. A colon closes a title before its subtitle, and a
# parenthesis or a bracket closes the year before a title in an author-year style.
FIELD_OPENS, FIELD_CLOSES = "“\"'‘.,:;([`)]", "”\"'’.,:;?!)]"
# A shorter title, in letters and digits, stands in too many entries by chance.
MIN_TITLE_LENGTH = 16
# Two titles are nearly the same from this ratio of their letters and digits, out of 100.
NEAR_TITLE = 95
# A word after a family name is no part of it when it marks a generation or holds up to three capital initials.
GENERATIONS = frozenset({"jr", "sr", "ii", "iii", "iv"})
MOST_INITIALS = 3
# Two titles of one work share this part of the words of four letters or more of the title that has fewer of them.
LONG_WORD, SHARED_WORDS = 4, 0.5


class Citation:
    """A reference as the comparison reads it: the folded text of its entry, and the title and the family names of
    the authors that Hallucinator read from the entry."""

    def __init__(self, text: str, title: str, authors: Iterable[str]):
        self.entry = folded(text)
        self.title = title
        self.cites_group = any(GROUP_NAME.search(name) for name in authors)
        self.families = _name_keys(family_names(name for name in authors if not GROUP_NAME.search(name)))
        self._places = [index for index, letter in enumerate(self.entry) if letter.isalnum()]
        self._letters = "".join(self.entry[index] for index in self._places)

    def bears(self, title: str) -> bool:
        """Tell whether the reference bears the title of a record: nearly the title that Hallucinator read, or a
        whole field of the entry, also when the entry leaves the subtitle of the record out."""
        main = title.split(":")[0]
        return ((len(letters(title)) >= MIN_TITLE_LENGTH and near(self.title, title))
                or self._place(title, field=True) is not None
                or (main != title and self._place(main, field=True) is not None))

    def holds_words(self, title: str) -> bool:
        """Tell whether the entry holds the words of a title in their order, as it holds the name of its venue."""
        words, held = WORD.findall(folded(title)), WORD.findall(self.entry)
        return bool(words) and any(held[start:start + len(words)] == words
                                   for start in range(len(held) - len(words) + 1))

    def after_authors(self) -> str:
        """Return the entry from its title on, or the whole entry when the title has no place in it."""
        return self.entry[self._place(self.title, field=False) or 0:]

    def same_authors(self, authors: Iterable[str], title: str = "") -> bool:
        """Tell whether a record under a title names the authors of the reference.

        The record does when it names at least half of the cited authors, only cited authors, as a record with a
        cut author list does, or the first author of an entry that goes on with et al. A record without an author
        to compare counts as the same, and so does every record for an entry that names a group and no person."""
        names = compared_authors(authors)
        if not names or (self.cites_group and not self.families):
            return True
        named = self._named(names, title)
        words = _name_keys(word for name in names for word in _words(name))
        if 2 * len(self.families & words) >= len(self.families) > 0 or named == len(names):
            return True
        if not self.families and 2 * named >= len(names):
            return True
        return bool(ET_AL.search(self._author_part(title))) and self._named(names[:1], title) == 1

    def _named(self, names: list[str], title: str) -> int:
        """Count the authors of a record that the reference names, among the authors that Hallucinator read or by
        the family name in the entry before the title."""
        part = _name_keys(WORD.findall(ET_AL.sub(" ", self._author_part(title))))
        return sum(1 for name in names
                   if _name_keys([_family_name(name)]) & part or self.families & _name_keys(_words(name)))

    def _author_part(self, title: str) -> str:
        """Return the entry before the title of a record, or before the title that Hallucinator read."""
        place = self._place(title, field=True)
        if place is None:
            place = self._place(self.title, field=False)
        return "" if place is None else self.entry[:place]

    def _place(self, title: str, field: bool) -> int | None:
        """Return where a title of 16 letters or more starts in the entry, as a whole field when asked."""
        wanted = letters(title)
        start = self._letters.find(wanted) if len(wanted) >= MIN_TITLE_LENGTH else -1
        while start >= 0:
            first, last = self._places[start], self._places[start + len(wanted) - 1]
            before, after = self.entry[:first].rstrip(), self.entry[last + 1:].lstrip()
            if not field or ((not before or before[-1] in FIELD_OPENS) and (not after or after[0] in FIELD_CLOSES)):
                return first
            start = self._letters.find(wanted, start + 1)
        return None


def folded(text: str) -> str:
    """Return a text in lower case without accents, also without those that a PDF holds as marks of their own."""
    return _unaccented(text).lower().translate(PLAIN_LETTERS)


def letters(text: str) -> str:
    """Return the letters and digits of a text, folded, also those of another script such as a Greek letter."""
    return "".join(letter for letter in folded(text) if letter.isalnum())


def near(first: str, second: str) -> bool:
    """Tell whether two titles are nearly the same in their letters and digits."""
    first, second = letters(first), letters(second)
    return bool(first and second) and fuzz.ratio(first, second) >= NEAR_TITLE


def share_words(first: str, second: str) -> bool:
    """Tell whether two titles share half of their longer words, as two titles of one work do."""
    longer = [{word for word in WORD.findall(folded(title)) if len(word) >= LONG_WORD} for title in (first, second)]
    fewer = min(longer, key=len)
    return bool(fewer) and len(longer[0] & longer[1]) >= SHARED_WORDS * len(fewer)


def in_latin_letters(text: str) -> bool:
    """Tell whether at least half of the letters and digits of a text are Latin letters or digits."""
    found = letters(text)
    return 2 * sum(letter.isascii() for letter in found) >= len(found)


def family_names(names: Iterable[str]) -> set[str]:
    """Return the family name of each name in Latin letters, folded.

    The family name is the last word before a comma or, without a comma, of the name, once the initials and the
    mark of a generation after it are left out, as in Wilson, E. B., in Brennan TJ, and in King Jr."""
    return {family for name in names if (family := _family_name(name))}


def compared_authors(names: Iterable[str]) -> list[str]:
    """Return the authors of a record that a reference can name: each one with a family name in Latin letters
    that is no group. The only author of a record under one word is an organization, such as a company."""
    people = [name for name in names if _family_name(name) and not GROUP_NAME.search(name)]
    return [] if len(people) == 1 and len(dblp.base_name(people[0]).split()) == 1 else people


def _family_name(name: str) -> str:
    head = dblp.base_name(name).split(",")[0]
    words = NAME_WORD.findall(_unaccented(head))
    while len(words) > 1 and (len(words[-1]) == 1 or words[-1].lower() in GENERATIONS
                              or (words[-1].isupper() and len(words[-1]) <= MOST_INITIALS and not words[0].isupper())):
        words.pop()
    family = words[-1].lower().translate(PLAIN_LETTERS) if words else ""
    return family if len(family) > 1 and WORD.fullmatch(family) else ""


def _words(name: str) -> list[str]:
    return WORD.findall(folded(dblp.base_name(name)))


def _name_keys(words: Iterable[str]) -> set[str]:
    """Return folded words of names with each written-out umlaut as one letter, as muller for mueller."""
    return {WRITTEN_UMLAUT.sub("", word) for word in words}


def _unaccented(text: str) -> str:
    joined = "".join(letter for letter in text if unicodedata.category(letter) not in ("Sk", "Lm"))
    return "".join(letter for letter in unicodedata.normalize("NFKD", joined) if not unicodedata.combining(letter))
