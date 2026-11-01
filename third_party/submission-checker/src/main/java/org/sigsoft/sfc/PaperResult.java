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

import org.jetbrains.annotations.NotNull;

import java.util.List;
import java.util.stream.Collectors;

/**
 * The result of checking one PDF, printed as one JSON object or as one line in the upstream text format.
 */
public final class PaperResult {

    @NotNull
    private final String file;

    @NotNull
    private final String fileName;

    private final Integer paper;

    private final String title;

    private final int pages;

    @NotNull
    private final List<Issue> issues;

    private final String error;

    /**
     * Create a result.
     * @param file Path of the PDF as given on the command line
     * @param fileName Name of the PDF without its folder
     * @param paper Paper ID from the file name, or null
     * @param title Title found in the paper, or null
     * @param pages Number of pages, 0 if the PDF did not open
     * @param issues Issues found
     * @param error What went wrong, or null
     */
    public PaperResult(@NotNull String file, @NotNull String fileName, Integer paper, String title, int pages,
                       @NotNull List<Issue> issues, String error) {
        this.file = file;
        this.fileName = fileName;
        this.paper = paper;
        this.title = title;
        this.pages = pages;
        this.issues = List.copyOf(issues);
        this.error = error;
    }

    @NotNull
    public List<Issue> getIssues() {
        return issues;
    }

    public String getError() {
        return error;
    }

    public int getPages() {
        return pages;
    }

    @NotNull
    public String getFileName() {
        return fileName;
    }

    /**
     * Render the result as one line of JSON with the keys file, paper, title, pages, issues, and error.
     * Every character outside printable ASCII is escaped, therefore the line survives any console encoding.
     * @return The JSON object on one line
     */
    public String toJson() {
        String issueList = issues.stream()
                .map(issue -> String.format("{\"code\": %s, \"detail\": %s, \"page\": %s}",
                        quote(issue.getCode()), quote(issue.getDetail()), number(issue.getPage())))
                .collect(Collectors.joining(", "));
        return String.format("{\"file\": %s, \"paper\": %s, \"title\": %s, \"pages\": %d, \"issues\": [%s], \"error\": %s}",
                quote(file), number(paper), quote(title), pages, issueList, quote(error));
    }

    /**
     * Render the result in the upstream text format, such as
     * {@code paper13.pdf issues-found {oversize:13} ``Title''}.
     * @return The line
     */
    public String toText() {
        String result;
        if (issues.isEmpty()) {
            result = "no-issues   ";
        } else {
            result = String.format("issues-found {%s}",
                    issues.stream().map(Issue::toText).collect(Collectors.joining(", ")));
        }
        result = result + String.format(" ``%s''", title);
        return String.format("%-24s %s", fileName, result);
    }

    private static String number(Integer value) {
        return value == null ? "null" : value.toString();
    }

    static String quote(String text) {
        if (text == null) {
            return "null";
        }
        StringBuilder quoted = new StringBuilder(text.length() + 2).append('"');
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            switch (c) {
                case '"':
                    quoted.append("\\\"");
                    break;
                case '\\':
                    quoted.append("\\\\");
                    break;
                case '\n':
                    quoted.append("\\n");
                    break;
                case '\r':
                    quoted.append("\\r");
                    break;
                case '\t':
                    quoted.append("\\t");
                    break;
                default:
                    if (c < 0x20 || c > 0x7e) {
                        quoted.append(String.format("\\u%04x", (int) c));
                    } else {
                        quoted.append(c);
                    }
            }
        }
        return quoted.append('"').toString();
    }
}
