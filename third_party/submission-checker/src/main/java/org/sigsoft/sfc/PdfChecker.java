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

import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.apache.commons.text.similarity.LevenshteinDistance;
import org.jetbrains.annotations.NotNull;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Conduct series of tests on PDF paper to make sure it meets
 * double blind and formatting standards.
 * Using ICSE 2021 and hence IEEE style as starting point,
 * but extensible for other conferences / styles.
 *
 * Relies on Apache PDFBox, which has excellent facilities to extra text
 * from pdf documents (also used in Apache Tika).
 *
 */

public class PdfChecker {

    static final String META_AUTHOR = "possibly-author-revealing-meta-data";
    static final String PREVIOUS_WORK = "previous-work-mentioned";
    static final String IDENTITY_DATA = "possibly-identity-revealing-data";
    static final String IDENTITY_IN_REFERENCES = "identity-data-in-references";
    static final String IDENTITY_LINK = "identity-link";
    static final String ACKNOWLEDGMENTS = "acknowledgments-present";

    private static final Pattern REFERENCES_HEADING = Pattern.compile(
            "^\\s*((REFERENCES)|(R E F E R E N C E S)|(PUBLICATIONS))\\s*$",
            Pattern.MULTILINE | Pattern.CASE_INSENSITIVE);
    // A placeholder only counts as a whole word, therefore names such as Anna or Kenneth stay checked.
    private static final Pattern PLACEHOLDER = Pattern.compile(
            "anon|anonymous|anonymi[sz]ed|doe|blind|blinded|nn|nobody|none|email|firstname|lastname|xyz|x{3,}"
                    + "|authors?|example|domain|address|review");
    private static final Pattern NON_WORD = Pattern.compile("[^\\p{L}\\p{N}]+");
    private static final Pattern TRAILING_DIGITS = Pattern.compile("\\d+$");
    private static final Pattern ACM_PERMISSIONS =
            Pattern.compile("(?<![\\w.])permissions@acm\\.org(?!\\w)", Pattern.CASE_INSENSITIVE);
    private static final Pattern ACKNOWLEDGMENT_HEADING =
            Pattern.compile("^(?:(?:[ivxlc]+|\\d+)\\.?\\s)?acknowledge?ments?(?:\\s?[.:]|$)", Pattern.MULTILINE);
    private static final Pattern FILE_NAME_SEPARATORS = Pattern.compile("[._/\\\\-]");

    @NotNull PdfDocument document;

    /**
     * The maximum number of pages of the main text
     */
    public static int PAGE_LIMIT = 10;

    /**
     * The maximum number of additional pages for references only.
     */
    public static int REFERENCE_LIMIT = 2;

    private PaperMetaData metaData = null;

    final private Log log = LogFactory.getLog(PdfChecker.class);

    private FoldedText[] foldedPages;

    public int getPageLimit() {
        return PAGE_LIMIT;
    }

    public int getReferenceLimit() {
        return REFERENCE_LIMIT;
    }

    public int getTotalLimit() {
        return getPageLimit() + getReferenceLimit();
    }

    public int pageCount() {
        return document.pageCount();
    }

    public void setDocument(@NotNull PdfDocument document) {
        this.document = document;
        this.foldedPages = null;
    }

    /**
     * Find the page of the references section.
     * @return Page number for references section or 0 if not found.
     */
    public int referencesPage() {
        // Search from back for page containing references section.
        for (int pagenr = document.pageCount(); pagenr > 0; pagenr--) {
            if (isReferencesPage(pagenr) != null) {
                return pagenr;
            }
        }
        // not found.
        return 0;
    }

    /**
     * Verify whether given page contains references.
     * @param pagenr Page that may contain references section.
     * @return Null if page does not contain References. Text on same page before references if it does.
      */
    private String isReferencesPage(int pagenr) {
        int heading = referencesOffset(pagenr);
        if (heading >= 0) {
            // We're on the references page.
            // Return text _preceding_ the References.
            // (should be empty if references start on page 11).
            // We're not interested in line nrs, so strip those first.
            String before = document.textAtPage(pagenr).substring(0, heading);
            return stripHeader(before);
        }
        // Not on the references page.
        return null;
    }

