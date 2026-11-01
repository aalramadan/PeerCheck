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

import java.text.Normalizer;
import java.util.Arrays;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Text folded for matching: lower case, without accents, with each run of white space reduced to one
 * space or one line break, and with a word joined again where a line break hyphenated it.
 * Each folded character keeps the span of the original text it comes from, therefore a match on the
 * folded text maps back to the words of the original.
 */
public final class FoldedText {

    // Letters whose mark is part of the letter, which Unicode decomposition therefore keeps whole.
    private static final Map<Integer, String> PLAIN_LETTERS = Map.ofEntries(
            Map.entry(0x00F8, "o"), Map.entry(0x00D8, "o"),
            Map.entry(0x0111, "d"), Map.entry(0x0110, "d"),
            Map.entry(0x00F0, "d"), Map.entry(0x00D0, "d"),
            Map.entry(0x0142, "l"), Map.entry(0x0141, "l"),
            Map.entry(0x00E6, "ae"), Map.entry(0x00C6, "ae"),
            Map.entry(0x0153, "oe"), Map.entry(0x0152, "oe"),
            Map.entry(0x00DF, "ss"), Map.entry(0x00FE, "th"), Map.entry(0x00DE, "th"),
            Map.entry(0x0131, "i"));

    private static final int SOFT_HYPHEN = 0x00AD;
    private static final int MINUS_SIGN = 0x2212;

    private static final Pattern SOFT_BREAK =
            Pattern.compile("(?<=\\p{L})[-\\u00AD\\u2010\\u2011]\\s*[\\r\\n]\\s*(?=\\p{Ll})");
    private static final Pattern SPACES = Pattern.compile("\\s+");

    @NotNull
    private final String original;

    @NotNull
    private final String folded;

    // starts[i] and ends[i] delimit the original text that folded character i comes from.
    private final int[] starts;
    private final int[] ends;

    private FoldedText(@NotNull String original, @NotNull String folded, int[] starts, int[] ends) {
        this.original = original;
        this.folded = folded;
        this.starts = starts;
        this.ends = ends;
    }

    /**
     * Fold a text.
     * @param original Text as extracted from the PDF
     * @return The folded text with its map back to the original
     */
    public static FoldedText of(@NotNull String original) {
        Builder out = new Builder(original.length());
        int length = original.length();
        int i = 0;
        while (i < length) {
            int cp = original.codePointAt(i);
            int next = i + Character.charCount(cp);
            if (isSpace(cp)) {
                int end = skipSpaces(original, i);
                out.space(hasLineBreak(original, i, end) ? '\n' : ' ', i, end);
                i = end;
            } else if (isDash(cp)) {
                i = foldDash(original, i, cp, out);
            } else if (isIgnorable(cp)) {
                i = next;
            } else {
                String plain = PLAIN_LETTERS.get(cp);
                String decomposed = plain != null ? plain
                        : Normalizer.normalize(original.substring(i, next), Normalizer.Form.NFKD);
                for (int k = 0; k < decomposed.length(); k++) {
                    char c = decomposed.charAt(k);
                    if (isMark(c)) {
                        continue;
                    }
                    if (Character.isWhitespace(c)) {
                        out.space(' ', i, next);
                    } else {
                        out.add(Character.toLowerCase(c), i, next);
                    }
                }
                i = next;
            }
        }
        return out.build(original);
    }

    /**
     * Fold a short text, such as a name, without keeping the map back to the original.
     * @param text Text to fold
     * @return Folded text without surrounding white space
     */
    public static String fold(@NotNull String text) {
        return of(text).folded().strip();
    }

    /**
     * Turn an excerpt of extracted text into evidence for a report: hyphenated line breaks joined,
     * every run of white space reduced to one space, and accents composed with their letters.
     * @param excerpt Text as extracted from the PDF
     * @return The excerpt on one line
     */
    public static String clean(@NotNull String excerpt) {
        String joined = SOFT_BREAK.matcher(excerpt).replaceAll("");
        String composed = Normalizer.normalize(joined, Normalizer.Form.NFC);
        return SPACES.matcher(composed).replaceAll(" ").strip();
    }

    @NotNull
    public String folded() {
        return folded;
    }

    @NotNull
    public String original() {
        return original;
    }

