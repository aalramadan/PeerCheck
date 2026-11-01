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
import java.io.StringReader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** The paper ID comes from a pattern with one group, by default the upstream -paper(\d+). */
public class PaperIdPatternTest {

    private static final String CSV = "paper,title,first,last,email\n"
            + "24,A Study of Maintenance Effort,Anna,Lindqvist,anna.lindqvist@kth.se\n";

    @Test
    void defaultPatternReadsHotCrpNames() {
        Pattern pattern = MetaData.compileIdPattern(MetaData.DEFAULT_ID_PATTERN);
        assertThat(MetaData.paperId(pattern, "icse2017-paper13.pdf")).isEqualTo("13");
        assertThat(MetaData.paperId(pattern, "ICSME_2026_paper_24.pdf")).isNull();
    }

    @Test
    void easyChairPatternReadsEasyChairNames() {
        Pattern pattern = MetaData.compileIdPattern("_paper_(\\d+)\\.pdf$");
        assertThat(MetaData.paperId(pattern, "ICSME_2026_paper_24.pdf")).isEqualTo("24");
        assertThat(MetaData.paperId(pattern, "ICSME_2026_paper_0024.PDF")).isEqualTo("0024");
    }

    @Test
    void zeroPaddedIdsMatchTheAuthorCsv() throws IOException {
        MetaData meta = new MetaData();
        meta.setIdPattern(MetaData.compileIdPattern("_paper_(\\d+)\\.pdf$"));
        meta.loadHotCRPauthors(new StringReader(CSV));
        PaperMetaData paper = meta.forFile(new File("ICSME_2026_paper_0024.pdf"));
        assertThat(paper).isNotNull();
        assertThat(paper.getAuthors().get(0).getName()).isEqualTo("Anna Lindqvist");
        assertThat(MetaData.numericId("0024")).isEqualTo(24);
    }

    @Test
    void easyChairNameMatchesNoRowWithTheDefaultPattern() throws IOException {
        MetaData meta = new MetaData();
        meta.loadHotCRPauthors(new StringReader(CSV));
        assertThat(meta.forFile(new File("ICSME_2026_paper_24.pdf"))).isNull();
        assertThat(meta.forFile(new File("ICSME-paper24.pdf"))).isNotNull();
    }

    @Test
    void patternWithoutExactlyOneGroupIsRejected() {
        assertThatThrownBy(() -> MetaData.compileIdPattern("_paper_\\d+")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> MetaData.compileIdPattern("(_paper)_(\\d+)")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> MetaData.compileIdPattern("_paper_(\\d+")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void authorListCheckRunsOnEasyChairNames(@TempDir Path folder) throws IOException {
        File csv = folder.resolve("authors.csv").toFile();
        Files.writeString(csv.toPath(), CSV);
        File pdf = new TestPdf().page("A Study of Maintenance Effort", "Anonymous Author(s)",
                "Contact anna.lindqvist@kth.se for the data.").save(folder, "ICSME_2026_paper_24.pdf");
        BatchRun run = BatchRun.of("--json", "--meta", csv.getPath(), "--id-pattern", "_paper_(\\d+)\\.pdf$",
                pdf.getPath());
        assertThat(run.status).isZero();
        assertThat(run.json().get("paper").getAsInt()).isEqualTo(24);
        assertThat(run.out).contains("possibly-identity-revealing-data").contains("anna.lindqvist@kth.se");
    }
}
