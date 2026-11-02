package io.github.ziadcp.dlr;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.provider.MediaStore;

import com.yausername.ffmpeg.FFmpeg;
import com.yausername.youtubedl_android.YoutubeDL;
import com.yausername.youtubedl_android.YoutubeDLException;
import com.yausername.youtubedl_android.YoutubeDLRequest;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Collections;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

import kotlin.Unit;

/**
 * Downloads with yt-dlp and FFmpeg (from the youtubedl-android library), into a private
 * folder first; the finished file is then copied to Downloads/Dlr and the folder is deleted.
 */
public final class Engine {
    /** Where finished files go, inside the phone's Downloads folder. */
    public static final String FOLDER = "Download/Dlr";  // Environment.DIRECTORY_DOWNLOADS + "/Dlr"

    private static final String RELEASES = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/";
    private static final long MAX_YTDLP_BYTES = 64L * 1024 * 1024;
    private static final String VIDEO_FORMAT =
            // H.264 + AAC plays on every phone; anything else is the fallback.
            "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[vcodec^=avc1][acodec^=mp4a]/bv*+ba/b";

    private static volatile boolean ready;

    private Engine() {
    }

    public interface Progress {
        void update(float percent, long etaSeconds);
    }

    /** A finished download, saved in Downloads/Dlr. */
    public static final class Saved {
        public final Uri uri;
        public final String name;
        public final String mimeType;

        Saved(Uri uri, String name, String mimeType) {
            this.uri = uri;
            this.name = name;
            this.mimeType = mimeType;
        }
    }

    /** A failure with a message that is safe to show to the user. */
    public static final class Failed extends Exception {
        public Failed(String message) {
            super(message);
        }
    }

    public static boolean isReady() {
        return ready;
    }

    /** Unpacks Python, yt-dlp and FFmpeg the first time (a few seconds), then is instant. */
    public static synchronized void init(Context context) throws Failed {
        if (ready) return;
        Context app = context.getApplicationContext();
        SharedPreferences prefs = prefs(app);
        // A new version of the app brings a newer yt-dlp than an older update may have left.
        if (prefs.getInt("ytdlpFor", -1) != BuildConfig.VERSION_CODE) {
            deleteTree(ytdlpDir(app));
            prefs.edit().putInt("ytdlpFor", BuildConfig.VERSION_CODE).apply();
        }
        try {
            YoutubeDL.getInstance().init(app);
            FFmpeg.getInstance().init(app);
        } catch (YoutubeDLException | RuntimeException e) {
            throw new Failed("Dlr couldn't start its download engine. Restart the app and try again.");
        }
        cleanTemp(app);
        ready = true;
    }

    /** The yt-dlp version in use, e.g. "2026.10.21". */
    public static String ytdlpVersion() {
        try {
            YoutubeDLRequest request = new YoutubeDLRequest(Collections.emptyList());
            request.addOption("--version");
            return YoutubeDL.getInstance().execute(request, null, null).getOut().trim();
        } catch (Exception e) {
            return "?";
        }
    }

    /** Downloads a link as a video (MP4) or MP3 and saves it in Downloads/Dlr. */
    public static Saved download(Context context, String url, boolean mp3, String jobId, Progress progress)
            throws Failed, YoutubeDL.CanceledException {
        Context app = context.getApplicationContext();
        File dir = new File(app.getCacheDir(), "job-" + jobId);
        deleteTree(dir);
        if (!dir.mkdirs()) {
            throw new Failed("Your phone is out of space, or Dlr can't write its temporary files.");
        }
        try {
            YoutubeDLRequest request = new YoutubeDLRequest(url);
            request.addOption("--ignore-config");
            request.addOption("--no-plugin-dirs");  // never run yt-dlp plugins
            request.addOption("--no-playlist");
            request.addOption("--no-mtime");
            request.addOption("--windows-filenames");
            request.addOption("--newline");
            request.addOption("-P", dir.getAbsolutePath());
            request.addOption("-o", "%(title).120B [%(id)s].%(ext)s");
            if (mp3) {
                request.addOption("-f", "ba/b");
                request.addOption("-x");
                request.addOption("--audio-format", "mp3");
                request.addOption("--audio-quality", "192K");
            } else {
                request.addOption("-f", VIDEO_FORMAT);
                request.addOption("--merge-output-format", "mp4");
            }
            try {
                YoutubeDL.getInstance().execute(request, jobId, (percent, eta, line) -> {
                    if (progress != null) progress.update(percent, eta);
                    return Unit.INSTANCE;
                });
            } catch (YoutubeDLException e) {
                throw new Failed(friendlyError(e.getMessage()));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new YoutubeDL.CanceledException();
            }
            File result = finishedFile(dir);
            if (result == null) {
                throw new Failed("The download finished, but no file came out of it. Try the other button.");
            }
            String mime = mp3 ? "audio/mpeg" : mimeFor(result.getName());
            return saveToDownloads(app, result, cleanName(result.getName()), mime);
        } finally {
            deleteTree(dir);
        }
    }

