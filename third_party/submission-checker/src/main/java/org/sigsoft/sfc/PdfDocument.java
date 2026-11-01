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

import org.apache.pdfbox.cos.COSBase;
import org.apache.pdfbox.cos.COSDictionary;
import org.apache.pdfbox.cos.COSName;
import org.apache.pdfbox.cos.COSStream;
import org.apache.pdfbox.cos.COSString;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDDocumentInformation;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.common.PDMetadata;
import org.apache.pdfbox.pdmodel.interactive.action.PDAction;
import org.apache.pdfbox.pdmodel.interactive.action.PDActionURI;
import org.apache.pdfbox.pdmodel.interactive.annotation.PDAnnotation;
import org.apache.pdfbox.pdmodel.interactive.annotation.PDAnnotationLink;
import org.apache.pdfbox.pdmodel.interactive.annotation.PDAnnotationMarkup;
import org.apache.pdfbox.text.PDFTextStripper;
import org.jetbrains.annotations.NotNull;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Access content of Pdf documents.
 *
 * Serves as simple wrapper around Apache PDFBox.
 * Helps in testing as it can be easily mocked.
 */
public class PdfDocument implements AutoCloseable {

    private static final COSName PTEX_INFO_DICT = COSName.getPDFName("PTEX.InfoDict");
    private static final COSName PTEX_FILE_NAME = COSName.getPDFName("PTEX.FileName");
    private static final String FIGURE_AUTHOR = figureInfoLabel("Author");
    private static final String FIGURE_XMP_CREATOR = "figure XMP dc:creator";

    @NotNull
    private PDDocument pdf;

    @NotNull
    private String fileName;

    // Every check reads the page text, therefore each page is extracted once.
    private String[] pageTexts;

    private List<TextSource> figures;

    private List<TextSource> figureAuthors;

    private XmpText xmp;

    private final List<String> problems = new ArrayList<>();

    public void loadFile(File paperFile) throws IOException {
        this.fileName = paperFile.getName();
        this.pdf = PDDocument.load(paperFile);
    }

    public void loadResource(String fileName) throws IOException {
        this.fileName = fileName;
        InputStream input = getClass().getClassLoader().getResourceAsStream(fileName);
        pdf = PDDocument.load(input);
    }

    @NotNull
    public String getFileName() {
        return fileName;
    }

    public void close() throws IOException {
        if (pdf != null) {
            pdf.close();
        }
    }

    public int pageCount() {
        return pdf.getNumberOfPages();
    }

