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

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * With an author list, the scan covers every page, the document information, XMP metadata, the PTEX entries
 * of embedded figures, and annotations with their link targets, and each issue carries its page.
 */
public class WholePaperScanTest {

    @TempDir
    Path folder;

    private File csv;

    @BeforeEach
    void writeAuthorList() throws IOException {
        csv = folder.resolve("authors.csv").toFile();
        Files.writeString(csv.toPath(), "﻿paper,title,first,last,email,affiliation\n"
                + "7,A Study,Anna,Lindqvist,anna.lindqvist@kth.se,KTH Royal Institute of Technology\n"
                + "7,A Study,Jörg,Müller,joerg.mueller@tum.de,Technical University of Munich\n",
                StandardCharsets.UTF_8);
    }

    private List<String> issues(File pdf) {
        BatchRun run = BatchRun.of("--json", "--meta", csv.getPath(), "--id-pattern", "_paper_(\\d+)\\.pdf$",
                pdf.getPath());
        assertThat(run.status).isZero();
        JsonObject result = run.json();
        assertThat(result.get("error").isJsonNull()).as(run.out).isTrue();
        List<String> issues = new ArrayList<>();
        for (JsonElement element : result.getAsJsonArray("issues")) {
            JsonObject issue = element.getAsJsonObject();
            String page = issue.get("page").isJsonNull() ? "-" : issue.get("page").getAsString();
            issues.add(issue.get("code").getAsString() + "|" + issue.get("detail").getAsString() + "|" + page);
        }
        return issues;
    }

    @Test
    void namesOnLaterPagesAreFoundWithTheirPage() throws IOException {
        File pdf = new TestPdf()
                .page("A Study of Maintenance Effort", "Anonymous Author(s)")
                .page("Background")
                .page("We thank Jörg Müller and the Technical University of Munich.")
                .save(folder, "ICSME_2026_paper_7.pdf");
        assertThat(issues(pdf)).contains(
                "possibly-identity-revealing-data|Jörg Müller|3",
                "possibly-identity-revealing-data|Technical University of Munich|3");
    }

    @Test
    void namesInTheReferenceListGetTheirOwnCode() throws IOException {
        File pdf = new TestPdf()
                .page("A Study of Maintenance Effort", "Anonymous Author(s)", "Anna Lindqvist wrote this.")
                .page("REFERENCES", "[1] A. Lindqvist, Mining effort data, 2020.")
                .save(folder, "ICSME_2026_paper_7.pdf");
        assertThat(issues(pdf)).contains(
                "possibly-identity-revealing-data|Anna Lindqvist|1",
                "identity-data-in-references|A. Lindqvist|2");
    }

    @Test
    void documentInformationAndXmpAreScanned() throws IOException {
        File pdf = new TestPdf()
                .page("A Study of Maintenance Effort", "Anonymous Author(s)")
                .info("Subject", "Draft by Lindqvist, Anna")
                .xmp(TestPdf.xmpPacket("Anonymous", "joerg.mueller@tum.de"))
                .save(folder, "ICSME_2026_paper_7.pdf");
        assertThat(issues(pdf)).contains(
                "possibly-identity-revealing-data|Lindqvist, Anna (document information Subject)|-",
                "possibly-identity-revealing-data|joerg.mueller@tum.de (XMP metadata)|-");
    }

    @Test
    void figureMetadataAndFileNamesAreScanned() throws IOException {
        File pdf = new TestPdf()
                .page("A Study of Maintenance Effort", "Anonymous Author(s)")
                .page("Results", "Fig. 1 shows the effort.")
                .figure(2, Map.of("Author", "Jörg Müller", "Title", "plot"),
                        "/home/anna_lindqvist/figs/effort.pdf")
                .save(folder, "ICSME_2026_paper_7.pdf");
        assertThat(issues(pdf)).contains(
                "possibly-author-revealing-meta-data|Jörg Müller (figure metadata (PTEX.InfoDict Author))|2",
                "possibly-identity-revealing-data|Jörg Müller (figure metadata (PTEX.InfoDict Author))|2",
                "possibly-identity-revealing-data|anna_lindqvist (figure file name (PTEX.FileName))|2");
    }

    @Test
    void annotationsAndLinkTargetsAreScanned() throws IOException {
        File pdf = new TestPdf()
                .page("A Study of Maintenance Effort", "Anonymous Author(s)")
                .page("Data")
                .link(2, "mailto:anna.lindqvist@kth.se")
                .note(2, "Ask Anna Lindqvist about the data", "J. Müller")
                .save(folder, "ICSME_2026_paper_7.pdf");
        assertThat(issues(pdf)).contains(
                "possibly-identity-revealing-data|anna.lindqvist@kth.se (link target)|2",
                "possibly-identity-revealing-data|Anna Lindqvist (annotation text)|2",
                "possibly-identity-revealing-data|J. Müller (annotation author)|2");
    }

    @Test
    void paperWithoutAuthorDataIsNotScannedAndSaysSo() throws IOException {
        File pdf = new TestPdf().page("A Study", "Anna Lindqvist").save(folder, "ICSME_2026_paper_8.pdf");
        BatchRun run = BatchRun.of("--json", "--meta", csv.getPath(), "--id-pattern", "_paper_(\\d+)\\.pdf$",
                pdf.getPath());
        assertThat(run.out).doesNotContain("identity");
        assertThat(run.err).contains("No author data for ICSME_2026_paper_8.pdf");
    }
}
