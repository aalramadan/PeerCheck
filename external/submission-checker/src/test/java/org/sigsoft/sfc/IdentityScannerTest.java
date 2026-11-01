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
import org.junit.jupiter.params.provider.ValueSource;

import java.util.List;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/** Names match as whole words in their usual forms; emails and affiliations match as whole phrases. */
public class IdentityScannerTest {

    private static List<String> found(String text, Author... authors) {
        FoldedText folded = FoldedText.of(text);
        return new IdentityScanner(List.of(authors)).find(folded).stream()
                .map(span -> folded.evidence(span[0], span[1]))
                .collect(Collectors.toList());
    }

    private static Author author(String first, String last, String email, String affiliation) {
        Author author = new Author();
        author.setFirstName(first);
        author.setLastName(last);
        author.setEmail(email);
        author.setAffiliation(affiliation);
        return author;
    }

    private static final Author ANNA = author("Anna", "Lindqvist", "anna.lindqvist@kth.se",
            "KTH Royal Institute of Technology");

    @ParameterizedTest
    @ValueSource(strings = {"Anna Lindqvist", "Lindqvist, Anna", "A. Lindqvist", "A.Lindqvist", "Lindqvist, A.",
            "Anna M. Lindqvist", "ANNA LINDQVIST", "Anna\nLindqvist", "A. M. Lindqvist"})
    void nameFormsAreFound(String form) {
        assertThat(found("As shown by " + form + " in 2020.", ANNA)).hasSize(1);
    }

    @ParameterizedTest
    @ValueSource(strings = {"Annalindqvist", "Anna Lindqvists", "Lindqvist alone", "Johanna Lindqvist",
            "B. Lindqvist", "Anna Berg"})
    void partsOfOtherWordsOrOtherPeopleAreNotFound(String text) {
        assertThat(found(text, ANNA)).isEmpty();
    }

    @Test
    void accentsAreIgnoredInTheTextAndInTheAuthorList() {
        Author jorg = author("Jörg", "Müller", "", "");
        assertThat(found("We thank Jorg Muller.", jorg)).containsExactly("Jorg Muller");
        assertThat(found("We thank Jörg Müller.", author("Jorg", "Muller", "", ""))).hasSize(1);
    }

    @Test
    void emailMatchesAsAWholePhrase() {
        assertThat(found("mail anna.lindqvist@kth.se now", ANNA)).containsExactly("anna.lindqvist@kth.se");
        assertThat(found("mail ANNA.LINDQVIST @ KTH.SE now", ANNA)).hasSize(1);
        assertThat(found("mail xanna.lindqvist@kth.se.com now", ANNA)).isEmpty();
    }

    @Test
    void emailInAGroupOfLocalPartsIsFound() {
        assertThat(found("{erik.berg, anna.lindqvist}@kth.se", ANNA))
                .containsExactly("{erik.berg, anna.lindqvist}@kth.se");
    }

    @Test
    void affiliationMatchesAsAWholePhrase() {
        assertThat(found("Work done at KTH Royal\nInstitute of Technology, Sweden.", ANNA))
                .containsExactly("KTH Royal Institute of Technology");
        assertThat(found("Work done at KTH Royal Institute.", ANNA)).isEmpty();
    }

    @Test
    void missingAffiliationValuesAreSkipped() {
        assertThat(found("n/a and N/A", author("Anna", "Lindqvist", "", "N/A"))).isEmpty();
    }

    @Test
    void firstGivenNameAloneAlsoMatches() {
        Author maria = author("Maria José", "García", "", "");
        assertThat(found("by Maria Garcia and García, Maria José", maria)).hasSize(2);
    }
}
