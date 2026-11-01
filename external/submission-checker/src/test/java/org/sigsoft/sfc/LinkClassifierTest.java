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

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** Links to code host accounts, personal pages, and cloud drive shares count unless their host is allowed. */
public class LinkClassifierTest {

    private final LinkClassifier links = new LinkClassifier(
            List.of("anonymous.4open.science", "zenodo.org", "figshare.com", "osf.io", "doi.org"));

    @ParameterizedTest
    @CsvSource({
            "https://github.com/annalindqvist/effort-study, CODE_HOST_ACCOUNT",
            "github.com/annalindqvist, CODE_HOST_ACCOUNT",
            "https://www.github.com/orgs/kth-se/repositories, CODE_HOST_ACCOUNT",
            "https://gitlab.com/alindqvist/tool, CODE_HOST_ACCOUNT",
            "https://bitbucket.org/alindqvist/tool, CODE_HOST_ACCOUNT",
            "https://raw.githubusercontent.com/alindqvist/tool/main/data.csv, CODE_HOST_ACCOUNT",
            "https://annalindqvist.github.io/, CODE_HOST_ACCOUNT",
            "https://www.cs.kth.se/~alind/, PERSONAL_PAGE",
            "https://people.kth.se/alind, PERSONAL_PAGE",
            "https://www.kth.se/profile/alind/page, PERSONAL_PAGE",
            "https://orcid.org/0000-0002-1825-0097, PERSONAL_PAGE",
            "https://scholar.google.com/citations?user=abc123, PERSONAL_PAGE",
            "https://dblp.org/pid/12/3456.html, PERSONAL_PAGE",
            "https://www.linkedin.com/in/annalindqvist, PERSONAL_PAGE",
            "https://drive.google.com/file/d/1AbCdEf/view?usp=sharing, CLOUD_SHARE",
            "https://www.dropbox.com/s/abc123/data.zip, CLOUD_SHARE",
            "https://kth-my.sharepoint.com/:f:/g/personal/alind/folder, CLOUD_SHARE",
            "https://1drv.ms/u/s!abc, CLOUD_SHARE",
    })
    void revealingLinksAreClassified(String link, LinkClassifier.Kind kind) {
        assertThat(links.classify(link)).isEqualTo(kind);
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "https://anonymous.4open.science/r/effort-study-1234",
            "https://zenodo.org/records/1234567",
            "https://sandbox.zenodo.org/records/1",
            "https://doi.org/10.5281/zenodo.1234567",
            "https://osf.io/abcde/?view_only=0123",
            "https://github.com",
            "https://github.com/features/actions",
            "https://www.example.org/tool",
            "mailto:anna.lindqvist@kth.se",
            "https://www.dropbox.com",
    })
    void otherLinksAreNotFlagged(String link) {
        assertThat(links.classify(link)).isNull();
    }

    @Test
    void allowedHostCoversItsSubdomains() {
        LinkClassifier allowGithub = new LinkClassifier(List.of(" https://GitHub.com/ "));
        assertThat(allowGithub.classify("https://github.com/annalindqvist")).isNull();
        assertThat(allowGithub.classify("https://gist.github.com/annalindqvist/abc")).isNull();
        assertThat(allowGithub.classify("https://gitlab.com/annalindqvist")).isEqualTo(LinkClassifier.Kind.CODE_HOST_ACCOUNT);
    }

    @Test
    void linksInTextLoseTrailingPunctuation() {
        assertThat(LinkClassifier.linksInText(
                "See https://github.com/janedoe/mytool. Data at (www.cs.kth.se/~alind), or gitlab.com/x/y;"))
                .containsExactly("https://github.com/janedoe/mytool", "www.cs.kth.se/~alind", "gitlab.com/x/y");
    }

    @Test
    void wordsWithDotsAreNoLinks() {
        assertThat(LinkClassifier.linksInText("e.g. Fig. 3/4 and version 2.0/3.0, i.e./et al.")).isEmpty();
    }

    @Test
    void hostIsReadWithoutSchemeUserPortOrCase() {
        assertThat(LinkClassifier.host("HTTPS://user@WWW.Example.org:8080/a?b")).isEqualTo("www.example.org");
        assertThat(LinkClassifier.host("zenodo.org.")).isEqualTo("zenodo.org");
    }
}
