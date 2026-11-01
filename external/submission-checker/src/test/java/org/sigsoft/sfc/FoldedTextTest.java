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

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/** Folding removes case and accents, joins hyphenated line breaks, and maps matches back to the original. */
public class FoldedTextTest {

    @Test
    void caseAndAccentsAreRemoved() {
        assertThat(FoldedText.fold("Jörg MÜLLER Søren Łukasz Strauß")).isEqualTo("jorg muller soren lukasz strauss");
    }

    @Test
    void spacingAccentsOfOldTexFontsAreRemoved() {
        // Text extraction of K\"astner in the OT1 encoding often yields a spacing diaeresis.
        assertThat(FoldedText.fold("K¨astner")).isEqualTo("kastner");
    }

    @Test
    void whiteSpaceRunsBecomeOneSpaceOrOneLineBreak() {
        assertThat(FoldedText.fold("Anna \t Lindqvist\n \n KTH")).isEqualTo("anna lindqvist\nkth");
    }

    @Test
    void hyphenatedLineBreakJoinsTheWord() {
        assertThat(FoldedText.fold("Lind-\nqvist and Jean-\nPaul")).isEqualTo("lindqvist and jean-paul");
    }

    @Test
    void evidenceComposesAccentsThatTextExtractionSplit() {
        // Text extraction of J\"org in the OT1 encoding may yield o followed by a combining diaeresis.
        FoldedText text = FoldedText.of("J" + "o\u0308" + "rg");
        assertThat(text.folded()).isEqualTo("jorg");
        assertThat(text.evidence(0, 4)).isEqualTo("J\u00f6rg");
        FoldedText jose = FoldedText.of("Jose" + "\u0301" + " Garc" + "i\u0301" + "a");
        assertThat(jose.evidence(0, 4)).isEqualTo("Jos\u00e9");
    }

    @Test
    void ligaturesAreSplit() {
        assertThat(FoldedText.fold("Griﬃn")).isEqualTo("griffin");
    }

    @Test
    void matchOnFoldedTextMapsBackToTheOriginalWords() {
        FoldedText text = FoldedText.of("Thanks to Ms. Jörg  Mül-\nler today");
        int start = text.folded().indexOf("jorg muller");
        int end = start + "jorg muller".length();
        assertThat(text.evidence(start, end)).isEqualTo("Jörg Müller");
        assertThat(text.originalStart(start)).isEqualTo(14);
    }
}
