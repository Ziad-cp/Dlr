package io.github.ziadcp.dlr;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.fail;

import java.net.InetAddress;

import org.junit.Test;

/** The same cases the desktop app's link rules handle (safety.py). */
public class LinkCheckTest {
    /** Pretends every name resolves to the given address. */
    private static LinkCheck.Resolver dns(String address) {
        return host -> new InetAddress[]{InetAddress.getByName(address)};
    }

    private static final LinkCheck.Resolver PUBLIC = dns("142.250.74.110");

    private static void rejected(String url, LinkCheck.Resolver resolver, String why) {
        try {
            LinkCheck.check(url, resolver);
            fail("accepted " + url);
        } catch (LinkCheck.BadLink e) {
            if (!e.getMessage().contains(why)) {
                fail(url + ": unexpected message " + e.getMessage());
            }
        }
    }

    @Test
    public void acceptsNormalLinks() throws Exception {
        assertEquals("https://www.youtube.com/watch?v=jNQXAC9IVRw",
                LinkCheck.check("  https://www.youtube.com/watch?v=jNQXAC9IVRw ", PUBLIC));
        assertEquals("https://youtu.be/abc", LinkCheck.check("youtu.be/abc", PUBLIC));
        assertEquals("http://vimeo.com:8080/1", LinkCheck.check("http://vimeo.com:8080/1", PUBLIC));
        assertEquals("https://some_blog.tumblr.com/post/1?a=b|c",
                LinkCheck.check("https://some_blog.tumblr.com/post/1?a=b|c", PUBLIC));
        LinkCheck.check("https://[2a00:1450:4001:82b::200e]/x", null);
        LinkCheck.check("https://8.8.8.8/x", null);
    }

    @Test
    public void rejectsEmptyLongAndHidden() {
        rejected("", PUBLIC, "Paste a video link");
        rejected("   ", PUBLIC, "Paste a video link");
        rejected("https://a.com/" + "x".repeat(2100), PUBLIC, "too long");
        rejected("https://you​tube.com/x", PUBLIC, "hidden");
        rejected("https://youtube.com/‮x", PUBLIC, "hidden");
        rejected("https://youtube.com/a b", PUBLIC, "hidden");
        rejected("https://youtube.com/\nx", PUBLIC, "hidden");
    }

    @Test
    public void rejectsOtherSchemesAndLogins() {
        rejected("file:///etc/passwd", PUBLIC, "Only web links");
        rejected("ftp://example.com/x", PUBLIC, "Only web links");
        rejected("javascript://alert(1)", PUBLIC, "Only web links");
        rejected("https://user:pass@example.com/", PUBLIC, "username or password");
        rejected("https://user@example.com/", PUBLIC, "username or password");
        rejected("https://example.com:99999/", PUBLIC, "isn't valid");
        rejected("https://example.com:abc/", PUBLIC, "isn't valid");
        rejected("https:///path", PUBLIC, "no website");
    }

    @Test
    public void rejectsThisPhoneAndLocalNetwork() {
        String local = "local network";
        rejected("http://localhost/", PUBLIC, local);
        rejected("http://LOCALHOST./", PUBLIC, local);
        rejected("http://printer.local/", PUBLIC, local);
        rejected("http://router.home.arpa/", PUBLIC, local);
        rejected("http://intranet/", PUBLIC, local);
        rejected("http://127.0.0.1/", PUBLIC, local);
        rejected("http://10.1.2.3/", PUBLIC, local);
        rejected("http://172.16.0.1/", PUBLIC, local);
        rejected("http://192.168.1.1/", PUBLIC, local);
        rejected("http://169.254.169.254/latest/meta-data", PUBLIC, local);
        rejected("http://100.64.0.1/", PUBLIC, local);
        rejected("http://0.0.0.0/", PUBLIC, local);
        rejected("http://[::1]/", PUBLIC, local);
        rejected("http://[fd00::1]/", PUBLIC, local);
        rejected("http://[fe80::1]/", PUBLIC, local);
        rejected("http://[::ffff:192.168.1.1]/", PUBLIC, local);
        rejected("http://%6c%6f%63%61%6c%68%6f%73%74/", PUBLIC, "hidden");
        // A public-looking name that resolves to the local network.
        rejected("https://evil.example.com/", dns("192.168.0.10"), local);
        rejected("https://evil.example.com/", dns("127.0.0.1"), local);
    }

    @Test
    public void findsLinksInSharedText() {
        assertEquals("https://youtu.be/abc",
                LinkCheck.findLink("Watch this! https://youtu.be/abc."));
        assertEquals("https://www.tiktok.com/@a/video/1?x=1",
                LinkCheck.findLink("https://www.tiktok.com/@a/video/1?x=1"));
        assertNull(LinkCheck.findLink("no link here"));
        assertNull(LinkCheck.findLink(null));
    }

    @Test
    public void knowsCopyProtectedServices() {
        assertEquals("Netflix", LinkCheck.drmService("https://www.netflix.com/watch/1"));
        assertEquals("Spotify", LinkCheck.drmService("https://open.spotify.com/track/1"));
        assertNull(LinkCheck.drmService("https://www.youtube.com/watch?v=1"));
    }
}
