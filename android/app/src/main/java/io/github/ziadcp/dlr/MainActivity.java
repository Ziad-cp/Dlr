package io.github.ziadcp.dlr;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Insets;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;

import com.yausername.youtubedl_android.YoutubeDL;

import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** The only screen: paste or share a link, then Download Video or MP3. */
public class MainActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();

    private EditText link;
    private Button video, mp3, open, cancel, update;
    private ProgressBar progress;
    private TextView status, version;

    private volatile String runningJob;
    private volatile boolean stopRequested;
    private Engine.Saved lastSaved;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        link = findViewById(R.id.link);
        video = findViewById(R.id.video);
        mp3 = findViewById(R.id.mp3);
        open = findViewById(R.id.open);
        cancel = findViewById(R.id.cancel);
        update = findViewById(R.id.update);
        progress = findViewById(R.id.progress);
        status = findViewById(R.id.status);
        version = findViewById(R.id.version);
        fitSystemBars(findViewById(R.id.root));

        findViewById(R.id.paste).setOnClickListener(v -> pasteFromClipboard(true));
        video.setOnClickListener(v -> start(false));
        mp3.setOnClickListener(v -> start(true));
        cancel.setOnClickListener(v -> stop());
        open.setOnClickListener(v -> openSaved());
        update.setOnClickListener(v -> runUpdate(false));

        readSharedLink(getIntent());
        startEngine();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        readSharedLink(intent);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        // Like the desktop app: a link copied elsewhere is filled in when you come back.
        if (hasFocus && runningJob == null && link.getText().toString().trim().isEmpty()) {
            pasteFromClipboard(false);
        }
    }

    @Override
    protected void onDestroy() {
        String job = runningJob;
        if (job != null && isFinishing()) {
            Engine.cancel(job);
        }
        worker.shutdown();
        super.onDestroy();
    }

    // ---- the engine ----

    private void startEngine() {
        setBusy(true);
        if (!Engine.isReady()) {
            status.setText("Getting ready… (only slow the first time)");
        }
        worker.execute(() -> {
            try {
                Engine.init(this);
                String ytdlp = Engine.ytdlpVersion();
                runOnUiThread(() -> {
                    showVersion(ytdlp);
                    if (status.getText().toString().startsWith("Getting ready")) status.setText("");
                    setBusy(false);
                });
                if (Engine.updateCheckDue(this)) {
                    runUpdate(true);
                }
            } catch (Engine.Failed e) {
                runOnUiThread(() -> showError(e.getMessage()));
            }
        });
    }

    private void showVersion(String ytdlp) {
        version.setText(String.format(Locale.ROOT, "Dlr %s · yt-dlp %s", BuildConfig.VERSION_NAME, ytdlp));
    }

    /** Updates yt-dlp. Quietly at most once a day, or when the Update button is tapped. */
    private void runUpdate(boolean quiet) {
        if (!quiet) {
            update.setEnabled(false);
            status.setText("Checking for updates…");
            status.setTextColor(getColor(R.color.text));
        }
        worker.execute(() -> {
            String message;
            boolean ok = true;
            try {
                message = Engine.update(this);
                Engine.markUpdateChecked(this);
            } catch (Engine.Failed e) {
                message = e.getMessage();
                ok = false;
            }
            String ytdlp = Engine.ytdlpVersion();
            String finalMessage = message;
            boolean finalOk = ok;
            runOnUiThread(() -> {
                showVersion(ytdlp);
                update.setEnabled(runningJob == null);
                if (!quiet) {
                    status.setText(finalMessage);
                    status.setTextColor(getColor(finalOk ? R.color.ok : R.color.danger));
                }
            });
        });
    }

    // ---- downloading ----

    private void start(boolean asMp3) {
        if (runningJob != null || !Engine.isReady()) return;
        String raw = link.getText().toString();
        String found = LinkCheck.findLink(raw);
        String url = found != null ? found : raw;
        hideKeyboard();
        String jobId = UUID.randomUUID().toString();
        runningJob = jobId;
        stopRequested = false;
        lastSaved = null;
        setBusy(true);
        open.setVisibility(View.GONE);
        cancel.setVisibility(View.VISIBLE);
        progress.setVisibility(View.VISIBLE);
        progress.setIndeterminate(true);
        status.setTextColor(getColor(R.color.text));
        status.setText("Looking up the link…");
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        worker.execute(() -> {
            String error = null;
            Engine.Saved saved = null;
            boolean cancelled = false;
            try {
                String checked = LinkCheck.check(url, LinkCheck.SYSTEM_DNS);
                String drm = LinkCheck.drmService(checked);
                if ("Spotify".equals(drm)) {
                    throw new Engine.Failed("Spotify songs work in the computer version of Dlr. "
                            + "On your phone, share the song's YouTube link instead.");
                } else if (drm != null) {
                    throw new Engine.Failed(drm + " is copy-protected, so its videos can't be downloaded.");
                }
                if (stopRequested) throw new YoutubeDL.CanceledException();
                runOnUiThread(() -> status.setText("Downloading…"));
                saved = Engine.download(this, checked, asMp3, jobId, this::showProgress);
            } catch (LinkCheck.BadLink | Engine.Failed e) {
                error = e.getMessage();
            } catch (YoutubeDL.CanceledException e) {
                cancelled = true;
            } catch (RuntimeException e) {
                error = "Something went wrong. Try again, or tap Update below.";
            }
            String finalError = error;
            Engine.Saved finalSaved = saved;
            boolean finalCancelled = cancelled;
            runOnUiThread(() -> done(finalSaved, finalError, finalCancelled));
        });
    }

    private void showProgress(float percent, long eta) {
        runOnUiThread(() -> {
            if (runningJob == null) return;
            if (percent > 0) {
                progress.setIndeterminate(false);
                progress.setProgress(Math.round(percent * 10));
            }
            if (percent >= 99) {
                status.setText("Finishing…");
            } else if (percent > 0) {
                String left = eta > 0 ? String.format(Locale.ROOT, " · %d:%02d left", eta / 60, eta % 60) : "";
                status.setText(String.format(Locale.ROOT, "Downloading… %.0f%%%s", percent, left));
            }
        });
    }

    private void done(Engine.Saved saved, String error, boolean cancelled) {
        runningJob = null;
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        progress.setVisibility(View.GONE);
        cancel.setVisibility(View.GONE);
        setBusy(false);
        if (saved != null) {
            lastSaved = saved;
            status.setTextColor(getColor(R.color.ok));
            status.setText("Saved in Downloads › Dlr:\n" + saved.name);
            open.setVisibility(View.VISIBLE);
        } else if (cancelled) {
            status.setTextColor(getColor(R.color.muted));
            status.setText("Stopped. Nothing was saved.");
        } else {
            showError(error);
        }
    }

    private void stop() {
        String job = runningJob;
        if (job == null) return;
        stopRequested = true;
        cancel.setEnabled(false);
        status.setText("Stopping…");
        new Thread(() -> {
            Engine.cancel(job);
            runOnUiThread(() -> cancel.setEnabled(true));
        }).start();
    }

    private void openSaved() {
        if (lastSaved == null) return;
        Intent view = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(lastSaved.uri, lastSaved.mimeType)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(view);
        } catch (ActivityNotFoundException e) {
            showError("No app on this phone can open this file. Find it in Files › Downloads › Dlr.");
        }
    }

    // ---- helpers ----

    private void setBusy(boolean busy) {
        boolean enabled = !busy && Engine.isReady();
        video.setEnabled(enabled);
        mp3.setEnabled(enabled);
        update.setEnabled(enabled);
        video.setAlpha(enabled ? 1f : 0.5f);
        mp3.setAlpha(enabled ? 1f : 0.5f);
    }

    private void showError(String message) {
        status.setTextColor(getColor(R.color.danger));
        status.setText(message);
    }

    private void readSharedLink(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return;
        String text = intent.getStringExtra(Intent.EXTRA_TEXT);
        String found = LinkCheck.findLink(text);
        if (found != null && runningJob == null) {
            link.setText(found);
            link.setSelection(found.length());
            status.setTextColor(getColor(R.color.muted));
            status.setText("Link received. Choose Download Video or MP3.");
        }
    }

    private void pasteFromClipboard(boolean userAsked) {
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        String found = null;
        if (clipboard != null && clipboard.hasPrimaryClip()) {
            ClipData clip = clipboard.getPrimaryClip();
            if (clip != null && clip.getItemCount() > 0) {
                CharSequence text = clip.getItemAt(0).coerceToText(this);
                found = LinkCheck.findLink(text == null ? null : text.toString());
            }
        }
        if (found != null) {
            link.setText(found);
            link.setSelection(found.length());
        } else if (userAsked) {
            status.setTextColor(getColor(R.color.muted));
            status.setText("There's no link to paste. Copy a video's link first.");
        }
    }

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(link.getWindowToken(), 0);
        link.clearFocus();
    }

    /** Keeps the content clear of the status bar, navigation bar and keyboard (Android 15 draws edge to edge). */
    private static void fitSystemBars(View root) {
        int left = root.getPaddingLeft(), top = root.getPaddingTop();
        int right = root.getPaddingRight(), bottom = root.getPaddingBottom();
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int l, t, r, b;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime()
                        | WindowInsets.Type.displayCutout());
                l = bars.left;
                t = bars.top;
                r = bars.right;
                b = bars.bottom;
            } else {
                l = insets.getSystemWindowInsetLeft();
                t = insets.getSystemWindowInsetTop();
                r = insets.getSystemWindowInsetRight();
                b = insets.getSystemWindowInsetBottom();
            }
            v.setPadding(left + l, top + t, right + r, bottom + b);
            return insets;
        });
    }
}