    public String fullText() {
        try {
            PDFTextStripper stripper = new PDFTextStripper();
            return stripper.getText(pdf);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }

    /**
     * Return the text of a specific page.
     * A page whose text cannot be extracted reads as empty and is listed in {@link #problems()}.
     *
     * @param pagenr Number of page to extract (ranges from 1 to nr of pages).
     * @return The text of the page
     */
    public String textAtPage(int pagenr) {
        assert pagenr > 0;
        assert pagenr <= pageCount();

        if (pageTexts == null) {
            pageTexts = new String[pageCount()];
        }
        if (pageTexts[pagenr - 1] == null) {
            try {
                // See https://stackoverflow.com/a/15689797/165292
                PDFTextStripper reader = new PDFTextStripper();
                reader.setStartPage(pagenr);
                reader.setEndPage(pagenr);
                pageTexts[pagenr - 1] = reader.getText(pdf);
            } catch (IOException | RuntimeException e) {
                problems.add(String.format("text of page %d not extracted: %s", pagenr, e));
                pageTexts[pagenr - 1] = "";
            }
        }
        return pageTexts[pagenr - 1];
    }

    /**
     * Check whether authors set their name in the pdf's meta-data.
     * Note: Set to "Anonymous Author(s)" when using ACM style properly.
     * @return Null if no name was given, actual name otherwise.
     */
    public String metaDataAuthor() {
        PDDocumentInformation pdi = pdf.getDocumentInformation();
        String metaAuthor = pdi.getAuthor();
        if (metaAuthor != null) {
            String stripped = metaAuthor.strip();
            return stripped.equals("")? null: stripped;
        } else {
            return null;
        }
    }

    /**
     * Check whether creating tool was set in pdf's meta-data.
     * Done, for example when ACM style is used properly, which then sets it to
     * "LaTeX with acmart ..."
     * @return Null if no tool was mentioned, name of tool otherwise.
     */
    public String metaDataCreator() {
        PDDocumentInformation pdi = pdf.getDocumentInformation();
        String creator = pdi.getCreator();
        if (creator == null || creator.equals("")) {
            return null;
        } else {
            return creator;
        }
    }

    public String metaDataTitle() {
        PDDocumentInformation pdi = pdf.getDocumentInformation();
        String title = pdi.getTitle();
        if (title == null) {
            return null;
        }
        title = title.strip();
        if (title.equals("")) {
            return null;
        }
        return title;
    }

    /**
     * Return every author name the metadata holds: the Author of the document information,
     * the creators of the XMP metadata, and the Author of the metadata of each embedded figure.
     * @return The names with their places
     */
    public List<TextSource> metaDataAuthors() {
        List<TextSource> authors = new ArrayList<>();
        String infoAuthor = metaDataAuthor();
        if (infoAuthor != null) {
            authors.add(new TextSource(TextSource.Kind.INFO, "document information Author", null, infoAuthor));
        }
        for (String creator : documentXmp().getCreators()) {
            authors.add(new TextSource(TextSource.Kind.XMP, "XMP dc:creator", null, creator));
        }
        readFigures();
        authors.addAll(figureAuthors);
        return authors;
    }

    /**
     * Return all text that the PDF holds outside its page text: the document information, the XMP
     * metadata, the metadata and file names of embedded figures, and the annotations of each page.
     * @return The texts with their places
     */
    public List<TextSource> embeddedSources() {
        List<TextSource> sources = new ArrayList<>(infoEntries());
        String xmp = documentXmp().getText();
        if (!xmp.isBlank()) {
            sources.add(new TextSource(TextSource.Kind.XMP, "XMP metadata", null, xmp));
        }
        readFigures();
        sources.addAll(figures);
        for (int pagenr = 1; pagenr <= pageCount(); pagenr++) {
            sources.addAll(annotationTexts(pagenr));
        }
        return sources;
    }

    /**
     * Return the targets of the web links on a page.
     * @param pagenr Page number, from 1
     * @return The link targets, such as https://github.com/user
     */
    public List<String> linkTargets(int pagenr) {
        return annotationTexts(pagenr).stream()
                .filter(source -> source.getKind() == TextSource.Kind.LINK_TARGET)
                .map(TextSource::getText)
                .collect(Collectors.toList());
    }

    /**
     * Return the problems met while reading the PDF, such as a page whose text could not be extracted.
     * @return The problems, empty if none
     */
    public List<String> problems() {
        return Collections.unmodifiableList(problems);
    }

    private List<TextSource> infoEntries() {
        List<TextSource> entries = new ArrayList<>();
        COSDictionary info = pdf.getDocumentInformation().getCOSObject();
        for (COSName key : info.keySet()) {
            COSBase value = info.getDictionaryObject(key);
            if (value instanceof COSString) {
                addSource(entries, TextSource.Kind.INFO, "document information " + key.getName(), null,
                        ((COSString) value).getString());
            }
        }
        return entries;
    }

    private XmpText documentXmp() {
        if (xmp == null) {
            xmp = XmpText.empty();
            PDMetadata metadata = pdf.getDocumentCatalog().getMetadata();
            if (metadata != null) {
                try (InputStream in = metadata.exportXMPMetadata()) {
                    xmp = XmpText.parse(in.readAllBytes());
                } catch (IOException | RuntimeException e) {
                    problems.add("XMP metadata not read: " + e);
                }
            }
        }
        return xmp;
    }

    private List<TextSource> annotationTexts(int pagenr) {
        List<TextSource> texts = new ArrayList<>();
        try {
            for (PDAnnotation annotation : pdf.getPage(pagenr - 1).getAnnotations()) {
                if (annotation instanceof PDAnnotationLink) {
                    PDAction action = ((PDAnnotationLink) annotation).getAction();
                    if (action instanceof PDActionURI) {
                        addSource(texts, TextSource.Kind.LINK_TARGET, "link target", pagenr,
                                ((PDActionURI) action).getURI());
                    }
                }
                addSource(texts, TextSource.Kind.ANNOTATION_TEXT, "annotation text", pagenr,
                        annotation.getContents());
                if (annotation instanceof PDAnnotationMarkup) {
                    addSource(texts, TextSource.Kind.ANNOTATION_AUTHOR, "annotation author", pagenr,
                            ((PDAnnotationMarkup) annotation).getTitlePopup());
                }
            }
        } catch (IOException | RuntimeException e) {
            problems.add(String.format("annotations of page %d not read: %s", pagenr, e));
        }
        return texts;
    }

    private void readFigures() {
        if (figures != null) {
            return;
        }
        figures = new ArrayList<>();
        figureAuthors = new ArrayList<>();
        Set<COSBase> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        for (int pagenr = 1; pagenr <= pageCount(); pagenr++) {
            try {
                PDPage page = pdf.getPage(pagenr - 1);
                if (page.getResources() != null) {
                    collectFigures(page.getResources().getCOSObject(), pagenr, seen);
                }
            } catch (IOException | RuntimeException e) {
                problems.add(String.format("figures of page %d not read: %s", pagenr, e));
            }
        }
    }

    private void collectFigures(COSDictionary resources, int pagenr, Set<COSBase> seen) throws IOException {
        COSBase xobjects = resources.getDictionaryObject(COSName.XOBJECT);
        if (!(xobjects instanceof COSDictionary)) {
            return;
        }
        for (COSName name : ((COSDictionary) xobjects).keySet()) {
            COSBase object = ((COSDictionary) xobjects).getDictionaryObject(name);
            if (!(object instanceof COSStream) || !seen.add(object)) {
                continue;
            }
            COSStream form = (COSStream) object;
            if (!COSName.FORM.equals(form.getCOSName(COSName.SUBTYPE))) {
                continue;
            }
            // pdfTeX copies the document information of an included PDF figure into PTEX.InfoDict.
            COSBase info = form.getDictionaryObject(PTEX_INFO_DICT);
            if (info instanceof COSDictionary) {
                COSDictionary entries = (COSDictionary) info;
                for (COSName key : entries.keySet()) {
                    COSBase value = entries.getDictionaryObject(key);
                    if (value instanceof COSString) {
                        String text = ((COSString) value).getString();
                        addSource(figures, TextSource.Kind.FIGURE_INFO, figureInfoLabel(key.getName()), pagenr, text);
                        if (key.getName().equals("Author")) {
                            addSource(figureAuthors, TextSource.Kind.FIGURE_INFO, FIGURE_AUTHOR, pagenr, text);
                        }
                    }
                }
            }
            COSBase file = form.getDictionaryObject(PTEX_FILE_NAME);
            if (file instanceof COSString) {
                addSource(figures, TextSource.Kind.FIGURE_FILE, "figure file name (PTEX.FileName)", pagenr,
                        ((COSString) file).getString());
            }
            COSBase metadata = form.getDictionaryObject(COSName.METADATA);
            if (metadata instanceof COSStream) {
                try (InputStream in = ((COSStream) metadata).createInputStream()) {
                    XmpText figureXmp = XmpText.parse(in.readAllBytes());
                    addSource(figures, TextSource.Kind.XMP, "figure XMP metadata", pagenr, figureXmp.getText());
                    for (String creator : figureXmp.getCreators()) {
                        addSource(figureAuthors, TextSource.Kind.XMP, FIGURE_XMP_CREATOR, pagenr, creator);
                    }
                }
            }
            COSBase inner = form.getDictionaryObject(COSName.RESOURCES);
            if (inner instanceof COSDictionary) {
                collectFigures((COSDictionary) inner, pagenr, seen);
            }
        }
    }

    private static String figureInfoLabel(String key) {
        return String.format("figure metadata (PTEX.InfoDict %s)", key);
    }

    private static void addSource(List<TextSource> sources, TextSource.Kind kind, String label, Integer pagenr,
                                  String text) {
        if (text != null && !text.isBlank()) {
            sources.add(new TextSource(kind, label, pagenr, text.strip()));
        }
    }
}
