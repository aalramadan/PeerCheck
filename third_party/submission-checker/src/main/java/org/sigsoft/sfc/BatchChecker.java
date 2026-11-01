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

import org.apache.commons.cli.CommandLine;
import org.apache.commons.cli.DefaultParser;
import org.apache.commons.cli.Option;
import org.apache.commons.cli.Options;
import org.apache.commons.cli.ParseException;
import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.jetbrains.annotations.NotNull;

import java.io.File;
import java.io.IOException;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

public class BatchChecker {

    /** Exit status of a run whose arguments were right, whatever the papers hold. */
    public static final int EXIT_OK = 0;

    /** Exit status of a run with wrong arguments, such as an unknown option or a missing file. */
    public static final int EXIT_USAGE = 2;

    private final Log log = LogFactory.getLog(BatchChecker.class);

    private final PrintStream out;

    private final PrintStream err;

    // Style can be "ACM" or "IEEE";
    public String style = "IEEE";

    // Which pages, if any, to display on stdout
    public String showText = null;

    // Separate meta-data for all files processed, if available.
    public MetaData meta = null;

    // Finds the paper ID in a file name.
    public Pattern idPattern = MetaData.compileIdPattern(MetaData.DEFAULT_ID_PATTERN);

    // Sorts out the links that can reveal an author.
    public LinkClassifier links = new LinkClassifier(List.of());

    public boolean flagAcknowledgments = false;

    // Print one JSON object per paper in place of the upstream text line.
    public boolean json = false;

    /** Create a checker that prints to the standard output and error streams. */
    public BatchChecker() {
        this(System.out, System.err);
    }

    /**
     * Create a checker that prints to the given streams.
     * @param out Stream for the results
     * @param err Stream for errors and the usage text
     */
    public BatchChecker(PrintStream out, PrintStream err) {
        this.out = out;
        this.err = err;
    }

    /**
     * Run every check on a paper. A check that fails is listed in failures while the other checks still run.
     * @param pc Checker that holds the paper
     * @param failures Receives one line per failed check
     * @return The issues found, in the upstream order followed by the PeerCheck checks
     */
    public List<Issue> paperIssues(PdfChecker pc, List<String> failures) {
        List<Issue> issues = new ArrayList<>();
        runCheck("template", failures, () -> {
            if (style.equals("ACM") && !pc.isACM() || style.equals("IEEE") && !pc.isIEEE()) {
                issues.add(Issue.value("wrong-template", String.format("must-be-%s", style), null));
            }
        });
        runCheck("page count", failures, () -> {
            if (pc.pageCount() > pc.getTotalLimit()) {
                issues.add(Issue.value("oversize", Integer.toString(pc.pageCount()), null));
            } else {
                final int minimum = Math.max(2, pc.getPageLimit() / 2);
                if (pc.pageCount() <= minimum) {
                    issues.add(Issue.value("paper-very-short", Integer.toString(pc.pageCount()), null));
                }
            }
        });
        runCheck("references", failures, () -> {
            int referencesPage = pc.referencesPage();
            if (referencesPage > pc.getPageLimit() + 1) {
                issues.add(Issue.value("reference-page-after-limit", Integer.toString(referencesPage), referencesPage));
            }
        });
        runCheck("pages after limit", failures, () -> {
            Issue textAfterLimit = pc.figuresAfterLimit();
            if (textAfterLimit != null) {
                issues.add(textAfterLimit);
            }
        });
        runCheck("emails", failures, () -> {
            String emails = pc.findEmails();
            if (emails != null) {
                issues.add(Issue.text("author-revealing-email", emails, 1));
            }
        });
        runCheck("metadata authors", failures, () -> issues.addAll(pc.findAuthorIdentity()));
        runCheck("previous work", failures, () -> issues.addAll(pc.previousWork()));
        // pc.titlesConsistent gives too many false alarms. Omitted for now.
        runCheck("author list", failures, () -> issues.addAll(pc.revealingMetaData()));
        runCheck("links", failures, () -> issues.addAll(pc.identityLinks(links)));
        if (flagAcknowledgments) {
            runCheck("acknowledgments", failures, () -> issues.addAll(pc.acknowledgments()));
        }
        return issues;
    }

