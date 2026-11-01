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

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Finds web links in text and sorts out the links that can reveal an author: a user or an organization on
 * a code host, a personal or staff page, or a cloud drive share. Links to an allowed host never count.
 * The classifier never fetches a link.
 */
public final class LinkClassifier {

    /** The kinds of links that can reveal an author. */
    public enum Kind {
        CODE_HOST_ACCOUNT("code host account"),
        PERSONAL_PAGE("personal page"),
        CLOUD_SHARE("cloud drive share");

        private final String description;

        Kind(String description) {
            this.description = description;
        }

        public String getDescription() {
            return description;
        }
    }

    private static final String URL_CHARS = "[^\\s<>\"'{}|\\\\^`\\[\\]]";
    private static final Pattern URL = Pattern.compile(
            "(?:\\bhttps?://|\\bwww\\.)" + URL_CHARS + "+"
                    + "|\\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}/" + URL_CHARS + "*",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern SCHEME = Pattern.compile("^[a-z][a-z0-9+.-]*:(?://)?", Pattern.CASE_INSENSITIVE);
    private static final String TRAILING_PUNCTUATION = ".,;:!?)]}'\"";

    private static final Set<String> CODE_HOSTS = Set.of(
            "github.com", "gist.github.com", "raw.githubusercontent.com", "gitlab.com", "bitbucket.org");
    private static final Set<String> CODE_HOST_PAGES = Set.of("github.io", "gitlab.io", "bitbucket.io");
    // First path segments of a code host that name a page of the host itself, never an account.
    private static final Set<String> CODE_HOST_RESERVED = Set.of(
            "about", "features", "topics", "collections", "trending", "explore", "marketplace", "pricing",
            "enterprise", "security", "site", "login", "join", "signup", "settings", "search", "contact",
            "readme", "customer-stories", "events", "help", "dashboard", "product", "blog", "docs");
    // First path segments after which the next segment names the account.
    private static final Set<String> CODE_HOST_ACCOUNT_PREFIXES = Set.of("orgs", "users", "groups", "sponsors", "u");
    private static final Set<String> PERSONAL_HOST_LABELS = Set.of(
            "people", "person", "homes", "homepages", "staff", "users", "faculty", "personal", "www-personal");
    private static final Set<String> PERSONAL_PATH_SEGMENTS = Set.of(
            "people", "person", "persons", "staff", "faculty", "homes", "users", "members", "member",
            "employees", "employee", "researchers", "researcher", "profile", "profiles", "team");
    private static final Set<String> PROFILE_HOSTS = Set.of(
            "orcid.org", "about.me", "twitter.com", "x.com", "sites.google.com");
    private static final Set<String> CLOUD_HOSTS = Set.of(
            "drive.google.com", "docs.google.com", "dropbox.com", "dropboxusercontent.com", "onedrive.live.com",
            "1drv.ms", "sharepoint.com", "box.com", "icloud.com", "mega.nz", "wetransfer.com", "we.tl");

    private final List<String> allowedHosts;

    /**
     * Create a classifier.
     * @param allowedHosts Hosts whose links never count, such as zenodo.org; a host also allows its subdomains
     */
    public LinkClassifier(@NotNull Collection<String> allowedHosts) {
        this.allowedHosts = allowedHosts.stream()
                .map(LinkClassifier::host)
                .filter(h -> !h.isEmpty())
                .collect(Collectors.toList());
    }

    /**
     * Find the web links in a text, such as https://example.org/a or github.com/user.
     * @param text Text to search
     * @return The links in text order, without trailing punctuation
     */
    public static List<String> linksInText(@NotNull String text) {
        List<String> links = new ArrayList<>();
        Matcher matcher = URL.matcher(text);
        while (matcher.find()) {
            String link = matcher.group();
            int end = link.length();
            while (end > 0 && TRAILING_PUNCTUATION.indexOf(link.charAt(end - 1)) >= 0) {
                end--;
            }
            if (end > 0) {
                links.add(link.substring(0, end));
            }
        }
        return links;
    }

    /**
     * Return the host of a link in lower case, without scheme, user, port, or a final dot.
     * @param link A link with or without scheme, such as https://www.github.com/user or zenodo.org
     * @return The host, or an empty string if the link has none
     */
    public static String host(@NotNull String link) {
        String rest = SCHEME.matcher(link.strip()).replaceFirst("");
        int end = 0;
        while (end < rest.length() && "/?#".indexOf(rest.charAt(end)) < 0) {
            end++;
        }
        String authority = rest.substring(0, end);
        authority = authority.substring(authority.lastIndexOf('@') + 1);
        int port = authority.indexOf(':');
        if (port >= 0) {
            authority = authority.substring(0, port);
        }
        while (authority.endsWith(".")) {
            authority = authority.substring(0, authority.length() - 1);
        }
        return authority.toLowerCase(Locale.ROOT);
    }

    /**
     * Decide whether a link can reveal an author.
     * @param link A web link, with or without scheme
     * @return The kind of revealing link, or null if the link is allowed, is no web link, or reveals no one
     */
    public Kind classify(@NotNull String link) {
        String trimmed = link.strip();
        Matcher scheme = SCHEME.matcher(trimmed);
        if (scheme.find() && !scheme.group().toLowerCase(Locale.ROOT).matches("https?://")) {
            return null;
        }
        String host = host(trimmed);
        if (host.isEmpty() || isAllowed(host)) {
            return null;
        }
        String bareHost = host.startsWith("www.") ? host.substring(4) : host;
        List<String> segments = pathSegments(trimmed);
        if (CODE_HOSTS.contains(bareHost)) {
            return codeHostAccount(segments) ? Kind.CODE_HOST_ACCOUNT : null;
        }
        if (isUnder(bareHost, CODE_HOST_PAGES) && !CODE_HOST_PAGES.contains(bareHost)) {
            return Kind.CODE_HOST_ACCOUNT;
        }
        if (isPersonalPage(bareHost, segments, trimmed)) {
            return Kind.PERSONAL_PAGE;
        }
        if (isUnder(bareHost, CLOUD_HOSTS) && !segments.isEmpty()) {
            return Kind.CLOUD_SHARE;
        }
        return null;
    }

    private boolean isAllowed(String host) {
        return allowedHosts.stream().anyMatch(allowed -> host.equals(allowed) || host.endsWith("." + allowed));
    }

    private static boolean codeHostAccount(List<String> segments) {
        if (segments.isEmpty()) {
            return false;
        }
        String first = segments.get(0).toLowerCase(Locale.ROOT);
        if (CODE_HOST_ACCOUNT_PREFIXES.contains(first)) {
            return segments.size() > 1;
        }
        return !CODE_HOST_RESERVED.contains(first);
    }

    private static boolean isPersonalPage(String host, List<String> segments, String link) {
        if (segments.stream().anyMatch(s -> s.startsWith("~") || s.toLowerCase(Locale.ROOT).startsWith("%7e"))) {
            return true;
        }
        String firstLabel = host.substring(0, Math.max(host.indexOf('.'), 0));
        if (PERSONAL_HOST_LABELS.contains(firstLabel) && !segments.isEmpty()) {
            return true;
        }
        for (int i = 0; i + 1 < segments.size(); i++) {
            if (PERSONAL_PATH_SEGMENTS.contains(segments.get(i).toLowerCase(Locale.ROOT))) {
                return true;
            }
        }
        if (PROFILE_HOSTS.contains(host)) {
            return !segments.isEmpty();
        }
        String path = String.join("/", segments).toLowerCase(Locale.ROOT);
        return host.matches("scholar\\.google\\.[a-z.]+") && link.toLowerCase(Locale.ROOT).contains("user=")
                || host.matches("(dblp\\.org|dblp\\.uni-trier\\.de|dblp\\.dagstuhl\\.de)")
                && (path.startsWith("pid/") || path.startsWith("pers/"))
                || host.endsWith("linkedin.com") && path.startsWith("in/")
                || host.endsWith("researchgate.net") && path.startsWith("profile/")
                || host.endsWith("semanticscholar.org") && path.startsWith("author/");
    }

    private static boolean isUnder(String host, Set<String> domains) {
        return domains.stream().anyMatch(domain -> host.equals(domain) || host.endsWith("." + domain));
    }

    private static List<String> pathSegments(String link) {
        String rest = SCHEME.matcher(link).replaceFirst("");
        int slash = rest.indexOf('/');
        if (slash < 0) {
            return List.of();
        }
        String path = rest.substring(slash + 1);
        int query = indexOfAny(path, "?#");
        if (query >= 0) {
            path = path.substring(0, query);
        }
        return Arrays.stream(path.split("/")).filter(s -> !s.isEmpty()).collect(Collectors.toList());
    }

    private static int indexOfAny(String text, String chars) {
        for (int i = 0; i < text.length(); i++) {
            if (chars.indexOf(text.charAt(i)) >= 0) {
                return i;
            }
        }
        return -1;
    }
}
