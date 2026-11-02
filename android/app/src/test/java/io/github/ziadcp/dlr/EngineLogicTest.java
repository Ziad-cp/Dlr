package io.github.ziadcp.dlr;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.net.URL;

import org.junit.Test;

/** The parts of the engine that don't need a phone. */
public class EngineLogicTest {
    @Test
    public void friendlyErrors() {
        assertEquals("This video is private. Only the owner or approved accounts can watch it.",
                Engine.friendlyError("[youtube] abc: some line\nERROR: [youtube] abc: Private video. Sign in"));
        assertTrue(Engine.friendlyError("ERROR: [youtube] x: Sign in to confirm you’re not a bot.")
                .contains("not a bot"));
        assertTrue(Engine.friendlyError("ERROR: Unsupported URL: https://example.com/").contains("isn't supported"));
        assertTrue(Engine.friendlyError("ERROR: Unable to download webpage: <urlopen error timed out>")
                .startsWith("Network error"));
        assertTrue(Engine.friendlyError("\u001b[0;31mERROR:\u001b[0m This video is DRM protected").contains("copy-protected"));
        assertTrue(Engine.friendlyError("something odd").contains("couldn't be downloaded"));
        assertTrue(Engine.friendlyError(null).contains("couldn't be downloaded"));
    }

    @Test
    public void checksumLine() {
        String sums = "aaaa  yt-dlp.exe\n"
                + "0123456789abcdef0123456789abcdef0123456789abcdef0123456789ABCDEF  yt-dlp\n"
                + "1111111111111111111111111111111111111111111111111111111111111111  yt-dlp_macos\n";
        assertEquals("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                Engine.checksumFor("yt-dlp", sums));
        assertNull(Engine.checksumFor("yt-dlp", "nothing here"));
        assertNull(Engine.checksumFor("yt-dlp", "xyz  yt-dlp"));
    }

    @Test
    public void updatesOnlyFromGitHub() throws Exception {
        assertTrue(Engine.allowedHost(new URL("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp")));
        assertTrue(Engine.allowedHost(new URL("https://release-assets.githubusercontent.com/x")));
        assertFalse(Engine.allowedHost(new URL("http://github.com/x")));
        assertFalse(Engine.allowedHost(new URL("https://github.com.evil.com/x")));
        assertFalse(Engine.allowedHost(new URL("https://evilgithubusercontent.com/x")));
    }

    @Test
    public void namesAndTypes() {
        assertEquals("video [abc].mp4", Engine.cleanName("..video [abc].mp4"));
        assertEquals("ab.mp3", Engine.cleanName("a/b‮.mp3"));
        assertEquals("download", Engine.cleanName("..."));
        assertEquals("video/mp4", Engine.mimeFor("x.MP4"));
        assertEquals("audio/mpeg", Engine.mimeFor("x.mp3"));
        assertEquals("video/webm", Engine.mimeFor("x.webm"));
    }

    @Test
    public void sha256() {
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", Engine.sha256(new byte[0]));
    }
}
