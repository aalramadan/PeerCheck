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
import org.junit.jupiter.params.provider.ValueSource;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** The placeholder test of a metadata author or an email matches whole words only. */
public class PlaceholderIdentityTest {

    private PdfChecker pc;
    private PdfDocument doc;

    @BeforeEach
    void setUp() {
        pc = new PdfChecker();
        doc = mock(PdfDocument.class);
        when(doc.pageCount()).thenReturn(1);
        pc.setDocument(doc);
    }

    @ParameterizedTest
    @ValueSource(strings = {"Anna Lindqvist", "Jennifer Doerr", "Kenneth Anonsen", "Lindqvist", "Hannah Exampleton",
            "anna.lindqvist@kth.se", "kenneth@reviewboard.org", "jennifer@domainx.com"})
    void namesThatContainAPlaceholderStringAreNoPlaceholder(String id) {
        assertThat(PdfChecker.blindedIdentity(id)).isFalse();
    }

    @ParameterizedTest
    @ValueSource(strings = {"Anonymous Author(s)", "Jane Doe", "anonymous@fnerk.com", "blinded@for.review",
            "john.doe@example.org", "author1@example.com", "XXXX", "Anonymized for review", "permissions@acm.org"})
    void wholePlaceholderWordsMarkAnAnonymousIdentity(String id) {
        assertThat(PdfChecker.blindedIdentity(id)).isTrue();
    }

    @Test
    void metadataAuthorAnnaIsReported() {
        when(doc.metaDataAuthors()).thenReturn(List.of(
                new TextSource(TextSource.Kind.INFO, "document information Author", null, "Anna Lindqvist")));
        assertThat(pc.findAuthorIdentity()).extracting(Issue::getDetail).containsExactly("Anna Lindqvist");
    }

    @Test
    void emailOfAnnaOnPageOneIsReported() {
        when(doc.textAtPage(eq(1))).thenReturn("Title\nContact anna.lindqvist@kth.se for the data.\n");
        assertThat(pc.findEmails()).isEqualTo("anna.lindqvist@kth.se");
    }

    @Test
    void realEmailAfterAPlaceholderEmailIsReported() {
        when(doc.textAtPage(eq(1))).thenReturn("Title\npermissions@acm.org\nkenneth.berg@kth.se\n");
        assertThat(pc.findEmails()).isEqualTo("kenneth.berg@kth.se");
    }

    @Test
    void figureAndXmpAuthorsAreReportedWithTheirPlace() {
        when(doc.metaDataAuthors()).thenReturn(List.of(
                new TextSource(TextSource.Kind.XMP, "XMP dc:creator", null, "Karl Svensson"),
                new TextSource(TextSource.Kind.FIGURE_INFO, "figure metadata (PTEX.InfoDict Author)", 4, "Jennifer Berg"),
                new TextSource(TextSource.Kind.FIGURE_INFO, "figure metadata (PTEX.InfoDict Author)", 5, "Anonymous")));
        assertThat(pc.findAuthorIdentity()).containsExactly(
                Issue.text(PdfChecker.META_AUTHOR, "Karl Svensson (XMP dc:creator)", null),
                Issue.text(PdfChecker.META_AUTHOR, "Jennifer Berg (figure metadata (PTEX.InfoDict Author))", 4));
    }
}