    /** Stops a running download. */
    public static void cancel(String jobId) {
        YoutubeDL.getInstance().destroyProcessById(jobId);
    }

    /** Copies a file into Downloads/Dlr. Android adds " (1)" to a name that's taken. */
    public static Saved saveToDownloads(Context context, File file, String name, String mime) throws Failed {
        ContentResolver resolver = context.getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
        values.put(MediaStore.MediaColumns.MIME_TYPE, mime);
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, FOLDER);
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);
        Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (uri == null) {
            throw new Failed("Dlr couldn't save to your Downloads folder.");
        }
        try (InputStream in = new FileInputStream(file); OutputStream out = resolver.openOutputStream(uri)) {
            if (out == null) throw new IOException("no output stream");
            byte[] buffer = new byte[1 << 16];
            int n;
            while ((n = in.read(buffer)) > 0) {
                out.write(buffer, 0, n);
            }
        } catch (IOException e) {
            resolver.delete(uri, null, null);
            throw new Failed("Dlr couldn't save to your Downloads folder. Is your phone full?");
        }
        values.clear();
        values.put(MediaStore.MediaColumns.IS_PENDING, 0);
        resolver.update(uri, values, null, null);
        return new Saved(uri, name, mime);
    }

    // ---- yt-dlp updates: only official releases, checked against the official checksums ----

    /** Installs the newest yt-dlp if there is one. Returns a message for the user. */
    public static synchronized String update(Context context) throws Failed {
        Context app = context.getApplicationContext();
        File current = new File(ytdlpDir(app), "yt-dlp");
        String expected;
        try {
            expected = checksumFor("yt-dlp", new String(fetch(RELEASES + "SHA2-256SUMS", 64 * 1024),
                    StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new Failed("Couldn't check for updates. Check your internet connection.");
        }
        if (expected == null) {
            throw new Failed("Couldn't check for updates right now. Try again later.");
        }
        if (current.isFile() && expected.equals(sha256(current))) {
            return "Up to date (yt-dlp " + ytdlpVersion() + ")";
        }
        byte[] data;
        try {
            data = fetch(RELEASES + "yt-dlp", MAX_YTDLP_BYTES);
        } catch (IOException e) {
            throw new Failed("Couldn't download the update. Check your internet connection.");
        }
        if (!expected.equals(sha256(data))) {
            throw new Failed("The update didn't match yt-dlp's official checksum, so it wasn't installed.");
        }
        File tmp = new File(current.getParentFile(), "yt-dlp.new");
        try {
            if (!current.getParentFile().isDirectory() && !current.getParentFile().mkdirs()) {
                throw new IOException("no folder");
            }
            try (OutputStream out = new FileOutputStream(tmp)) {
                out.write(data);
            }
            String version = zipVersion(tmp);
            if (version == null) {
                throw new IOException("not a yt-dlp release");
            }
            if (!tmp.renameTo(current)) {
                throw new IOException("couldn't replace");
            }
            prefs(app).edit().putLong("lastUpdateCheck", System.currentTimeMillis()).apply();
            return "Updated to yt-dlp " + version;
        } catch (IOException e) {
            throw new Failed("The update couldn't be installed. Dlr keeps using the current version.");
        } finally {
            //noinspection ResultOfMethodCallIgnored
            tmp.delete();
        }
    }

    /** True if the daily update check is due (checked at most once a day). */
    public static boolean updateCheckDue(Context context) {
        long last = prefs(context).getLong("lastUpdateCheck", 0);
        return System.currentTimeMillis() - last > 24L * 60 * 60 * 1000;
    }

    public static void markUpdateChecked(Context context) {
        prefs(context).edit().putLong("lastUpdateCheck", System.currentTimeMillis()).apply();
    }

    /** "<sha256>  yt-dlp" line from SHA2-256SUMS. */
    static String checksumFor(String name, String sums) {
        for (String line : sums.split("\n")) {
            String[] parts = line.trim().split("\\s+");
            if (parts.length == 2 && parts[1].equals(name) && parts[0].matches("[0-9a-fA-F]{64}")) {
                return parts[0].toLowerCase(Locale.ROOT);
            }
        }
        return null;
    }

    /** Fetches a GitHub release file over HTTPS, following redirects only to GitHub's servers. */
    private static byte[] fetch(String address, long limit) throws IOException {
        URL url = new URL(address);
        for (int hops = 0; hops < 5; hops++) {
            if (!allowedHost(url)) {
                throw new IOException("unexpected host " + url.getHost());
            }
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(30000);
            connection.setRequestProperty("User-Agent", "Dlr-Android");
            int code = connection.getResponseCode();
            if (code >= 300 && code < 400) {
                String location = connection.getHeaderField("Location");
                connection.disconnect();
                if (location == null) throw new IOException("redirect without location");
                url = new URL(url, location);
                continue;
            }
            if (code != 200) {
                connection.disconnect();
                throw new IOException("HTTP " + code);
            }
            try (InputStream in = connection.getInputStream()) {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                byte[] buffer = new byte[1 << 16];
                long total = 0;
                int n;
                while ((n = in.read(buffer)) > 0) {
                    total += n;
                    if (total > limit) throw new IOException("too large");
                    out.write(buffer, 0, n);
                }
                return out.toByteArray();
            } finally {
                connection.disconnect();
            }
        }
        throw new IOException("too many redirects");
    }

    static boolean allowedHost(URL url) {
        String host = url.getHost().toLowerCase(Locale.ROOT);
        return url.getProtocol().equals("https")
                && (host.equals("github.com") || host.endsWith(".githubusercontent.com"));
    }

    /** The version written inside a yt-dlp release (a zip with yt_dlp/version.py), or null. */
    static String zipVersion(File file) {
        try (ZipFile zip = new ZipFile(file)) {
            ZipEntry entry = zip.getEntry("yt_dlp/version.py");
            if (entry == null || entry.getSize() > 64 * 1024) return null;
            try (InputStream in = zip.getInputStream(entry)) {
                String text = new String(readAll(in, 64 * 1024), StandardCharsets.UTF_8);
                Matcher m = Pattern.compile("__version__\\s*=\\s*['\"]([0-9.]+)['\"]").matcher(text);
                return m.find() ? m.group(1) : null;
            }
        } catch (IOException e) {
            return null;
        }
    }

    // ---- helpers ----

    private static final String[][] ERRORS = {
            {"\\bdrm\\b|copy[- ]protect", "This video is copy-protected, so it can't be downloaded."},
            {"private video|video is private|this account is private",
                    "This video is private. Only the owner or approved accounts can watch it."},
            {"not a bot", "YouTube wants to confirm you're not a bot. Wait a bit and try again, or tap Update below."},
            {"age[- ]restricted|confirm your age|inappropriate for some users",
                    "This video is age-restricted and can only be downloaded with a logged-in account."},
            {"login required|log in|sign in|logged[- ]in|requires authentication|use --cookies|rate-limit reached",
                    "This site requires you to be logged in to access this video."},
            {"unsupported url|no video could be found|is not a valid url",
                    "This site or link isn't supported. Make sure it's a link to a single video."},
            {"requested format is not available",
                    "No version of this video can be saved this way. Try the other button, or another link."},
            {"video unavailable|is unavailable|not available|has been removed|does not exist|http error 404|this post is unavailable",
                    "This video is unavailable. It may have been deleted or blocked in your region."},
            {"unable to download webpage|getaddrinfo|timed out|connection|network is unreachable|name resolution|no address associated",
                    "Network error. Check your internet connection and try again."},
            {"no space left", "Your phone is out of space."},
    };

    /** Turns yt-dlp's error output into a plain message (same table as the desktop app). */
    public static String friendlyError(String error) {
        String text = error == null ? "" : error.replaceAll("\u001b\\[[0-9;]*m", "");
        String last = "";
        for (String line : text.split("\n")) {
            if (line.startsWith("ERROR:")) last = line.substring(6).trim();
        }
        String low = (last.isEmpty() ? text : last).toLowerCase(Locale.ROOT);
        for (String[] rule : ERRORS) {
            if (Pattern.compile(rule[0]).matcher(low).find()) {
                return rule[1];
            }
        }
        return "This link couldn't be downloaded. Check it plays in your browser, then try again, "
                + "or tap Update below (sites change often).";
    }

    private static File finishedFile(File dir) {
        File best = null;
        File[] files = dir.listFiles();
        if (files == null) return null;
        for (File f : files) {
            String n = f.getName().toLowerCase(Locale.ROOT);
            if (!f.isFile() || n.endsWith(".part") || n.endsWith(".ytdl") || n.contains(".temp.")
                    || n.endsWith(".jpg") || n.endsWith(".webp") || n.endsWith(".png")) {
                continue;
            }
            if (best == null || f.length() > best.length()) best = f;
        }
        return best != null && best.length() > 0 ? best : null;
    }

    static String mimeFor(String name) {
        String n = name.toLowerCase(Locale.ROOT);
        if (n.endsWith(".mp4") || n.endsWith(".m4v")) return "video/mp4";
        if (n.endsWith(".webm")) return "video/webm";
        if (n.endsWith(".mkv")) return "video/x-matroska";
        if (n.endsWith(".mov")) return "video/quicktime";
        if (n.endsWith(".mp3")) return "audio/mpeg";
        if (n.endsWith(".m4a")) return "audio/mp4";
        return "application/octet-stream";
    }

    /** A safe display name: no folders, hidden-file dots or invisible characters. */
    static String cleanName(String name) {
        String clean = name.replaceAll("[\\x00-\\x1f\\x7f/\\\\\\u200b\\u200c\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069\\ufeff]", "")
                .replaceAll("^[.\\s]+", "").trim();
        return clean.isEmpty() ? "download" : clean;
    }

    static String sha256(byte[] data) {
        return hex(digest().digest(data));
    }

    static String sha256(File file) {
        MessageDigest md = digest();
        try (InputStream in = new FileInputStream(file)) {
            byte[] buffer = new byte[1 << 16];
            int n;
            while ((n = in.read(buffer)) > 0) md.update(buffer, 0, n);
        } catch (IOException e) {
            return "";
        }
        return hex(md.digest());
    }

    private static MessageDigest digest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) sb.append(String.format(Locale.ROOT, "%02x", b));
        return sb.toString();
    }

    private static byte[] readAll(InputStream in, int limit) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int n;
        while ((n = in.read(buffer)) > 0) {
            if (out.size() + n > limit) throw new IOException("too large");
            out.write(buffer, 0, n);
        }
        return out.toByteArray();
    }

    private static File ytdlpDir(Context app) {
        return new File(new File(app.getNoBackupFilesDir(), YoutubeDL.baseName), YoutubeDL.ytdlpDirName);
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences("dlr", Context.MODE_PRIVATE);
    }

    /** Removes temporary folders left by a download that was interrupted (e.g. the app was closed). */
    private static void cleanTemp(Context app) {
        File[] leftovers = app.getCacheDir().listFiles((d, n) -> n.startsWith("job-"));
        if (leftovers != null) {
            for (File f : leftovers) deleteTree(f);
        }
    }

    /** Deletes a file or folder, without following symlinks out of it. */
    static void deleteTree(File file) {
        if (file == null) return;
        try {
            if (java.nio.file.Files.isSymbolicLink(file.toPath())) {
                //noinspection ResultOfMethodCallIgnored
                file.delete();
                return;
            }
        } catch (RuntimeException ignored) {
            // fall through
        }
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) deleteTree(child);
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
    }
}