    private int referencesOffset(int pagenr) {
        Matcher findRefs = REFERENCES_HEADING.matcher(document.textAtPage(pagenr));
        return findRefs.find() ? findRefs.start() : -1;
    }

    /**
     * Establish whether paper is created with ACM style.
     * @return True if paper was created with acmart
     */
    boolean isACM() {
        String producer = document.metaDataCreator();
        if (producer != null && match("acmart", producer) != null) {
            return true;
        }
        // no luck with meta data. Check content of first page.
        String permissions = revealingEmail("permissions@acm.org");
        if (permissions != null) {
            return true;
        }
        // no luck with official copyright template. Try format.
        String format = revealingEmail("ACM Reference format:");
        if (format != null) {
            return true;
        }
        // no luck: Are there (many) line numbers?
        String page1 = document.textAtPage(1);
        int lineCount = countLineNumbers(page1.split("\n"));
        return lineCount > 30;
    }

    String stripHeader(@NotNull String acmPage) {
        String[] lines = acmPage.split("\\n");
        int leftColumn = countLineNumbers(lines);
        final int minimumPageLength = 30;
        if (leftColumn > minimumPageLength && leftColumn < lines.length) {
            // if you'd like to know the header, it is in lines[leftColumn];
            // in rare cases the header can take three (!) lines. Let's check.
            if (leftColumn + 1 < lines.length && !Pattern.matches("\\d+", lines[leftColumn + 1])) {
                leftColumn++;
                if (leftColumn + 1 < lines.length && !Pattern.matches("\\d+", lines[leftColumn + 1])) {
                    leftColumn++;
                }
            }
            String[] remainingLines = Arrays.copyOfRange(lines, leftColumn + 1, lines.length);
            int rightColumn = countLineNumbers(remainingLines);
            if (rightColumn > minimumPageLength) {
                return String.join("\n", Arrays.copyOfRange(remainingLines, rightColumn, remainingLines.length));
            } else {
                // left column numbered, but right one not ...
                return String.join("\n", remainingLines);
            }
        } else {
            //return acmPage;
            return stripNonNumberedHeader(acmPage);
        }
    }

    String stripNonNumberedHeader(@NotNull String acmPage) {
        if (pageCount() < 3) {
            // cannot determine whether headers are used.
            return acmPage;
        }
        String title = getTitle();
        // in ACM format odd pages can contain title header.
        String page3 = document.textAtPage(3);
        String line1 = page3.contains("\n") ? page3.substring(0, page3.indexOf("\n")) : page3;
        if (title != null && line1.startsWith(title)) {
            // assume header is one line, and drop it from the page.
            return acmPage.substring(acmPage.indexOf("\n") + 1);
        } else {
            // nothing to strip
            return acmPage;
        }
    }

    /**
     * Strip initial line numbers from text, if present (as is the case for ACM formating).
     * @param acmText Text potentially containing line numbers.
     * @return Text with starting line numbers removed.
     */
    String stripLineNumbers(@NotNull String acmText) {
        String[] lines = acmText.split("\\n");
        int count = countLineNumbers(lines);
        assert count >= 0;
        assert count <= lines.length;
        return String.join("\n", Arrays.copyOfRange(lines, count, lines.length)) + "\n";
    }

    /**
     * Count how many of the starting lines of this string are pure line numbers,
     * i.e., a consecutive series of numbers on new lines.
     * @param lines Text potentially starting with line numbers
     * @return Count of the number of starting lines that are just numbers.
     */
    int countLineNumbers(String ...lines) {
        int i = 0;
        int counter = -1;
        while (i < lines.length) {
            try {
                int nr = Integer.parseInt(lines[i]);
                if (counter != -1) {
                    if (counter + 1 != nr ) {
                         // Numbers not consecutive -- done.
                        break;
                    }
                }
                counter = nr;
                i++;
            } catch(NumberFormatException nfe) {
                // first line of real text. Done.
                break;
            }
        }
        return i;
    }

