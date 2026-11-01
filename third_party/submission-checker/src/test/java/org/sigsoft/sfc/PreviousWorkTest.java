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

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** Self-citations beyond the upstream wording are found, with the quoted text and its page as evidence. */
public class PreviousWorkTest {

    private PdfChecker pc;
    private PdfDocument doc;

    @BeforeEach
    void setUp() {
        pc = new PdfChecker();
        doc = mock(PdfDocument.class);
    }

    private void pages(String... texts) {
        when(doc.pageCount()).thenReturn(texts.length);
        for (int i = 0; i < texts.length; i++) {
            when(doc.textAtPage(eq(i + 1))).thenReturn(texts[i] + "\n");
        }
        pc.setDocument(doc);
    }

    @ParameterizedTest
    @CsvSource(delimiter = '|', value = {
            "In our previous work [2], we built a tool.|our previous work [2]",
            "As we previously proposed in [12], the tool works.|we previously proposed in [12]",
            "We have previously shown this.|We have previously shown",
            "Our prior tool supports Java.|Our prior tool",
            "This extends our earlier paper [3, 4].|our earlier paper [3, 4]",
            "We build on our recent study (Lindqvist et al., 2021).|our recent study (Lindqvist et al., 2021)",
            "Unlike our previous approach [5\u20137], it scales.|our previous approach [5\u20137]",
            "As described in our [12], it scales.|in our [12]",
            "In [12], we proposed a model.|In [12], we proposed",
            "In previous work [5], we showed the bound.|previous work [5], we showed",
            "Our earlier empirical study [9] found more.|Our earlier empirical study [9]",
            "My prior publications [1] differ.|My prior publications [1]",
            "our previous results [4] hold.|our previous results [4]",
    })
    void selfCitationFormsAreFound(String text, String evidence) {
        pages("Title", text);
        assertThat(pc.previousWork()).containsExactly(Issue.text(PdfChecker.PREVIOUS_WORK, evidence, 2));
    }

    @ParameterizedTest
    @ValueSource(strings = {"Previous work [5] shows the bound.", "Our tool supports Java.",
            "In previous work, Lindqvist et al. [5] showed the bound.", "Our results show the bound.",
            "our previous results hold.", "The workflow of our approach."})
    void thirdPersonCitationsAndCurrentWorkAreNotFound(String text) {
        pages("Title", text);
        assertThat(pc.previousWork()).isEmpty();
    }

    @Test
    void phraseBrokenAcrossLinesIsReportedOnOneLine() {
        pages("Title", "As shown in our\nprevious work [3], the tool helps.");
        assertThat(pc.previousWork()).extracting(Issue::getDetail).containsExactly("our previous work [3]");
    }

    @Test
    void everyPhraseIsReportedWithItsPage() {
        pages("In our previous work [1] we did A.", "Body", "We previously proposed B [2].");
        assertThat(pc.previousWork()).containsExactly(
                Issue.text(PdfChecker.PREVIOUS_WORK, "our previous work [1]", 1),
                Issue.text(PdfChecker.PREVIOUS_WORK, "We previously proposed B [2]", 3));
    }
}