    /**
     * Check one PDF. A PDF that does not open gives a result with the error and no issues.
     * @param paper The PDF
     * @return The result
     */
    public PaperResult checkPaper(File paper) {
        log.trace("Processing " + paper.getName());
        Integer paperId = MetaData.numericId(MetaData.paperId(idPattern, paper.getName()));
        PdfDocument doc = new PdfDocument();
        try {
            doc.loadFile(paper);
            PdfChecker pc = new PdfChecker();
            pc.setDocument(doc);
            pc.setMetaData(getPaperMetaData(paper));

            displayPages(doc, this.showText);

            List<String> failures = new ArrayList<>();
            String[] title = new String[1];
            runCheck("title", failures, () -> title[0] = pc.getTitle());
            List<Issue> issues = paperIssues(pc, failures);
            List<String> problems = new ArrayList<>(doc.problems());
            problems.addAll(failures);
            String error = problems.isEmpty() ? null : String.join("; ", problems);
            return new PaperResult(paper.getPath(), paper.getName(), paperId, title[0], doc.pageCount(), issues, error);
        } catch (IOException | RuntimeException e) {
            // A PDF that fails to open, such as a damaged or password-protected file, gives no issues.
            return new PaperResult(paper.getPath(), paper.getName(), paperId, null, 0, List.of(), describe(e));
        } finally {
            try {
                doc.close();
            } catch (IOException e) {
                err.printf("Error closing %s. %s%n", paper.getName(), e);
            }
        }
    }

    public void processPaper(File paper) {
        PaperResult result = checkPaper(paper);
        if (json) {
            out.println(result.toJson());
            return;
        }
        if (result.getError() != null) {
            // show error, but permit progressing to next paper.
            err.printf("Error processing %s. %s%n", result.getFileName(), result.getError());
        }
        // Like upstream, a PDF that did not open gets no result line.
        if (result.getPages() > 0 || result.getError() == null) {
            out.println(result.toText());
        }
    }

    private PaperMetaData getPaperMetaData(File paper) {
        if (meta == null) {
            return null;
        }
        PaperMetaData found = meta.forFile(paper);
        if (found == null) {
            err.printf("No author data for %s in the author CSV.%n", paper.getName());
        }
        return found;
    }

    public void displayPages(PdfDocument doc, String pages) {
        if (pages == null) {
            return;
        }
        if ("all".equals(pages)) {
            out.println(doc.fullText());
            return;
        }
        int pagenr = Integer.parseInt(pages);
        if (pagenr < 1 || pagenr > doc.pageCount()) {
            usage(String.format("Page nrs ``%d'' out of range for file %s", pagenr, doc.getFileName()));
        } else {
            out.printf("START-PAGE %d (of %d) %s: ---\n%sEND-PAGE\n%n", pagenr, doc.pageCount(), doc.getFileName(), doc.textAtPage(pagenr));
        }
    }

    /**
     * Run the checker on the arguments of the command line.
     * @param argv Options followed by PDF files and folders
     * @return {@link #EXIT_OK}, or {@link #EXIT_USAGE} if the arguments are wrong
     */
    public int run(String... argv) {
        Options options = defineOptions();

        CommandLine cmd;
        try {
            cmd = new DefaultParser().parse(options, argv);
        } catch(ParseException pe) {
            usage(pe.getMessage());
            return EXIT_USAGE;
        }

        if (cmd.hasOption("h")) {
            usage(null);
            return EXIT_OK;
        }

        List<File> papers;
        try {
            processOptions(cmd);
            papers = paperFiles(cmd.getArgs());
        } catch (IOException | RuntimeException e) {
            usage(e.getMessage());
            return EXIT_USAGE;
        }
        for (File paper : papers) {
            processPaper(paper);
        }
        return EXIT_OK;
    }

    private void processOptions(CommandLine cmd) throws IOException {
        this.style = cmd.getOptionValue("s", "IEEE").toUpperCase(Locale.ROOT);
        if (!style.equals("ACM") && !style.equals("IEEE")) {
            throw new IllegalArgumentException(String.format("Wrong style ``%s''; use ACM or IEEE.", style));
        }
        this.showText = cmd.getOptionValue("t", null);
        if (showText != null && !showText.equals("all") && MetaData.numericId(showText) == null) {
            throw new IllegalArgumentException(String.format("Wrong <pagenr> ``%s'' given to option showtext.", showText));
        }
        this.json = cmd.hasOption("json");
        if (json && showText != null) {
            throw new IllegalArgumentException("Option showtext prints page text, which --json cannot carry.");
        }
        this.flagAcknowledgments = cmd.hasOption("flag-acknowledgments");
        if (cmd.hasOption("id-pattern")) {
            idPattern = MetaData.compileIdPattern(cmd.getOptionValue("id-pattern"));
        }
        if (cmd.hasOption("allowed-hosts")) {
            links = new LinkClassifier(Arrays.asList(cmd.getOptionValue("allowed-hosts").split(",")));
        }
        if (cmd.hasOption("m")) {
            File csv = new File(cmd.getOptionValue("m"));
            if (!csv.isFile()) {
                throw new IllegalArgumentException(String.format("Author CSV file not found: %s", csv));
            }
            meta = new MetaData();
            meta.setIdPattern(idPattern);
            meta.loadHotCRPauthors(csv);
        }
        processPageLimitOptions(cmd);
    }

