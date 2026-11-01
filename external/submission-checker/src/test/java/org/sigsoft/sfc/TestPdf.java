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

import org.apache.pdfbox.cos.COSDictionary;
import org.apache.pdfbox.cos.COSName;
import org.apache.pdfbox.cos.COSString;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.common.PDMetadata;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.font.PDType1Font;
import org.apache.pdfbox.pdmodel.graphics.form.PDFormXObject;
import org.apache.pdfbox.pdmodel.interactive.action.PDActionURI;
import org.apache.pdfbox.pdmodel.interactive.annotation.PDAnnotationLink;
import org.apache.pdfbox.pdmodel.interactive.annotation.PDAnnotationText;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Builds small PDFs for the tests: pages of text lines, document information, XMP metadata,
 * link and note annotations, and figures that carry the PTEX entries pdfTeX writes.
 */
final class TestPdf {

    private final PDDocument pdf = new PDDocument();
    private final List<List<String>> pages = new ArrayList<>();
    private final List<Runnable> extras = new ArrayList<>();

    /**
     * Add a page with one text line per argument.
     * @param lines Lines of the page
     * @return This builder
     */
    TestPdf page(String... lines) {
        pages.add(List.of(lines));
        return this;
    }

    TestPdf info(String key, String value) {
        pdf.getDocumentInformation().getCOSObject().setString(COSName.getPDFName(key), value);
        return this;
    }

    TestPdf xmp(String packet) {
        extras.add(() -> {
            try {
                PDMetadata metadata = new PDMetadata(pdf,
                        new ByteArrayInputStream(packet.getBytes(StandardCharsets.UTF_8)));
                pdf.getDocumentCatalog().setMetadata(metadata);
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
        });
        return this;
    }

    TestPdf link(int pagenr, String uri) {
        extras.add(() -> {
            try {
                PDAnnotationLink link = new PDAnnotationLink();
                link.setRectangle(new PDRectangle(72, 72, 100, 12));
                PDActionURI action = new PDActionURI();
                action.setURI(uri);
                link.setAction(action);
                pdf.getPage(pagenr - 1).getAnnotations().add(link);
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
        });
        return this;
    }

    TestPdf note(int pagenr, String contents, String author) {
        extras.add(() -> {
            try {
                PDAnnotationText note = new PDAnnotationText();
                note.setRectangle(new PDRectangle(300, 300, 20, 20));
                note.setContents(contents);
                note.setTitlePopup(author);
                pdf.getPage(pagenr - 1).getAnnotations().add(note);
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
        });
        return this;
    }

    /**
     * Draw an empty figure on a page that carries PTEX entries, as pdfTeX writes for an included PDF.
     * Each value of the information dictionary is stored in UTF-16, like pdfTeX stores a non-ASCII value.
     * @param pagenr Page of the figure
     * @param infoDict Entries of PTEX.InfoDict
     * @param fileName Value of PTEX.FileName
     * @return This builder
     */
    TestPdf figure(int pagenr, Map<String, String> infoDict, String fileName) {
        extras.add(() -> {
            try {
                PDFormXObject form = new PDFormXObject(pdf);
                form.setBBox(new PDRectangle(0, 0, 10, 10));
                COSDictionary entries = new COSDictionary();
                for (Map.Entry<String, String> entry : infoDict.entrySet()) {
                    entries.setItem(COSName.getPDFName(entry.getKey()), new COSString(utf16(entry.getValue())));
                }
                form.getCOSObject().setItem(COSName.getPDFName("PTEX.InfoDict"), entries);
                form.getCOSObject().setItem(COSName.getPDFName("PTEX.FileName"), new COSString(fileName));
                PDPage page = pdf.getPage(pagenr - 1);
                try (PDPageContentStream content = new PDPageContentStream(pdf, page,
                        PDPageContentStream.AppendMode.APPEND, false)) {
                    content.drawForm(form);
                }
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
        });
        return this;
    }

    /**
     * Write the PDF.
     * @param folder Folder to write to
     * @param fileName Name of the file
     * @return The file
     * @throws IOException if the file cannot be written
     */
    File save(Path folder, String fileName) throws IOException {
        for (List<String> lines : pages) {
            PDPage page = new PDPage(PDRectangle.LETTER);
            pdf.addPage(page);
            try (PDPageContentStream content = new PDPageContentStream(pdf, page)) {
                content.beginText();
                content.setFont(PDType1Font.HELVETICA, 10);
                content.newLineAtOffset(72, 720);
                for (String line : lines) {
                    content.showText(line);
                    content.newLineAtOffset(0, -14);
                }
                content.endText();
            }
        }
        extras.forEach(Runnable::run);
        File file = folder.resolve(fileName).toFile();
        pdf.save(file);
        pdf.close();
        return file;
    }

    /**
     * Build an XMP packet with one creator and one contact email, as hyperxmp writes them.
     * @param creator Value of dc:creator
     * @param email Value of the IPTC contact email
     * @return The packet
     */
    static String xmpPacket(String creator, String email) {
        return "<?xpacket begin=\"\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n"
                + "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">"
                + "<rdf:Description rdf:about=\"\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\""
                + " xmlns:Iptc4xmpCore=\"http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/\" xmlns:xmp=\"http://ns.adobe.com/xap/1.0/\""
                + " xmp:CreatorTool=\"LaTeX with hyperref\">"
                + "<dc:creator><rdf:Seq><rdf:li>" + creator + "</rdf:li></rdf:Seq></dc:creator>"
                + "<Iptc4xmpCore:CreatorContactInfo rdf:parseType=\"Resource\">"
                + "<Iptc4xmpCore:CiEmailWork>" + email + "</Iptc4xmpCore:CiEmailWork>"
                + "</Iptc4xmpCore:CreatorContactInfo>"
                + "</rdf:Description></rdf:RDF></x:xmpmeta>\n<?xpacket end=\"w\"?>";
    }

    private static byte[] utf16(String text) {
        byte[] body = text.getBytes(StandardCharsets.UTF_16BE);
        byte[] bytes = new byte[body.length + 2];
        bytes[0] = (byte) 0xFE;
        bytes[1] = (byte) 0xFF;
        System.arraycopy(body, 0, bytes, 2, body.length);
        return bytes;
    }
}
