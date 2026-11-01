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

import org.apache.commons.text.similarity.LevenshteinDistance;
import org.apache.pdfbox.util.Version;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

/** PDFBox is the newest 2.0 release, commons-text is 1.10 or later, and the bytecode stays at Java 11. */
public class DependencyVersionsTest {

    private static int[] parts(String version) {
        return Arrays.stream(version.split("\\.")).mapToInt(Integer::parseInt).toArray();
    }

    @Test
    void pdfboxIsRelease2037OrLaterOf20() {
        int[] version = parts(Version.getVersion());
        assertThat(version[0]).isEqualTo(2);
        assertThat(version[1]).isEqualTo(0);
        assertThat(version[2]).isGreaterThanOrEqualTo(37);
    }

    @Test
    void commonsTextIs110OrLater() {
        int[] version = parts(LevenshteinDistance.class.getPackage().getImplementationVersion());
        assertThat(version[0] * 1000 + version[1]).isGreaterThanOrEqualTo(1010);
        assertThat(new LevenshteinDistance().apply("Lindqvist", "Lindquist")).isEqualTo(1);
    }

    @Test
    void classFilesTargetJava11() throws IOException {
        try (InputStream in = BatchChecker.class.getResourceAsStream("BatchChecker.class")) {
            byte[] header = in.readNBytes(8);
            int major = (header[6] & 0xff) << 8 | header[7] & 0xff;
            assertThat(major).isEqualTo(55);
        }
    }
}