    /**
     * Establish whether paper is created with IEEE style.
     * Unfortunately no positive test exists, so we use heuristics.
     * @return True if paper likely IEEE
     */
    boolean isIEEE() {
        if (isACM()) {
            return false;
        }
        if (copyrightIEEE(getFirstLine(document.textAtPage(1)))) {
            // an old MS Word Template, but ok for now.
            return true;
        }
        // we're not sure, but let's assume it's IEEE style.
        // can we think of more checks to do here?
        return true;
    }

    /**
     * Find a figure, a table, an appendix, acknowledgments, or other text on the pages after the page limit.
     * @return The issue with the text found and its page, or null if the pages after the limit hold references only.
     */
    public Issue figuresAfterLimit() {
        if (document.pageCount() <= getPageLimit()) {
            return null;
        }
        String code = String.format("non-references-after-p%d", PdfChecker.PAGE_LIMIT);
        for (int pagenr = document.pageCount(); pagenr > getPageLimit(); pagenr--) {
            String figText = pageContainsFigure(pagenr);
            if (figText != null) {
                return Issue.text(code, figText, pagenr);
            }
        }
        String beforeReferences = isReferencesPage(getPageLimit() + 1);
        final int leewayForPageNr = 8;
        if (beforeReferences == null || beforeReferences.length() <= leewayForPageNr) {
            return null;
        } else {
            int abusiveCharCount = beforeReferences.length();
            String content = beforeReferences.substring(0, leewayForPageNr).replaceAll("\\n", "\\\\n");
            return Issue.text(code, String.format("%d-chars-before-REFERENCES: %s", abusiveCharCount, content),
                    getPageLimit() + 1);
        }
    }

    public String pageContainsFigure(int pagenr) {
        String figRegEx = "^\\s*((((Fig\\.)|(Figure))\\s*\\d+)|(TABLE\\s*[IVX]+)|(APPENDIX)|ACKNOWLEDGE?MENTS)";
        return findOnPage(pagenr, figRegEx);
    }

    /**
     * Find author names in the metadata of the document and of its figures that are no placeholder.
     * @return One issue per revealing name, with the page of the figure where one applies
     */
    public List<Issue> findAuthorIdentity() {
        List<Issue> issues = new ArrayList<>();
        for (TextSource author : document.metaDataAuthors()) {
            if (!blindedIdentity(author.getText())) {
                String detail = author.getKind() == TextSource.Kind.INFO
                        ? author.getText() : String.format("%s (%s)", author.getText(), author.getLabel());
                issues.add(Issue.text(META_AUTHOR, detail, author.getPage()));
            }
        }
        return issues;
    }

    public String revealingEmail(String email) {
        String emailPattern = email.replaceAll("\\.", "\\\\.");
        return findOnPage(1, emailPattern);
    }

    /**
     * Find an email address on the first page that is no placeholder.
     * @return The first such address, or null if there is none.
     */
    public String findEmails() {
        // The email pattern is not exact, as authors can be sloppy in
        // writing their email in the paper.
        String name = "\\w+[\\w\\.\\-]*";
        String curlyNames = String.format("(\\{)?%s(,\\s*%s)*(\\})?", name, name);
        String domain = "\\w+(\\.[a-zA-Z]\\w*)+";
        String pat = curlyNames + "\\s*@\\s*" + domain;
        Matcher emails = Pattern.compile(pat, Pattern.MULTILINE | Pattern.CASE_INSENSITIVE)
                .matcher(document.textAtPage(1));
        while (emails.find()) {
            String found = emails.group(0).strip();
            if (!blindedIdentity(found)) {
                return found;
            }
        }
        return null;
    }

