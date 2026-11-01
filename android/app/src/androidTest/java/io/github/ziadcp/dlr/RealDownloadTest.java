package io.github.ziadcp.dlr;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.content.Context;
import android.database.Cursor;
import android.provider.MediaStore;
import android.util.Log;

import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

import java.util.UUID;

/**
 * Downloads real videos over the internet. Sites sometimes block GitHub's computers, so the
 * workflow reports a failure here without stopping the build.
 */
@RunWith(AndroidJUnit4.class)
public class RealDownloadTest {
    private static final String TAG = "DlrTest";
    // Public test videos from sites that don't block GitHub's computers (YouTube does).
    private static final String[] LINKS = {
            "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4",
            "https://download.blender.org/peach/trailer/trailer_480p.mov",
    };
    private final Context context = ApplicationProvider.getApplicationContext();

    @Test
    public void updatesYtDlpFromGitHub() throws Exception {
        Engine.init(context);
        String message = Engine.update(context);
        Log.i(TAG, "update: " + message);
        assertTrue(message, message.startsWith("Up to date") || message.startsWith("Updated"));
    }

    @Test
    public void downloadsVideoAndMp3() throws Exception {
        Engine.init(context);
        StringBuilder errors = new StringBuilder();
        for (String link : LINKS) {
            try {
                check(Engine.download(context, link, false, UUID.randomUUID().toString(), null), "video/");
                check(Engine.download(context, link, true, UUID.randomUUID().toString(), null), "audio/mpeg");
                Log.i(TAG, "downloaded " + link);
                return;
            } catch (Engine.Failed e) {
                Log.w(TAG, link + ": " + e.getMessage());
                errors.append(link).append(": ").append(e.getMessage()).append('\n');
            }
        }
        fail("No test link could be downloaded:\n" + errors);
    }

    @Test
    public void youTubeErrorsArePlainMessages() throws Exception {
        Engine.init(context);
        try {
            check(Engine.download(context, "https://www.youtube.com/watch?v=jNQXAC9IVRw", false,
                    UUID.randomUUID().toString(), null), "video/");
            Log.i(TAG, "YouTube download worked");
        } catch (Engine.Failed e) {
            Log.i(TAG, "YouTube: " + e.getMessage());  // usually "not a bot" on GitHub's computers
            assertTrue(e.getMessage(), !e.getMessage().contains("Traceback"));
        }
    }

    private void check(Engine.Saved saved, String mime) {
        try (Cursor c = context.getContentResolver().query(saved.uri,
                new String[]{MediaStore.MediaColumns.SIZE, MediaStore.MediaColumns.MIME_TYPE}, null, null, null)) {
            assertTrue(c != null && c.moveToFirst());
            Log.i(TAG, "saved " + saved.name + " (" + c.getLong(0) + " bytes)");
            assertTrue("file has content", c.getLong(0) > 10_000);
            assertTrue(c.getString(1), c.getString(1).startsWith(mime));
        } finally {
            context.getContentResolver().delete(saved.uri, null, null);
        }
    }
}
