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

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.stream.Collectors;

/** One run of the command line with its exit status and captured output, for the tests. */
final class BatchRun {

    final int status;
    final String out;
    final String err;

    private BatchRun(int status, String out, String err) {
        this.status = status;
        this.out = out;
        this.err = err;
    }

    /**
     * Run the checker with the default page limits and capture its streams.
     * @param args Command line arguments
     * @return The run
     */
    static BatchRun of(String... args) {
        PdfChecker.PAGE_LIMIT = 10;
        PdfChecker.REFERENCE_LIMIT = 2;
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ByteArrayOutputStream err = new ByteArrayOutputStream();
        int status = new BatchChecker(new PrintStream(out, true, StandardCharsets.UTF_8),
                new PrintStream(err, true, StandardCharsets.UTF_8)).run(args);
        return new BatchRun(status, out.toString(StandardCharsets.UTF_8), err.toString(StandardCharsets.UTF_8));
    }

    /**
     * Parse each line of the standard output as one JSON object.
     * @return The objects in output order
     */
    List<JsonObject> jsonLines() {
        return out.lines().map(line -> JsonParser.parseString(line).getAsJsonObject()).collect(Collectors.toList());
    }

    /**
     * Parse the only line of the standard output as a JSON object.
     * @return The object
     */
    JsonObject json() {
        List<JsonObject> lines = jsonLines();
        if (lines.size() != 1) {
            throw new IllegalStateException("expected one JSON line, got " + lines.size() + ": " + out);
        }
        return lines.get(0);
    }
}