    private void processPageLimitOptions(CommandLine cmd) {
        var pageLimit = cmd.getOptionValue("p");
        var refLimit = cmd.getOptionValue("r");
        try {
            if (pageLimit != null) {
                PdfChecker.PAGE_LIMIT = Integer.parseInt(pageLimit);
            }
            if (refLimit != null) {
                PdfChecker.REFERENCE_LIMIT = Integer.parseInt(refLimit);
            }
        } catch (NumberFormatException nfe) {
            throw new IllegalArgumentException(String.format("Wrong page limit: ``%s''.", nfe.getMessage()));
        }
        if (PdfChecker.PAGE_LIMIT < 1 || PdfChecker.REFERENCE_LIMIT < 0) {
            throw new IllegalArgumentException("Wrong page limit: the main text needs 1 page or more, "
                    + "the references 0 pages or more.");
        }
    }

    @NotNull
    private Options defineOptions() {
        Options options = new Options();
        options.addOption("s", "style", true, "'ACM' or 'IEEE' style, default IEEE");
        options.addOption("h", "help", false, "Display help information");
        options.addOption("t", "showtext", true, "Display text of given page (nr, or 'all') on stdout");
        options.addOption("m", "meta", true, "CSV file with author meta-data.");
        options.addOption("p","mainpages", true, "Nr of pages for main text");
        options.addOption("r","refpages", true, "Nr of additional pages for references");
        options.addOption(Option.builder().longOpt("id-pattern").hasArg().argName("regex")
                .desc("Regular expression with one group that finds the paper ID in a file name").build());
        options.addOption(Option.builder().longOpt("allowed-hosts").hasArg().argName("hosts")
                .desc("Comma-separated hosts whose links never count as revealing").build());
        options.addOption(Option.builder().longOpt("flag-acknowledgments")
                .desc("Report an Acknowledgments heading").build());
        options.addOption(Option.builder().longOpt("json").desc("Print one JSON object per PDF").build());
        return options;
    }

    private static List<File> paperFiles(String[] argv) {
        if (argv.length == 0) {
            throw new IllegalArgumentException("No arguments provided, not processing any files.");
        }
        List<File> papers = new ArrayList<>();
        for (String arg: argv) {
            File farg = new File(arg);
            if (farg.isDirectory()) {
                File[] files = farg.listFiles((d, name) -> isPdfName(name) && new File(d, name).isFile());
                if (files != null) {
                    Arrays.sort(files);
                    papers.addAll(Arrays.asList(files));
                }
            } else if (isPdfName(arg) && farg.isFile()) {
                papers.add(farg);
            } else {
                throw new IllegalArgumentException(String.format("Argument not a file or folder: %s", arg));
            }
        }
        return papers;
    }

    private static boolean isPdfName(String name) {
        return name.toLowerCase(Locale.ROOT).endsWith(".pdf");
    }

    private static void runCheck(String check, List<String> failures, Runnable body) {
        try {
            body.run();
        } catch (RuntimeException | AssertionError e) {
            failures.add(String.format("%s check failed: %s", check, e));
        }
    }

    private static String describe(Exception e) {
        return e.getMessage() == null ? e.getClass().getSimpleName()
                : String.format("%s: %s", e.getClass().getSimpleName(), e.getMessage());
    }

    public void usage(String error) {
        if (error != null) {
            err.printf("ERROR: %s%n", error);
        }
        String tool = BatchChecker.class.getName();
        String msg = String.format("Usage: %s [options] [folder-with-pdfs...] [pdf-file ...]\n", tool);
        msg += "  Options:\n";
        msg += "  -s, --style <style>    Set style in ACM or IEEE, default IEEE\n";
        msg += "  -m, --meta <csv-file>  .csv file with author meta data. One row per author. Columns used:\n";
        msg += "                         paper,title,first,last,email and, if present, affiliation\n";
        msg += "  -p, --mainpages <N>    main text should be maximum N pages (default = 10)\n";
        msg += "  -r, --refpages <N>     nr of extra pages for references (default = 2)\n";
        msg += "  -h, --help             Show this information\n";
        msg += "  -t, --showtext <pages> Show plain text of pages on stdout. <pages> can be nr or 'all'\n";
        msg += "                         Combine with '... | grep ...' to fetch custom patterns\n";
        msg += "  --id-pattern <regex>   Regular expression with one group that finds the paper ID in a\n";
        msg += "                         file name, default " + MetaData.DEFAULT_ID_PATTERN + "\n";
        msg += "  --allowed-hosts <h,h>  Hosts whose links never count as revealing, such as zenodo.org\n";
        msg += "  --flag-acknowledgments Report an Acknowledgments heading\n";
        msg += "  --json                 Print one JSON object per PDF on one line\n";
        msg += "  The exit status is 0 unless the arguments are wrong (2).\n";
        err.println(msg);
    }

    public static void main(String[] argv) {
        int status = new BatchChecker().run(argv);
        if (status != EXIT_OK) {
            System.exit(status);
        }
    }
}
