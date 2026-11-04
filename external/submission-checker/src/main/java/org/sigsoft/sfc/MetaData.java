/*
 * Copyright 2020, Arie van Deursen, TU Delft
 * Modified for PeerCheck in 2026; PORT.md lists the changes.
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

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.Reader;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MetaData {

    /** The pattern of HotCRP file names such as icse2017-paper13.pdf, as upstream reads them. */
    public static final String DEFAULT_ID_PATTERN = "-paper(\\d+)";

    private static final List<String> REQUIRED_COLUMNS = List.of("paper", "title", "first", "last", "email");
    private static final String AFFILIATION = "affiliation";
    private static final Pattern DIGITS = Pattern.compile("\\d{1,9}");

    private final HashMap<String, PaperMetaData> papers = new HashMap<>();

    private Pattern idPattern = Pattern.compile(DEFAULT_ID_PATTERN, Pattern.CASE_INSENSITIVE);

    public PaperMetaData getPaper(String id) {
        return papers.get(normalizeId(id));
    }

    /**
     * Set the pattern that finds the paper ID in a file name.
     * @param idPattern Pattern with exactly one group, which holds the ID
     */
    public void setIdPattern(Pattern idPattern) {
        this.idPattern = idPattern;
    }

    /**
     * Compile a paper ID pattern as given on the command line, ignoring case like PeerCheck does.
     * @param regex Regular expression with exactly one group
     * @return The compiled pattern
     * @throws IllegalArgumentException if the expression does not compile or has another number of groups
     */
    public static Pattern compileIdPattern(String regex) {
        Pattern pattern = Pattern.compile(regex, Pattern.CASE_INSENSITIVE);
        int groups = pattern.matcher("").groupCount();
        if (groups != 1) {
            throw new IllegalArgumentException(String.format(
                    "the ID pattern ``%s'' has %d groups; it needs exactly one, which holds the paper ID", regex, groups));
        }
        return pattern;
    }

    /**
     * Find the paper ID in a file name.
     * @param idPattern Pattern with one group
     * @param fileName File name such as CONF_2026_paper_24.pdf
     * @return The ID as written in the name, or null if the pattern does not match
     */
    public static String paperId(Pattern idPattern, String fileName) {
        Matcher matcher = idPattern.matcher(fileName);
        return matcher.find() ? matcher.group(1) : null;
    }

    /**
     * Return a paper ID as a number, such as 24 for the ID 0024.
     * @param id ID as written in a file name, or null
     * @return The number, or null if the ID is missing or not a number
     */
    public static Integer numericId(String id) {
        return id != null && DIGITS.matcher(id.strip()).matches() ? Integer.valueOf(id.strip()) : null;
    }

    public void loadHotCRPauthors(String fileName) throws IOException {
        try (var stream = getClass().getClassLoader().getResourceAsStream(fileName)) {
            if (stream == null) {
                throw new IOException(String.format("Cannot find csv file %s on class path", fileName));
            }
            loadHotCRPauthors(readUtf8(stream));
        }
    }

    /**
     * Load an author CSV file in UTF-8, with or without a byte order mark.
     * @param file CSV file with the columns paper, title, first, last, email, and optionally affiliation
     * @throws IOException if the file cannot be read
     * @throws IllegalArgumentException if a required column is missing
     */
    public void loadHotCRPauthors(File file) throws IOException {
        try (InputStream stream = Files.newInputStream(file.toPath())) {
            loadHotCRPauthors(readUtf8(stream));
        }
    }

    private CSVFormat hotCrpCSVFormat() {
        return CSVFormat.DEFAULT
                .builder()
                .setHeader()
                .setSkipHeaderRecord(true)
                .setIgnoreHeaderCase(true)
                .setTrim(true)
                .build();
    }

    public void loadHotCRPauthors(Reader reader) throws IOException {
        try (CSVParser records = hotCrpCSVFormat().parse(reader)) {
            for (String column : REQUIRED_COLUMNS) {
                if (!records.getHeaderMap().containsKey(column)) {
                    throw new IllegalArgumentException(String.format(
                            "the author CSV lacks the column ``%s''; it needs %s", column,
                            String.join(",", REQUIRED_COLUMNS)));
                }
            }
            boolean hasAffiliation = records.getHeaderMap().containsKey(AFFILIATION);
            for (CSVRecord record : records) {
                processHotCRPRecord(record, hasAffiliation);
            }
        }
    }

    private PaperMetaData processHotCRPRecord(CSVRecord record, boolean hasAffiliation) {
        var author = hotCrpAuthor(record, hasAffiliation);
        var paper = hotCrpPaper(record);
        paper.addAuthor(author);
        return paper;
    }

    private Author hotCrpAuthor(CSVRecord record, boolean hasAffiliation) {
        var author = new Author();
        author.setEmail(record.get("email"));
        author.setFirstName(record.get("first"));
        author.setLastName(record.get("last"));
        if (hasAffiliation && record.isSet(AFFILIATION)) {
            author.setAffiliation(record.get(AFFILIATION));
        }
        return author;
    }

    private PaperMetaData hotCrpPaper(CSVRecord record) {
        String id = normalizeId(record.get("paper"));
        PaperMetaData paper = papers.get(id);
        if (paper == null) {
            paper = new PaperMetaData(id, record.get("title"));
            papers.put(id, paper);
        }
        return paper;
    }

    public PaperMetaData forFile(File paper) {
        String id = paperId(idPattern, paper.getName());
        return id == null ? null : getPaper(id);
    }

    private static String normalizeId(String id) {
        if (id == null) {
            return null;
        }
        Integer number = numericId(id);
        return number != null ? number.toString() : id.strip();
    }

    private static Reader readUtf8(InputStream stream) throws IOException {
        String text = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        return new StringReader(text.startsWith("﻿") ? text.substring(1) : text);
    }
}
