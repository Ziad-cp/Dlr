package io.github.ziadcp.dlr;

import java.net.Inet4Address;
import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * The same link rules as the desktop app (safety.py): web links only, a sane length, no hidden
 * characters, no logins in the link, and never this phone or the local network.
 */
public final class LinkCheck {
    public static final int MAX_URL_LENGTH = 2048;

    /** Rejected input; the message is safe to show to the user. */
    public static final class BadLink extends Exception {
        public BadLink(String message) {
            super(message);
        }
    }

    /** Looks up a host name's addresses (replaceable in tests). */
    public interface Resolver {
        InetAddress[] resolve(String host) throws UnknownHostException;
    }

    public static final Resolver SYSTEM_DNS = InetAddress::getAllByName;

    // Control characters, plus invisible ones that can disguise text (zero-width, bidi overrides).
    private static final Pattern CONTROL =
            Pattern.compile("[\\x00-\\x1f\\x7f-\\x9f\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069\\ufeff]");
    private static final Pattern HAS_SCHEME = Pattern.compile("^[a-zA-Z][a-zA-Z0-9+.-]*://.*");
    private static final Pattern IPV4 = Pattern.compile("^\\d{1,3}(\\.\\d{1,3}){3}$");
    private static final String[] LOCAL_SUFFIXES = {
            ".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa", ".corp", ".intranet"};
    private static final Pattern LINK_IN_TEXT = Pattern.compile("https?://\\S+", Pattern.CASE_INSENSITIVE);

    private LinkCheck() {
    }

    /** Returns the cleaned-up link, or throws BadLink with a friendly reason. */
    public static String check(String url, Resolver resolver) throws BadLink {
        if (url == null || url.trim().isEmpty()) {
            throw new BadLink("Paste a video link first.");
        }
        url = url.trim();
        if (url.length() > MAX_URL_LENGTH) {
            throw new BadLink("That link is too long.");
        }
        if (CONTROL.matcher(url).find() || url.chars().anyMatch(Character::isWhitespace)) {
            throw new BadLink("That link contains hidden or invalid characters.");
        }
        if (!HAS_SCHEME.matcher(url).matches()) {
            url = "https://" + url;
        }
        // Split by hand, like Python's urlsplit: java.net.URI rejects many real-world links.
        int sep = url.indexOf("://");
        String scheme = url.substring(0, sep).toLowerCase(Locale.ROOT);
        if (!scheme.equals("http") && !scheme.equals("https")) {
            throw new BadLink("Only web links (http or https) can be downloaded.");
        }
        String rest = url.substring(sep + 3);
        int end = rest.length();
        for (char c : new char[]{'/', '?', '#', '\\'}) {
            int i = rest.indexOf(c);
            if (i >= 0 && i < end) end = i;
        }
        checkHost(hostOf(rest.substring(0, end)), resolver);
        return url;
    }

    /** The link's host name in lower case (after check() accepted it), or "". */
    public static String hostOfLink(String url) {
        try {
            int sep = url.indexOf("://");
            String rest = url.substring(sep + 3);
            int end = rest.length();
            for (char c : new char[]{'/', '?', '#', '\\'}) {
                int i = rest.indexOf(c);
                if (i >= 0 && i < end) end = i;
            }
            return hostOf(rest.substring(0, end)).toLowerCase(Locale.ROOT);
        } catch (BadLink | RuntimeException e) {
            return "";
        }
    }

    /**
     * The host part of "host", "host:port" or "[v6]:port". Parsed here rather than with
     * URI.getHost(), which gives up on valid names such as ones with an underscore.
     */
    static String hostOf(String authority) throws BadLink {
        if (authority == null || authority.isEmpty()) {
            throw new BadLink("That link has no website in it.");
        }
        if (authority.contains("@")) {
            throw new BadLink("Links with a username or password in them aren't allowed.");
        }
        String host = authority;
        String port = "";
        if (host.startsWith("[")) {
            int end = host.indexOf(']');
            if (end < 0) throw new BadLink("That link isn't valid.");
            String rest = host.substring(end + 1);
            if (!rest.isEmpty()) {
                if (!rest.startsWith(":")) throw new BadLink("That link isn't valid.");
                port = rest.substring(1);
            }
            host = host.substring(0, end + 1);
        } else {
            int colon = host.lastIndexOf(':');
            if (colon >= 0) {
                port = host.substring(colon + 1);
                host = host.substring(0, colon);
            }
        }
        if (!port.matches("\\d{0,5}") || (!port.isEmpty() && Integer.parseInt(port) > 65535)) {
            throw new BadLink("That link isn't valid.");
        }
        if (host.contains("%")) {
            throw new BadLink("That link contains hidden or invalid characters.");
        }
        return host;
    }

