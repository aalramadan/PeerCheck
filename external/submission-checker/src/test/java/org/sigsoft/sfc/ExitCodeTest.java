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

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/** The exit status is 0 unless the arguments are wrong, whatever the papers hold. */
public class ExitCodeTest {

    @TempDir
    Path folder;

    private String pdf;
    private String damaged;

    @BeforeEach
    void writePapers() throws IOException {
        pdf = new TestPdf().page("Title", "Anna Lindqvist, anna.lindqvist@kth.se").save(folder, "paper.pdf").getPath();
        damaged = folder.resolve("damaged.pdf").toString();
        Files.writeString(Path.of(damaged), "broken");
    }

    @Test
    void papersWithIssuesOrErrorsExitWithZero() {
        assertThat(BatchRun.of("--json", pdf, damaged).status).isEqualTo(BatchChecker.EXIT_OK);
        assertThat(BatchRun.of(pdf, damaged).status).isEqualTo(BatchChecker.EXIT_OK);
    }

    @Test
    void helpExitsWithZero() {
        BatchRun run = BatchRun.of("--help");
        assertThat(run.status).isEqualTo(BatchChecker.EXIT_OK);
        assertThat(run.err).contains("--id-pattern", "--allowed-hosts", "--flag-acknowledgments", "--json");
    }

    @Test
    void wrongOptionsExitWithTwo() {
        assertThat(BatchRun.of("--no-such-option", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--mainpages", "ten", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--mainpages", "0", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--style", "Springer", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--id-pattern", "(a)(b)", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--id-pattern", "paper_(\\d+", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--showtext", "first", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--showtext", "99999999999", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--json", "--showtext", "1", pdf).status).isEqualTo(BatchChecker.EXIT_USAGE);
    }

    @Test
    void wrongFilesExitWithTwoBeforeAnyPaperIsChecked() throws IOException {
        File notes = folder.resolve("notes.txt").toFile();
        Files.writeString(notes.toPath(), "text");
        BatchRun run = BatchRun.of("--json", pdf, notes.getPath());
        assertThat(run.status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(run.out).isEmpty();
        assertThat(BatchRun.of("--json").status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(BatchRun.of("--json", folder.resolve("missing.pdf").toString()).status)
                .isEqualTo(BatchChecker.EXIT_USAGE);
    }

    @Test
    void wrongAuthorCsvExitsWithTwo() throws IOException {
        assertThat(BatchRun.of("--meta", folder.resolve("missing.csv").toString(), pdf).status)
                .isEqualTo(BatchChecker.EXIT_USAGE);
        Path noEmail = folder.resolve("authors.csv");
        Files.writeString(noEmail, "paper,title,first,last\n1,T,Anna,Lindqvist\n");
        BatchRun run = BatchRun.of("--meta", noEmail.toString(), pdf);
        assertThat(run.status).isEqualTo(BatchChecker.EXIT_USAGE);
        assertThat(run.err).contains("email");
    }
}
