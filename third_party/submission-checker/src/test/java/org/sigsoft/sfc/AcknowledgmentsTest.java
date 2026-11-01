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
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.File;
import java.io.IOException;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** A heading Acknowledgment(s) or Acknowledgement(s) becomes acknowledgments-present when the option asks. */
public class AcknowledgmentsTest {

    private PdfChecker pc;
    private PdfDocument doc;

    @BeforeEach
    void setUp() {
        pc = new PdfChecker();
        doc = mock(PdfDocument.class);
        when(doc.pageCount()).thenReturn(2);
        when(doc.textAtPage(eq(1))).thenReturn("Title\nIntroduction\n");
        pc.setDocument(doc);
    }

    @ParameterizedTest
    @CsvSource(delimiter = '|', value = {
            "ACKNOWLEDGMENT|ACKNOWLEDGMENT",
            "Acknowledgments|Acknowledgments",
            "ACKNOWLEDGEMENTS|ACKNOWLEDGEMENTS",
            "Acknowledgement|Acknowledgement",
            "VIII. ACKNOWLEDGMENTS|VIII. ACKNOWLEDGMENTS",
            "7 Acknowledgments|7 Acknowledgments",
            "Acknowledgments. We thank the reviewers.|Acknowledgments.",
            "'  Acknowledgements:'|Acknowledgements:",
    })
    void headingFormsAreFound(String heading, String evidence) {
        when(doc.textAtPage(eq(2))).thenReturn("Conclusion text.\n" + heading + "\nThis work was funded.\n");
        assertThat(pc.acknowledgments()).containsExactly(Issue.text(PdfChecker.ACKNOWLEDGMENTS, evidence, 2));
    }

    @ParameterizedTest
    @ValueSource(strings = {"Acknowledgments are due to the reviewers.", "We acknowledge the funding.",
            "The acknowledgments section is missing."})
    void runningTextIsNoHeading(String text) {
        when(doc.textAtPage(eq(2))).thenReturn(text + "\n");
        assertThat(pc.acknowledgments()).isEmpty();
    }

    @Test
    void optionTurnsTheCheckOn(@TempDir Path folder) throws IOException {
        File pdf = new TestPdf().page("A Study", "Conclusion").page("ACKNOWLEDGMENT", "We thank the funder.")
                .save(folder, "paper.pdf");
        assertThat(BatchRun.of("--json", pdf.getPath()).out).doesNotContain("acknowledgments-present");
        assertThat(BatchRun.of("--json", "--flag-acknowledgments", pdf.getPath()).out).contains(
                "{\"code\": \"acknowledgments-present\", \"detail\": \"ACKNOWLEDGMENT\", \"page\": 2}");
    }
}