    /** Throws BadLink unless host is a public internet address. */
    public static void checkHost(String host, Resolver resolver) throws BadLink {
        host = host == null ? "" : host.toLowerCase(Locale.ROOT);
        if (host.startsWith("[") && host.endsWith("]")) {
            host = host.substring(1, host.length() - 1);
        }
        while (host.endsWith(".")) {
            host = host.substring(0, host.length() - 1);
        }
        if (host.isEmpty()) {
            throw new BadLink("That link has no website in it.");
        }
        BadLink blocked = new BadLink("Links to this phone or your local network aren't allowed.");
        if (host.contains(":") || IPV4.matcher(host).matches()) {
            InetAddress literal;
            try {
                literal = InetAddress.getByName(host);  // a literal address: no DNS lookup
            } catch (UnknownHostException e) {
                throw new BadLink("That link isn't valid.");
            }
            if (!isPublic(literal)) {
                throw blocked;
            }
            return;
        }
        if (host.equals("localhost") || !host.contains(".")) {
            throw blocked;
        }
        for (String suffix : LOCAL_SUFFIXES) {
            if (host.endsWith(suffix)) {
                throw blocked;
            }
        }
        if (resolver == null) {
            return;
        }
        InetAddress[] addresses;
        try {
            addresses = resolver.resolve(host);
        } catch (UnknownHostException e) {
            return;  // can't resolve: the download itself will report a network error
        }
        for (InetAddress address : addresses) {
            if (!isPublic(address)) {
                throw blocked;
            }
        }
    }

    /** True for addresses on the public internet (like Python's ip.is_global, minus multicast). */
    public static boolean isPublic(InetAddress address) {
        byte[] b = address.getAddress();
        if (address instanceof Inet6Address) {
            if (isV4Mapped(b)) {
                byte[] v4 = {b[12], b[13], b[14], b[15]};
                try {
                    return isPublic(InetAddress.getByAddress(v4));
                } catch (UnknownHostException e) {
                    return false;
                }
            }
            int first = b[0] & 0xff;
            if (address.isAnyLocalAddress() || address.isLoopbackAddress() || address.isLinkLocalAddress()
                    || address.isSiteLocalAddress() || address.isMulticastAddress()) {
                return false;
            }
            if ((first & 0xfe) == 0xfc) {
                return false;  // fc00::/7 unique local
            }
            if (first == 0x20 && (b[1] & 0xff) == 0x01 && (b[2] & 0xff) == 0x0d && (b[3] & 0xff) == 0xb8) {
                return false;  // 2001:db8::/32 documentation
            }
            if (first == 0x00 || first == 0x01) {
                return false;  // ::/8 reserved, 100::/64 discard
            }
            return true;
        }
        if (address instanceof Inet4Address) {
            int a = b[0] & 0xff, c = b[1] & 0xff;
            if (a == 0 || a == 10 || a == 127 || a >= 224) return false;     // this net, private, loopback, multicast/reserved
            if (a == 100 && c >= 64 && c <= 127) return false;                 // 100.64.0.0/10 carrier-grade NAT
            if (a == 169 && c == 254) return false;                            // link-local
            if (a == 172 && c >= 16 && c <= 31) return false;                  // private
            if (a == 192 && c == 168) return false;                            // private
            if (a == 192 && c == 0 && (b[2] & 0xff) == 0) return false;        // 192.0.0.0/24 protocol assignments
            if (a == 192 && c == 0 && (b[2] & 0xff) == 2) return false;        // documentation
            if (a == 198 && (c == 18 || c == 19)) return false;                // benchmarking
            if (a == 198 && c == 51 && (b[2] & 0xff) == 100) return false;     // documentation
            if (a == 203 && c == 0 && (b[2] & 0xff) == 113) return false;      // documentation
            return true;
        }
        return false;
    }

    private static boolean isV4Mapped(byte[] b) {
        for (int i = 0; i < 10; i++) {
            if (b[i] != 0) return false;
        }
        return (b[10] & 0xff) == 0xff && (b[11] & 0xff) == 0xff;
    }

    /** The first web link in some text (e.g. "Look at this! https://…"), or null. */
    public static String findLink(String text) {
        if (text == null) return null;
        java.util.regex.Matcher m = LINK_IN_TEXT.matcher(text);
        if (!m.find()) return null;
        String link = m.group();
        // Trailing punctuation from a sentence isn't part of the link.
        while (!link.isEmpty() && ".,;:!?)]}>\"'".indexOf(link.charAt(link.length() - 1)) >= 0) {
            link = link.substring(0, link.length() - 1);
        }
        return link;
    }

    /** Sites whose media is copy-protected (DRM); the same list as the desktop app. */
    public static String drmService(String url) {
        String host = hostOfLink(url);
        if (host.isEmpty()) return null;
        String[][] sites = {
                {"(^|\\.)netflix\\.com$", "Netflix"},
                {"(^|\\.)disneyplus\\.com$|(^|\\.)disney\\.com$", "Disney+"},
                {"^music\\.apple\\.com$", "Apple Music"},
                {"^tv\\.apple\\.com$", "Apple TV+"},
                {"(^|\\.)primevideo\\.com$", "Amazon Prime Video"},
                {"^music\\.amazon\\.", "Amazon Music"},
                {"(^|\\.)hulu\\.com$", "Hulu"},
                {"(^|\\.)max\\.com$|(^|\\.)hbomax\\.com$", "Max"},
                {"(^|\\.)paramountplus\\.com$", "Paramount+"},
                {"(^|\\.)peacocktv\\.com$", "Peacock"},
                {"(^|\\.)tidal\\.com$", "Tidal"},
                {"(^|\\.)deezer\\.com$", "Deezer"},
                {"(^|\\.)crunchyroll\\.com$", "Crunchyroll"},
                {"(^|\\.)open\\.spotify\\.com$|(^|\\.)spotify\\.com$", "Spotify"},
        };
        for (String[] site : sites) {
            if (Pattern.compile(site[0]).matcher(host).find()) {
                return site[1];
            }
        }
        return null;
    }
}
