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
import org.junit.jupiter.api.io.TempDir;

import java.io.File;
import java.io.IOException;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/** The link check reads link annotations and the page text, and reports each revealing link once. */
public class IdentityLinkTest {

    @TempDir
    Path folder;

    @Test
    void annotationAndTextLinksBecomeIdentityLinks() throws IOException {
        File pdf = new TestPdf()
                .page("A Study", "Anonymous Author(s)", "Our package is at anonymous.4open.science/r/study-1.")
                .page("Data at https://drive.google.com/file/d/1AbC/view and www.cs.kth.se/~alind.")
                .link(1, "https://github.com/annalindqvist/effort-study")
                .save(folder, "paper.pdf");
        BatchRun run = BatchRun.of("--json", "--allowed-hosts", "anonymous.4open.science,zenodo.org", pdf.getPath());
        assertThat(run.out).contains(
                "{\"code\": \"identity-link\", \"detail\": \"https://github.com/annalindqvist/effort-study "
                        + "(code host account)\", \"page\": 1}",
                "{\"code\": \"identity-link\", \"detail\": \"https://drive.google.com/file/d/1AbC/view "
                        + "(cloud drive share)\", \"page\": 2}",
                "{\"code\": \"identity-link\", \"detail\": \"www.cs.kth.se/~alind (personal page)\", \"page\": 2}");
        assertThat(run.out).doesNotContain("4open");
    }

    @Test
    void linkTextThatBreaksAcrossLinesIsCoveredByItsAnnotation() throws IOException {
        File pdf = new TestPdf()
                .page("A Study", "Code: https://github.com/annalind", "qvist/effort-study")
                .link(1, "https://github.com/annalindqvist/effort-study")
                .save(folder, "paper.pdf");
        BatchRun run = BatchRun.of("--json", pdf.getPath());
        assertThat(run.json().getAsJsonArray("issues").toString())
                .contains("annalindqvist/effort-study")
                .doesNotContain("annalind (code host account)");
    }

    @Test
    void sameLinkOnTwoPagesIsReportedOnce() throws IOException {
        File pdf = new TestPdf()
                .page("A Study", "See github.com/annalindqvist/tool.")
                .page("Again github.com/annalindqvist/tool")
                .save(folder, "paper.pdf");
        String issues = BatchRun.of("--json", pdf.getPath()).json().getAsJsonArray("issues").toString();
        assertThat(issues.split("identity-link", -1)).hasSize(2);
        assertThat(issues).contains("github.com/annalindqvist/tool (code host account)\",\"page\":1");
    }

    @Test
    void allowedHostIsNeverReported() throws IOException {
        File pdf = new TestPdf().page("A Study", "See https://github.com/annalindqvist/tool")
                .save(folder, "paper.pdf");
        assertThat(BatchRun.of("--json", "--allowed-hosts", "github.com", pdf.getPath()).out)
                .doesNotContain("identity-link");
    }
}