    /**
     * Decide whether a name or an email is a placeholder, such as "Anonymous Author(s)" or
     * john.doe@example.org. Only whole words count, therefore Anna or Kenneth is no placeholder.
     * @param id Name or email
     * @return True if a word of the text is a placeholder word
     */
    static boolean blindedIdentity(@NotNull String id) {
        if (ACM_PERMISSIONS.matcher(id).find()) {
            return true;
        }
        for (String token : NON_WORD.split(id.toLowerCase(Locale.ROOT))) {
            String word = TRAILING_DIGITS.matcher(token).replaceFirst("");
            if (!word.isEmpty() && PLACEHOLDER.matcher(word).matches()) {
                return true;
            }
        }
        return false;
    }

    /**
     * Check if the given page matches a given pattern
     * @param pagenr Page containing the relevant pattern
     * @param regexp Regular expression to search for
     * @return Matching text, if found, null otherwise.
     */
    private String findOnPage(int pagenr, @NotNull String regexp) {
        assert pagenr > 0;
        assert pagenr <= document.pageCount();
        return match(regexp, document.textAtPage(pagenr));
    }

    private String match(@NotNull String regexp, @NotNull String text) {
        Pattern pat = Pattern.compile(regexp, Pattern.MULTILINE | Pattern.CASE_INSENSITIVE);
        return match(pat, text);
    }

    private String match(@NotNull Pattern pattern, @NotNull String text) {
        Matcher match = pattern.matcher(text);
        if (match.find()) {
            return match.group(0).strip();
        } else {
            return null;
        }
    }

    /**
     * Identify identity-revealing references to previous work, such as "our previous work [3]",
     * "we previously proposed", "in our [12]", or "In [12], we showed".
     * This test seems moderately useful at best, so use with caution.
     * @return One issue per phrase found, with the phrase on one line and its page.
     */
    public List<Issue> previousWork() {
        StringBuilder full = new StringBuilder();
        int[] pageStarts = new int[document.pageCount()];
        for (int pagenr = 1; pagenr <= document.pageCount(); pagenr++) {
            pageStarts[pagenr - 1] = full.length();
            full.append(document.textAtPage(pagenr)).append('\n');
        }
        FoldedText text = FoldedText.of(full.toString());
        List<Issue> issues = new ArrayList<>();
        Matcher matcher = previousWorkPattern().matcher(text.folded());
        while (matcher.find()) {
            int start = text.originalStart(matcher.start());
            int pagenr = Arrays.binarySearch(pageStarts, start);
            pagenr = pagenr >= 0 ? pagenr + 1 : -pagenr - 1;
            issues.add(Issue.text(PREVIOUS_WORK, text.evidence(matcher.start(), matcher.end()), pagenr));
        }
        return issues;
    }

    private static Pattern _previousWorkPattern = null;
    private static Pattern previousWorkPattern() {
        if (_previousWorkPattern == null) {
            // The pattern runs on folded text: lower case, one white space character between words.
            String our = "(?:our|my)";
            String previous = "(?:previous|earlier|prior|recent|past)";
            String work = "(?:works?|papers?|stud(?:y|ies)|tools?|approach(?:es)?|publications?)";
            String result = "(?:results?|findings?)";
            String citation = "(?:\\[\\s?\\d+(?:\\s?[,-]\\s?\\d+)*\\s?\\]|\\([^()]{0,80}?(?:19|20)\\d{2}[a-z]?\\))";
            String[] forms = {
                    // our previous work [3], our prior empirical study, my earlier tool
                    "\\b" + our + "\\s" + previous + "(?:\\s[\\p{L}-]+)?\\s" + work + "\\b(?:\\s?" + citation + ")?",
                    // the upstream wording with results or findings, which needs a citation
                    "\\b" + our + "\\s" + previous + "\\s" + result + "\\s?" + citation,
                    // we previously proposed ... [3]
                    "\\bwe\\s(?:have\\s|had\\s)?previously\\s\\p{L}+(?:[^.;\\[\\]()]{0,60}?\\s?" + citation + ")?",
                    // in our [12]
                    "\\b(?:in\\s)?" + our + "\\s?" + citation,
                    // In [12], we showed
                    "\\bin\\s" + citation + ",?\\swe\\s\\p{L}+",
                    // In previous work [5], we showed
                    "\\b" + previous + "\\s" + work + "\\s?" + citation + ",?\\swe\\s\\p{L}+",
            };
            _previousWorkPattern = Pattern.compile("(?:" + String.join("|", forms) + ")");
        }
        return _previousWorkPattern;
    }

