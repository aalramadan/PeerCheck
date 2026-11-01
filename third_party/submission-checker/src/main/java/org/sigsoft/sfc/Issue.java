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

import java.util.Objects;

/**
 * One problem found in a paper: a code such as {@code oversize}, its evidence, and the page
 * it was found on, or null where no single page applies.
 */
public final class Issue {

    @NotNull
    private final String code;

    @NotNull
    private final String detail;

    private final Integer page;

    // The upstream text format quotes found text, such as an email, and leaves values, such as a page count, bare.
    private final boolean quoted;

    private Issue(@NotNull String code, @NotNull String detail, Integer page, boolean quoted) {
        this.code = code;
        this.detail = detail;
        this.page = page;
        this.quoted = quoted;
    }

    /**
     * Create an issue whose detail is text found in the paper, such as a phrase or an email.
     * @param code Issue code, such as previous-work-mentioned
     * @param detail The text found
     * @param page Page of the text, or null
     * @return The issue
     */
    public static Issue text(@NotNull String code, @NotNull String detail, Integer page) {
        return new Issue(code, detail, page, true);
    }

    /**
     * Create an issue whose detail is a value, such as a page count.
     * @param code Issue code, such as oversize
     * @param detail The value
     * @param page Page the value refers to, or null
     * @return The issue
     */
    public static Issue value(@NotNull String code, @NotNull String detail, Integer page) {
        return new Issue(code, detail, page, false);
    }

    @NotNull
    public String getCode() {
        return code;
    }

    @NotNull
    public String getDetail() {
        return detail;
    }

    public Integer getPage() {
        return page;
    }

    /**
     * Render the issue in the upstream text format, such as {@code oversize:23}
     * or {@code author-revealing-email:``a@b.org''}.
     * @return The issue as text
     */
    public String toText() {
        return quoted ? String.format("%s:``%s''", code, detail) : String.format("%s:%s", code, detail);
    }

    @Override
    public boolean equals(Object other) {
        if (!(other instanceof Issue)) {
            return false;
        }
        Issue that = (Issue) other;
        return code.equals(that.code) && detail.equals(that.detail) && Objects.equals(page, that.page);
    }

    @Override
    public int hashCode() {
        return Objects.hash(code, detail, page);
    }

    @Override
    public String toString() {
        return page == null ? toText() : toText() + "@p" + page;
    }
}
