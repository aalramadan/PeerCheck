/*
 * Copyright 2026, the PeerCheck authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 */

package org.sigsoft.sfc;

import org.jetbrains.annotations.NotNull;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Finds the names, emails, and affiliations of the authors of a paper in a text, ignoring case and accents.
 * Names match as whole words in the forms "First Last", "Last, First", "Last, F.", and "F. Last",
 * with an optional middle initial. Emails and affiliations match as whole phrases.
 */
public final class IdentityScanner {

    private static final String WORD_BEFORE = "(?<![\\p{L}\\p{N}])";
    private static final String WORD_AFTER = "(?![\\p{L}\\p{N}])";
    private static final String MIDDLE_INITIAL = "(?:\\s\\p{L}\\.)?";
    private static final String MORE_INITIALS = "(?:\\s?-?\\s?\\p{L}\\.)*";
    private static final String EMAIL_BEFORE = "(?<![\\p{L}\\p{N}._%+-])";
    private static final String EMAIL_AFTER = "(?![\\p{L}\\p{N}_-]|\\.[\\p{L}\\p{N}])";
    // LaTeX accent commands that author lists from HotCRP may hold, such as K{\"a}stner.
    private static final Pattern LATEX_ACCENT = Pattern.compile("\\\\[`'^\"~=.uvHtcdbkr]\\s*\\{?\\s*(\\p{L})\\s*\\}?");
    private static final Set<String> MISSING_VALUES = Set.of("n/a", "na", "none", "unknown", "-");

    private final List<Pattern> patterns = new ArrayList<>();

    /**
     * Prepare the patterns for the authors of one paper.
     * @param authors Authors with their names and, where known, emails and affiliations
     */
    public IdentityScanner(@NotNull List<Author> authors) {
        for (Author author : authors) {
            addPattern(namePattern(author.getFirstName(), author.getLastName()));
            addPattern(emailPattern(author.getEmail()));
            addPattern(affiliationPattern(author.getAffiliation()));
        }
    }

    /**
     * Find every author name, email, and affiliation in a folded text.
     * @param text Folded text to search
     * @return Spans {start, end} in the folded text, in text order, none inside another
     */
    public List<int[]> find(@NotNull FoldedText text) {
        List<int[]> spans = new ArrayList<>();
        for (Pattern pattern : patterns) {
            Matcher matcher = pattern.matcher(text.folded());
            while (matcher.find()) {
                spans.add(new int[]{matcher.start(), matcher.end()});
            }
        }
        spans.sort(Comparator.<int[]>comparingInt(s -> s[0]).thenComparingInt(s -> -s[1]));
        List<int[]> outer = new ArrayList<>();
        for (int[] span : spans) {
            if (outer.isEmpty() || span[0] >= outer.get(outer.size() - 1)[1]) {
                outer.add(span);
            }
        }
        return outer;
    }

    private void addPattern(String regex) {
        if (regex != null) {
            patterns.add(Pattern.compile(regex));
        }
    }

    static String namePattern(String first, String last) {
        String given = foldName(first);
        String family = foldName(last);
        List<String> forms = new ArrayList<>();
        if (!given.isEmpty() && !family.isEmpty()) {
            String familyWords = words(family);
            List<String> givenForms = new ArrayList<>();
            givenForms.add(words(given));
            String firstGiven = given.split(" ")[0];
            if (!firstGiven.equals(given)) {
                givenForms.add(words(firstGiven));
            }
            for (String givenWords : givenForms) {
                forms.add(givenWords + MIDDLE_INITIAL + "\\s" + familyWords);
                forms.add(familyWords + "\\s?,\\s?" + givenWords);
            }
            int initial = given.codePointAt(0);
            if (Character.isLetter(initial)) {
                String letter = Pattern.quote(new String(Character.toChars(initial)));
                forms.add(letter + "\\." + MORE_INITIALS + "\\s?" + familyWords);
                forms.add(familyWords + "\\s?,\\s?" + letter + "\\.");
            }
        } else if (!given.isEmpty() || !family.isEmpty()) {
            forms.add(words(given.isEmpty() ? family : given));
        }
        if (forms.isEmpty()) {
            return null;
        }
        return WORD_BEFORE + "(?:" + String.join("|", forms) + ")" + WORD_AFTER;
    }

    static String emailPattern(String email) {
        String folded = email == null ? "" : FoldedText.fold(email);
        int at = folded.indexOf('@');
        if (at <= 0 || at == folded.length() - 1 || folded.contains(" ")) {
            return null;
        }
        String local = Pattern.quote(folded.substring(0, at));
        String domain = Pattern.quote(folded.substring(at + 1));
        String plain = EMAIL_BEFORE + local + "\\s?@\\s?" + domain;
        // Papers often group the local parts of several authors, as in {anna, bob}@kth.se.
        String grouped = "\\{[^{}]{0,200}?" + EMAIL_BEFORE + local + "(?![\\p{L}\\p{N}._%+-])[^{}]{0,200}\\}\\s?@\\s?"
                + domain;
        return "(?:" + grouped + "|" + plain + ")" + EMAIL_AFTER;
    }

    static String affiliationPattern(String affiliation) {
        String folded = affiliation == null ? "" : FoldedText.fold(affiliation);
        if (folded.isEmpty() || MISSING_VALUES.contains(folded.toLowerCase(Locale.ROOT))
                || folded.codePoints().filter(Character::isLetter).count() < 2) {
            return null;
        }
        return WORD_BEFORE + words(folded) + WORD_AFTER;
    }

    private static String foldName(String name) {
        if (name == null) {
            return "";
        }
        String plain = LATEX_ACCENT.matcher(name).replaceAll("$1").replace("{", "").replace("}", "");
        return FoldedText.fold(plain).replace('\n', ' ');
    }

    private static String words(String folded) {
        return Arrays.stream(folded.split("[ \\n]+")).map(Pattern::quote).collect(Collectors.joining("\\s"));
    }
}
