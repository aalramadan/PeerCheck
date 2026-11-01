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

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.encryption.AccessPermission;
import org.apache.pdfbox.pdmodel.encryption.StandardProtectionPolicy;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** With --json, each PDF gives one JSON object on one line; a PDF that fails to open gives its error. */
public class JsonOutputTest {

    @TempDir
    Path folder;

    @Test
    void resultHoldsEveryKeyWithItsType() throws IOException {
        File pdf = new TestPdf().page("A Study of Maintenance Effort", "Anonymous Author(s)",
                "In our previous work [1], we built it.").save(folder, "ICSME_2026_paper_0031.pdf");
        JsonObject result = BatchRun.of("--json", "--id-pattern", "_paper_(\\d+)\\.pdf$", pdf.getPath()).json();
        assertThat(result.keySet()).containsExactly("file", "paper", "title", "pages", "issues", "error");
        assertThat(result.get("file").getAsString()).isEqualTo(pdf.getPath());
        assertThat(result.get("paper").getAsInt()).isEqualTo(31);
        assertThat(result.get("title").getAsString()).isEqualTo("A Study of Maintenance Effort");
        assertThat(result.get("pages").getAsInt()).isEqualTo(1);
        assertThat(result.get("error").isJsonNull()).isTrue();
        JsonObject issue = result.getAsJsonArray("issues").get(1).getAsJsonObject();
        assertThat(issue.keySet()).containsExactly("code", "detail", "page");
        assertThat(issue.get("code").getAsString()).isEqualTo("previous-work-mentioned");
        assertThat(issue.get("detail").getAsString()).isEqualTo("our previous work [1]");
        assertThat(issue.get("page").getAsInt()).isEqualTo(1);
        assertThat(result.getAsJsonArray("issues").get(0).getAsJsonObject().get("page").isJsonNull()).isTrue();
    }

    @Test
    void paperIsNullWhenTheNameDoesNotMatch() throws IOException {
        File pdf = new TestPdf().page("Title").save(folder, "draft.pdf");
        assertThat(BatchRun.of("--json", pdf.getPath()).json().get("paper").isJsonNull()).isTrue();
    }

    @Test
    void damagedPdfGivesItsErrorAndNoIssues() throws IOException {
        Path damaged = folder.resolve("ICSME_2026_paper_0003.pdf");
        Files.writeString(damaged, "%PDF-1.4\nnot really a pdf\n");
        BatchRun run = BatchRun.of("--json", "--id-pattern", "_paper_(\\d+)\\.pdf$", damaged.toString());
        assertThat(run.status).isZero();
        JsonObject result = run.json();
        assertThat(result.get("error").getAsString()).isNotBlank();
        assertThat(result.getAsJsonArray("issues")).isEmpty();
        assertThat(result.get("pages").getAsInt()).isZero();
        assertThat(result.get("title").isJsonNull()).isTrue();
        assertThat(result.get("paper").getAsInt()).isEqualTo(3);
    }

    @Test
    void passwordProtectedPdfGivesItsError() throws IOException {
        File plain = new TestPdf().page("Title", "Anna Lindqvist").save(folder, "plain.pdf");
        File locked = folder.resolve("locked.pdf").toFile();
        try (PDDocument pdf = PDDocument.load(plain)) {
            StandardProtectionPolicy policy = new StandardProtectionPolicy("owner", "user", new AccessPermission());
            policy.setEncryptionKeyLength(128);
            pdf.protect(policy);
            pdf.save(locked);
        }
        JsonObject result = BatchRun.of("--json", locked.getPath()).json();
        assertThat(result.get("error").getAsString()).contains("password");
        assertThat(result.getAsJsonArray("issues")).isEmpty();
    }

    @Test
    void folderGivesOneLinePerPdfInNameOrderIncludingUpperCaseExtensions() throws IOException {
        new TestPdf().page("Second").save(folder, "b.PDF");
        new TestPdf().page("First").save(folder, "a.pdf");
        Files.writeString(folder.resolve("c.pdf"), "broken");
        Files.writeString(folder.resolve("notes.txt"), "not a pdf");
        List<JsonObject> lines = BatchRun.of("--json", folder.toString()).jsonLines();
        assertThat(lines).extracting(line -> new File(line.get("file").getAsString()).getName())
                .containsExactly("a.pdf", "b.PDF", "c.pdf");
    }

    @Test
    void textIsEscapedToPrintableAscii() {
        String quoted = PaperResult.quote("Jörg \"Q\" \\ a\nb\tc ");
        assertThat(quoted).isEqualTo("\"J\\u00f6rg \\\"Q\\\" \\\\ a\\nb\\tc\\u2028\"");
        assertThat(JsonParser.parseString(quoted).getAsString()).isEqualTo("Jörg \"Q\" \\ a\nb\tc ");
        assertThat(quoted.chars().allMatch(c -> c >= 0x20 && c < 0x7f)).isTrue();
    }

    @Test
    void withoutJsonTheUpstreamTextFormatStays() throws IOException {
        File pdf = new TestPdf().page("A Study of Maintenance Effort", "In our previous work [1], we built it.")
                .save(folder, "paper.pdf");
        BatchRun run = BatchRun.of(pdf.getPath());
        assertThat(run.out).isEqualTo("paper.pdf                issues-found {paper-very-short:1, "
                + "previous-work-mentioned:``our previous work [1]''} ``A Study of Maintenance Effort''"
                + System.lineSeparator());
    }

    @Test
    void withoutJsonADamagedPdfIsReportedOnStandardError() throws IOException {
        Path damaged = folder.resolve("damaged.pdf");
        Files.write(damaged, "broken".getBytes(StandardCharsets.UTF_8));
        BatchRun run = BatchRun.of(damaged.toString());
        assertThat(run.out).isEmpty();
        assertThat(run.err).startsWith("Error processing damaged.pdf.");
    }
}
