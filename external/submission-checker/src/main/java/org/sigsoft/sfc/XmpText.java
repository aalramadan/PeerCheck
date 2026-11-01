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
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NamedNodeMap;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;
import org.xml.sax.SAXException;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.parsers.ParserConfigurationException;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * The text values of an XMP metadata packet, with the names it lists as creators (dc:creator).
 */
public final class XmpText {

    private static final String DUBLIN_CORE = "http://purl.org/dc/elements/1.1/";
    private static final Pattern TAG = Pattern.compile("<[^>]*>");
    private static final Set<String> SYNTAX_ATTRIBUTES = Set.of("rdf:about", "rdf:parseType", "x:xmptk");

    @NotNull
    private final String text;

    @NotNull
    private final List<String> creators;

    private XmpText(@NotNull String text, @NotNull List<String> creators) {
        this.text = text;
        this.creators = creators;
    }

    /**
     * Read an XMP packet. A packet that is no well-formed XML falls back to its text without tags.
     * @param packet Bytes of the packet
     * @return Its text values and creators
     */
    public static XmpText parse(byte[] packet) {
        try {
            Document xml = secureFactory().newDocumentBuilder().parse(new ByteArrayInputStream(packet));
            StringBuilder values = new StringBuilder();
            collectText(xml.getDocumentElement(), values);
            List<String> creators = new ArrayList<>();
            NodeList creatorNodes = xml.getElementsByTagNameNS(DUBLIN_CORE, "creator");
            for (int i = 0; i < creatorNodes.getLength(); i++) {
                NodeList items = ((Element) creatorNodes.item(i)).getElementsByTagNameNS("*", "li");
                for (int j = 0; j < items.getLength(); j++) {
                    addValue(creators, items.item(j).getTextContent());
                }
                if (items.getLength() == 0) {
                    addValue(creators, creatorNodes.item(i).getTextContent());
                }
            }
            return new XmpText(values.toString(), Collections.unmodifiableList(creators));
        } catch (ParserConfigurationException | SAXException | IOException e) {
            String raw = new String(packet, StandardCharsets.UTF_8);
            return new XmpText(TAG.matcher(raw).replaceAll("\n"), List.of());
        }
    }

    /**
     * Return the reading of a document without XMP metadata.
     * @return No text and no creators
     */
    public static XmpText empty() {
        return new XmpText("", List.of());
    }

    @NotNull
    public String getText() {
        return text;
    }

    @NotNull
    public List<String> getCreators() {
        return creators;
    }

    private static DocumentBuilderFactory secureFactory() throws ParserConfigurationException {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        factory.setXIncludeAware(false);
        factory.setExpandEntityReferences(false);
        return factory;
    }

    private static void collectText(Node node, StringBuilder values) {
        // XMP may write a simple property as an attribute, such as pdf:Producer="...".
        NamedNodeMap attributes = node.getAttributes();
        for (int i = 0; attributes != null && i < attributes.getLength(); i++) {
            Node attribute = attributes.item(i);
            String name = attribute.getNodeName();
            if (!name.startsWith("xmlns") && !SYNTAX_ATTRIBUTES.contains(name)) {
                String value = attribute.getNodeValue().strip();
                if (!value.isEmpty()) {
                    values.append(value).append('\n');
                }
            }
        }
        for (Node child = node.getFirstChild(); child != null; child = child.getNextSibling()) {
            if (child.getNodeType() == Node.TEXT_NODE || child.getNodeType() == Node.CDATA_SECTION_NODE) {
                String value = child.getNodeValue().strip();
                if (!value.isEmpty()) {
                    values.append(value).append('\n');
                }
            } else if (child.getNodeType() == Node.ELEMENT_NODE) {
                collectText(child, values);
            }
        }
    }

    private static void addValue(List<String> values, String value) {
        String stripped = value == null ? "" : value.strip();
        if (!stripped.isEmpty()) {
            values.add(stripped);
        }
    }
}
