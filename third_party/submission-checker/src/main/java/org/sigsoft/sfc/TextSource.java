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

/**
 * A piece of text that a PDF holds outside its page text, such as a metadata entry or a link target,
 * with the place it comes from.
 */
public final class TextSource {

    /** The places in a PDF that hold text outside the page content. */
    public enum Kind {
        INFO, XMP, FIGURE_INFO, FIGURE_FILE, LINK_TARGET, ANNOTATION_TEXT, ANNOTATION_AUTHOR
    }

    @NotNull
    private final Kind kind;

    @NotNull
    private final String label;

    private final Integer page;

    @NotNull
    private final String text;

    /**
     * Create a source.
     * @param kind Place the text comes from
     * @param label Human-readable name of the place, such as "document information Author"
     * @param page Page the text belongs to, or null for document-level text
     * @param text The text
     */
    public TextSource(@NotNull Kind kind, @NotNull String label, Integer page, @NotNull String text) {
        this.kind = kind;
        this.label = label;
        this.page = page;
        this.text = text;
    }

    @NotNull
    public Kind getKind() {
        return kind;
    }

    @NotNull
    public String getLabel() {
        return label;
    }

    public Integer getPage() {
        return page;
    }

    @NotNull
    public String getText() {
        return text;
    }
}
