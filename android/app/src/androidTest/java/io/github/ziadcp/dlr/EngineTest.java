package io.github.ziadcp.dlr;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import android.database.Cursor;
import android.provider.MediaStore;

import androidx.test.core.app.ActivityScenario;
import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.File;
import java.io.FileOutputStream;
import java.util.UUID;

/** Runs on a phone or emulator, without needing any website. */
@RunWith(AndroidJUnit4.class)
public class EngineTest {
    private final Context context = ApplicationProvider.getApplicationContext();

    @Test
    public void engineStartsAndHasYtDlp() throws Exception {
        Engine.init(context);
        assertTrue(Engine.isReady());
        String version = Engine.ytdlpVersion();
        assertTrue("yt-dlp version: " + version, version.matches("\\d{4}\\.\\d{2}\\.\\d{2}(\\.\\d+)?"));
    }

    @Test
    public void savesIntoDownloads() throws Exception {
        File tmp = new File(context.getCacheDir(), "dlr-test.txt");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write("hello".getBytes());
        }
        String name = "dlr-test-" + UUID.randomUUID() + ".txt";
        Engine.Saved saved = Engine.saveToDownloads(context, tmp, name, "text/plain");
        try (Cursor c = context.getContentResolver().query(saved.uri,
                new String[]{MediaStore.MediaColumns.SIZE, MediaStore.MediaColumns.RELATIVE_PATH}, null, null, null)) {
            assertTrue(c != null && c.moveToFirst());
            assertEquals(5, c.getLong(0));
            assertEquals(Engine.FOLDER + "/", c.getString(1));
        } finally {
            context.getContentResolver().delete(saved.uri, null, null);
            //noinspection ResultOfMethodCallIgnored
            tmp.delete();
        }
    }

    @Test
    public void screenOpensAndGetsReady() throws Exception {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            long deadline = System.currentTimeMillis() + 120_000;
            while (!Engine.isReady() && System.currentTimeMillis() < deadline) {
                Thread.sleep(500);
            }
            assertTrue(Engine.isReady());
            Thread.sleep(2000);
            final boolean[] enabled = new boolean[1];
            scenario.onActivity(a -> enabled[0] = a.findViewById(R.id.video).isEnabled());
            assertTrue("Download Video button is enabled", enabled[0]);
        }
    }
}