    /**
     * Map the start of a match on the folded text to the original text.
     * @param foldedStart Start index in the folded text
     * @return Start index in the original text
     */
    public int originalStart(int foldedStart) {
        return foldedStart < starts.length ? starts[foldedStart] : original.length();
    }

    /**
     * Map the exclusive end of a match on the folded text to the original text.
     * @param foldedEnd Exclusive end index in the folded text
     * @return Exclusive end index in the original text
     */
    public int originalEnd(int foldedEnd) {
        if (foldedEnd <= 0) {
            return 0;
        }
        int end = ends[foldedEnd - 1];
        // A combining accent after the last letter belongs to that letter, as in a decomposed José.
        while (end < original.length() && isMark(original.charAt(end))) {
            end++;
        }
        return end;
    }

    /**
     * Return the original words behind a span of the folded text, cleaned for a report.
     * @param foldedStart Start index in the folded text
     * @param foldedEnd Exclusive end index in the folded text
     * @return The original excerpt on one line
     */
    public String evidence(int foldedStart, int foldedEnd) {
        return clean(original.substring(originalStart(foldedStart), originalEnd(foldedEnd)));
    }

    private static int foldDash(String text, int i, int dash, Builder out) {
        int next = i + Character.charCount(dash);
        int end = skipSpaces(text, next);
        if (end > next && end < text.length() && hasLineBreak(text, next, end)
                && i > 0 && Character.isLetter(text.codePointBefore(i))) {
            int after = text.codePointAt(end);
            if (Character.isLowerCase(after)) {
                // A word that the line break hyphenated, such as Lind-/qvist.
                return end;
            }
            if (Character.isLetter(after)) {
                // A compound that the line break split after its hyphen, such as Jean-/Paul.
                if (dash != SOFT_HYPHEN) {
                    out.add('-', i, next);
                }
                return end;
            }
        }
        if (dash != SOFT_HYPHEN) {
            out.add('-', i, next);
        }
        return next;
    }

    private static int skipSpaces(String text, int from) {
        int j = from;
        while (j < text.length() && isSpace(text.codePointAt(j))) {
            j += Character.charCount(text.codePointAt(j));
        }
        return j;
    }

    private static boolean hasLineBreak(String text, int from, int to) {
        for (int j = from; j < to; j++) {
            char c = text.charAt(j);
            if (c == '\n' || c == '\r' || c == ' ' || c == ' ') {
                return true;
            }
        }
        return false;
    }

    private static boolean isSpace(int cp) {
        return Character.isWhitespace(cp) || Character.isSpaceChar(cp);
    }

    private static boolean isDash(int cp) {
        return Character.getType(cp) == Character.DASH_PUNCTUATION || cp == SOFT_HYPHEN || cp == MINUS_SIGN;
    }

    private static boolean isIgnorable(int cp) {
        int type = Character.getType(cp);
        return type == Character.FORMAT || type == Character.MODIFIER_SYMBOL || type == Character.CONTROL
                || isMarkType(type);
    }

    private static boolean isMark(char c) {
        return isMarkType(Character.getType(c));
    }

    private static boolean isMarkType(int type) {
        return type == Character.NON_SPACING_MARK || type == Character.ENCLOSING_MARK
                || type == Character.COMBINING_SPACING_MARK;
    }

    /** Collects folded characters with their original spans. */
    private static final class Builder {
        private final StringBuilder text;
        private int[] starts;
        private int[] ends;

        Builder(int capacity) {
            text = new StringBuilder(capacity);
            starts = new int[Math.max(capacity, 16)];
            ends = new int[Math.max(capacity, 16)];
        }

        void add(char c, int start, int end) {
            if (text.length() == starts.length) {
                starts = Arrays.copyOf(starts, starts.length * 2);
                ends = Arrays.copyOf(ends, ends.length * 2);
            }
            starts[text.length()] = start;
            ends[text.length()] = end;
            text.append(c);
        }

        void space(char c, int start, int end) {
            int last = text.length() - 1;
            if (last < 0) {
                return;
            }
            char previous = text.charAt(last);
            if (previous == ' ' || previous == '\n') {
                if (c == '\n') {
                    text.setCharAt(last, '\n');
                }
                ends[last] = end;
            } else {
                add(c, start, end);
            }
        }

        FoldedText build(String original) {
            int length = text.length();
            return new FoldedText(original, text.toString(), Arrays.copyOf(starts, length), Arrays.copyOf(ends, length));
        }
    }
}