    /**
     * Find a heading Acknowledgment(s) or Acknowledgement(s), numbered or not, alone on its line
     * or opening a paragraph.
     * @return One issue per heading, with the heading and its page.
     */
    public List<Issue> acknowledgments() {
        List<Issue> issues = new ArrayList<>();
        for (int pagenr = 1; pagenr <= document.pageCount(); pagenr++) {
            FoldedText text = foldedPage(pagenr);
            Matcher heading = ACKNOWLEDGMENT_HEADING.matcher(text.folded());
            while (heading.find()) {
                issues.add(Issue.text(ACKNOWLEDGMENTS, text.evidence(heading.start(), heading.end()), pagenr));
            }
        }
        return issues;
    }

    /**
     * Find links on the pages and in their annotations that can reveal an author, such as an account
     * on a code host, a personal page, or a cloud drive share.
     * @param links Classifier that knows the allowed hosts
     * @return One issue per distinct link, with its kind and the first page it appears on.
     */
    public List<Issue> identityLinks(@NotNull LinkClassifier links) {
        List<Issue> issues = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (int pagenr = 1; pagenr <= document.pageCount(); pagenr++) {
            List<String> targets = document.linkTargets(pagenr);
            List<String> candidates = new ArrayList<>(targets);
            for (String inText : LinkClassifier.linksInText(document.textAtPage(pagenr))) {
                String key = linkKey(inText);
                // The text of a link may break across lines, while its annotation holds the whole target.
                if (targets.stream().noneMatch(target -> linkKey(target).startsWith(key))) {
                    candidates.add(inText);
                }
            }
            for (String link : candidates) {
                LinkClassifier.Kind kind = links.classify(link);
                if (kind != null && seen.add(linkKey(link))) {
                    issues.add(Issue.text(IDENTITY_LINK, String.format("%s (%s)", link, kind.getDescription()), pagenr));
                }
            }
        }
        return issues;
    }

    private static String linkKey(String link) {
        String key = link.strip().toLowerCase(Locale.ROOT).replaceFirst("^[a-z][a-z0-9+.-]*://", "")
                .replaceFirst("^www\\.", "");
        return key.endsWith("/") ? key.substring(0, key.length() - 1) : key;
    }

    public String getFileName() {
        return document.getFileName();
    }

    /**
     * Obtain the title of the document, which we assume to be the first line on page 1.
     * (Note: Meta data rarely set, so discarded).
     * @return Title of the document.
     */
    public String getTitle() {
        // in likelihood of being correct:
        String paperTitle = titleFromText();
        if (paperTitle != null) {
            return paperTitle;
        }
        String metaTitle = titleFromSubmissionForm();
        if (metaTitle != null) {
            return metaTitle;
        }
        return document.metaDataTitle();
    }

    public String titleFromText() {
        String page1 = stripLineNumbers(document.textAtPage(1));
        String line1 = getFirstLine(page1).strip();
        if (copyrightIEEE(line1)) {
            line1 = getFirstLine(page1.substring(line1.length() + 2));
        }
        if (line1 == "") {
            line1 = null;
        }
        return line1;
    }

    @NotNull private String getFirstLine(@NotNull String text) {
        int newLine = text.indexOf("\n");
        if (newLine == -1) {
            return "";
        } else {
            return text.substring(0, newLine);
        }
    }

    private boolean copyrightIEEE(@NotNull String line) {
        return line.matches(".*20XX IEEE.*");
    }

    public void setMetaData(PaperMetaData metaData) {
        this.metaData = metaData;
    }

    /**
     * Find the names, emails, and affiliations of the authors of the paper anywhere in the PDF:
     * on every page, in the document information, the XMP metadata, the metadata and file names
     * of embedded figures, and the annotations with their link targets.
     * @return One issue per distinct match and place; matches in the reference list get their own code.
     */
    public List<Issue> revealingMetaData() {
        if (metaData == null) {
            return List.of();
        }
        IdentityScanner scanner = new IdentityScanner(metaData.getAuthors());
        int referencesPage = referencesPage();
        int referencesOffset = referencesPage > 0 ? referencesOffset(referencesPage) : -1;
        Set<Issue> issues = new LinkedHashSet<>();
        for (int pagenr = 1; pagenr <= document.pageCount(); pagenr++) {
            FoldedText text = foldedPage(pagenr);
            for (int[] span : scanner.find(text)) {
                int start = text.originalStart(span[0]);
                boolean inReferences = referencesPage > 0
                        && (pagenr > referencesPage || pagenr == referencesPage && start >= referencesOffset);
                issues.add(Issue.text(inReferences ? IDENTITY_IN_REFERENCES : IDENTITY_DATA,
                        text.evidence(span[0], span[1]), pagenr));
            }
        }
        for (TextSource source : document.embeddedSources()) {
            String raw = source.getText();
            List<FoldedText> readings = new ArrayList<>();
            readings.add(FoldedText.of(raw));
            if (source.getKind() == TextSource.Kind.FIGURE_FILE) {
                // A path such as /home/anna_lindqvist/plot.pdf separates the names by other characters.
                readings.add(FoldedText.of(FILE_NAME_SEPARATORS.matcher(raw).replaceAll(" ")));
            }
            for (FoldedText reading : readings) {
                for (int[] span : scanner.find(reading)) {
                    String excerpt = raw.substring(reading.originalStart(span[0]), reading.originalEnd(span[1]));
                    issues.add(Issue.text(IDENTITY_DATA,
                            String.format("%s (%s)", FoldedText.clean(excerpt), source.getLabel()), source.getPage()));
                }
            }
        }
        return new ArrayList<>(issues);
    }

    private FoldedText foldedPage(int pagenr) {
        if (foldedPages == null) {
            foldedPages = new FoldedText[document.pageCount()];
        }
        if (foldedPages[pagenr - 1] == null) {
            foldedPages[pagenr - 1] = FoldedText.of(document.textAtPage(pagenr));
        }
        return foldedPages[pagenr - 1];
    }

    public String titleFromSubmissionForm() {
        return metaData == null? null : metaData.getTitle();
    }

    private boolean similarStart(@NotNull String t1, @NotNull String t2) {
        var len = Math.min(t1.length(), t2.length());
        var t11 = t1.substring(0, len).toLowerCase();
        var t22 = t2.substring(0, len).toLowerCase();
        int distance = (new LevenshteinDistance().apply(t11, t22));
        return distance < 5;
    }

    public String titlesConsistent() {
        String textTitle = titleFromText();
        String metaTitle = titleFromSubmissionForm();
        String pdfTitle = document.metaDataTitle();

        if (metaTitle != null) {
            // the most solid ground truth.
            if (textTitle != null) {
                // testTitle can be shorter, but start must be same.
                if (!similarStart(metaTitle, textTitle)) {
                    return String.format("``%s''-vs-txt-``%s''", metaTitle, textTitle);
                }
                if (pdfTitle != null) {
                    if (!similarStart(metaTitle, pdfTitle)) {
                        return String.format("``%s''-vs-pdf-``%s''", metaTitle, pdfTitle);
                    }
                }
            }
            // ok
            return null;
        }
        // no submission info.
        if (textTitle != null) {
            if (pdfTitle != null) {
                if (!similarStart(pdfTitle, textTitle)) {
                    return String.format("``%s''-vs-``%s''", pdfTitle, textTitle);
                }
            }
        }
        // all suspicious cases checked. Should be OK.
        return null;
    }
}
