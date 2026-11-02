"use strict";
// The app's UI. It runs inside pywebview and talks to app.py through window.pywebview.api.

const $ = (id) => document.getElementById(id);
const ACTIVE = ["queued", "downloading", "processing"];
const MODES = ["best", "mp3"];

// ---------- platforms & icons ----------

const PLATFORMS = {
  youtube: { name: "YouTube", hosts: ["youtube.com", "youtu.be", "youtube-nocookie.com"] },
  tiktok: { name: "TikTok", hosts: ["tiktok.com"] },
  instagram: { name: "Instagram", hosts: ["instagram.com"] },
  reddit: { name: "Reddit", hosts: ["reddit.com", "redd.it"] },
  facebook: { name: "Facebook", hosts: ["facebook.com", "fb.watch", "fb.com"] },
  x: { name: "X", hosts: ["x.com", "twitter.com"] },
  spotify: { name: "Spotify", hosts: ["spotify.com", "spotify.link"] },
};

const GLYPHS = {
  youtube: '<path d="M10 8.3v7.4l6-3.7z" fill="#fff"/>',
  tiktok: '<path d="M13.3 5.5h2.3a3.3 3.3 0 0 0 2.9 2.9v2.3a5.6 5.6 0 0 1-2.9-.9v4.4a3.9 3.9 0 1 1-3.9-3.9h.3v2.3h-.3a1.6 1.6 0 1 0 1.6 1.6z" fill="#fff"/>',
  instagram: '<rect x="6.2" y="6.2" width="11.6" height="11.6" rx="3.6" fill="none" stroke="#fff" stroke-width="1.7"/><circle cx="12" cy="12" r="2.8" fill="none" stroke="#fff" stroke-width="1.7"/><circle cx="15.4" cy="8.6" r="0.95" fill="#fff"/>',
  reddit: '<ellipse cx="12" cy="13.6" rx="5.6" ry="3.9" fill="#fff"/><circle cx="16.4" cy="7.4" r="1.2" fill="#fff"/><path d="M12 9.7l.9-3.4 3.4.9" fill="none" stroke="#fff" stroke-width="1.1" stroke-linecap="round"/><circle cx="9.9" cy="13.2" r="0.95" fill="#ff4500"/><circle cx="14.1" cy="13.2" r="0.95" fill="#ff4500"/>',
  facebook: '<path d="M13.2 19v-5.6h1.9l.3-2.3h-2.2V9.7c0-.6.2-1.1 1.1-1.1h1.2v-2a14 14 0 0 0-1.8-.1c-1.7 0-2.9 1-2.9 3v1.6H8.9v2.3h1.9V19z" fill="#fff"/>',
  x: '<path d="M7.2 6.8h2.9l7 10.4h-2.9zM16.8 6.8 7.2 17.2" fill="#fff" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/>',
  spotify: '<path d="M7.2 9.6c3.2-1 7-.7 9.7.9M7.7 12.4c2.7-.8 5.8-.5 8 .8M8.2 15c2.2-.6 4.4-.4 6.2.6" fill="none" stroke="#000" stroke-width="1.5" stroke-linecap="round"/>',
  other: '<path d="M10.6 13.4a3 3 0 0 0 4.2 0l2.2-2.2a3 3 0 0 0-4.2-4.2l-.8.8M13.4 10.6a3 3 0 0 0-4.2 0L7 12.8a3 3 0 0 0 4.2 4.2l.8-.8" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>',
};

const LINK_ICON = '<svg class="link" viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/></svg>';
const CHECK = '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.2 4.2L19 7"/></svg>';

function siteIcon(platform) {
  const key = GLYPHS[platform] ? platform : "other";
  return `<svg class="glyph g-${key}" viewBox="0 0 24 24" aria-hidden="true"><rect class="bg" x="0.5" y="0.5" width="23" height="23" rx="7"/>${GLYPHS[key]}</svg>`;
}

function platformOf(url) {
  try {
    const host = new URL(url).hostname.replace(/^(www|m|mobile|vm|vt)\./, "");
    for (const [key, p] of Object.entries(PLATFORMS)) {
      if (p.hosts.some((h) => host === h || host.endsWith("." + h))) return key;
    }
    return "other";
  } catch {
    return "";
  }
}

// Finds a link in pasted text (share sheets often add words around it).
function findUrl(text) {
  const full = text.match(/https?:\/\/[^\s<>"']+/i);
  if (full) return full[0];
  const bare = text.match(/\b(?:[\w-]+\.)+[a-z]{2,}\/[^\s<>"']*/i);
  return bare ? "https://" + bare[0] : "";
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// ---------- backends ----------

const desktop = {
  kind: "desktop",
  call(name, ...args) {
    return window.pywebview.api[name](...args).catch((e) => ({ error: String(e?.message || e) }));
  },
  info: () => desktop.call("info"),
  fetch: (url) => desktop.call("fetch", url),
  add: (url, mode, title, label) => desktop.call("add", url, mode, title, label),
  jobs: () => desktop.call("jobs"),
  open: (item) => desktop.call("reveal", item.filepath),
  cancel: (id) => desktop.call("cancel", id),
  clipboard: () => desktop.call("clipboard"),
};

// ---------- state ----------

const el = {
  field: $("field"),
  fieldIcon: $("fieldIcon"),
  input: $("url"),
  error: $("error"),
  card: $("card"),
  thumbBox: document.querySelector(".thumb"),
  thumb: $("thumb"),
  duration: $("duration"),
  siteIcon: $("siteIcon"),
  siteName: $("siteName"),
  title: $("title"),
  uploader: $("uploader"),
  badges: { best: $("videoBadge"), mp3: $("mp3Badge") },
  actionArea: $("actionArea"),
  actions: document.querySelector(".actions"),
  picker: $("picker"),
  hint: $("stopHint"),
  stack: $("stack"),
  buttons: { best: $("videoBtn"), mp3: $("mp3Btn") },
};

const state = {
  backend: null,
  env: {},
  seq: 0,
  fetchedUrl: "",
  info: null,
  cardJobs: { best: null, mp3: null },
  jobs: [],
  lastClip: "",
  timer: null,
  polling: false,
  shownErrors: new Set(),
  pollTimer: null,
  cancelling: new Set(), // stopped by the user; hidden until the backend confirms
  flash: "",
  flashTimer: null,
};

const jobById = (id) => (id ? state.jobs.find((j) => j.id === id) : null);

// ---------- link field ----------

function setPlatform(platform) {
  if (document.body.dataset.platform === platform) return;
  document.body.dataset.platform = platform;
  el.fieldIcon.innerHTML = platform ? siteIcon(platform) : LINK_ICON;
}

function setError(message) {
  if (message) el.error.textContent = message;
  el.error.classList.toggle("show", !!message);
}

function shake() {
  el.field.classList.remove("shake");
  void el.field.offsetWidth;
  el.field.classList.add("shake");
}

function onInput(now = false) {
  clearTimeout(state.timer);
  const url = findUrl(el.input.value);
  setPlatform(url ? platformOf(url) : "");
  if (!url) {
    if (!el.input.value.trim()) {
      state.seq++;
      state.fetchedUrl = "";
      el.field.classList.remove("loading");
      hideCard();
      setError("");
    } else if (now) {
      setError("That doesn't look like a link. Paste the full address of a video.");
      shake();
    }
    return;
  }
  if (url === state.fetchedUrl && !now) return;
  state.timer = setTimeout(() => doFetch(url), now ? 0 : 350);
}

async function doFetch(url) {
  const seq = ++state.seq;
  state.fetchedUrl = url;
  setError("");
  el.field.classList.add("loading");
  const info = await state.backend.fetch(url);
  if (seq !== state.seq) return;
  el.field.classList.remove("loading");
  if (!info || info.error) {
    hideCard();
    setError(info?.error || "Something went wrong.");
    shake();
    return;
  }
  showCard(info);
}

el.input.addEventListener("input", () => onInput());
el.input.addEventListener("paste", () => setTimeout(() => onInput(true), 0));
el.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    onInput(true);
  }
});

async function checkClipboard() {
  if (!state.backend.clipboard) return;
  const clip = findUrl((await state.backend.clipboard()) || "");
  if (!clip || clip === state.lastClip) return;
  state.lastClip = clip;
  if (findUrl(el.input.value) === clip) return;
  el.input.value = clip;
  onInput(true);
}

// ---------- card ----------

function showCard(info) {
  const platform = platformOf(info.url);
  const src = info.thumbData || ""; // never load images from the internet directly
  state.info = info;
  // Re-attach to downloads already started for this link.
  state.cardJobs = { best: null, mp3: null };
  for (const mode of MODES) {
    const j = [...state.jobs].reverse().find((j) => j.url === info.url && (mode === "mp3") === (j.quality === "mp3")
      && ACTIVE.concat("done").includes(j.status) && !state.cancelling.has(j.id));
    if (j) state.cardJobs[mode] = j.id;
  }
  el.thumb.src = src;
  el.thumbBox.classList.toggle("empty", !src);
  el.duration.textContent = info.duration || "";
  el.siteIcon.innerHTML = siteIcon(platform);
  el.siteName.textContent = PLATFORMS[platform]?.name || info.site || "Video";
  el.title.textContent = info.title;
  el.uploader.textContent = info.uploader || "";
  for (const mode of MODES) delete el.buttons[mode].dataset.status;
  closePicker(true);
  renderButtons();
  el.card.hidden = false;
  el.card.classList.remove("in");
  void el.card.offsetWidth;
  el.card.classList.add("in");
  renderStack();
}

function hideCard() {
  closePicker(true);
  el.card.classList.remove("in");
  el.card.hidden = true;
  state.info = null;
  state.cardJobs = { best: null, mp3: null };
  renderStack();
}

el.thumb.addEventListener("error", () => el.thumbBox.classList.add("empty"));

async function onAction(mode) {
  if (!state.info) return;
  const job = jobById(state.cardJobs[mode]);
  if (job && ACTIVE.includes(job.status)) {
    // Tapping a running download stops it; the video button then offers other qualities.
    stopJob(mode, job);
    if (mode === "best") openPicker();
    return;
  }
  if (job && job.status === "done") {
    const r = await state.backend.open(job);
    if (r && r.error) setError(r.error);
    return;
  }
  const label = mode === "mp3" ? state.info.mp3Label : state.info.label;
  startDownload(mode, mode, label);
}

// quality: "best", "mp3" or a resolution like "720"; the job stays on the button for `mode`.
async function startDownload(mode, quality, label) {
  setError("");
  const res = await state.backend.add(state.info.url, quality, state.info.title, label);
  if (!res || res.error) {
    setError(res?.error || "Couldn't start the download.");
    return;
  }
  state.cardJobs[mode] = res.id;
  state.jobs.push({ id: res.id, url: state.info.url, quality, title: state.info.title, status: "queued", percent: 0, label });
  renderButtons();
  kickPoll();
}

function stopJob(mode, job) {
  state.cancelling.add(job.id);
  state.cardJobs[mode] = null;
  state.backend.cancel(job.id);
  renderButtons();
  renderStack();
}

// ---------- quality picker ----------

const CLOSE_ICON = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';

function openPicker() {
  const qualities = state.info.qualities || [];
  if (!qualities.length) return;
  if (qualities.length === 1 && !state.info.lowOnly) {
    flashHint(`Only ${qualities[0].label} available`);
    return;
  }
  el.picker.innerHTML = "";
  qualities.forEach((q, i) => {
    const pill = document.createElement("button");
    const best = i === 0 && !state.info.lowOnly;
    pill.className = "pill" + (best ? " best" : "");
    pill.style.setProperty("--i", i);
    pill.innerHTML = esc(q.label) + (best ? "<em>Best</em>" : state.info.lowOnly ? '<em class="low">low quality</em>' : "");
    pill.addEventListener("click", () => pickQuality(best ? "best" : String(q.height), q.label));
    el.picker.append(pill);
  });
  const close = document.createElement("button");
  close.className = "picker-close";
  close.setAttribute("aria-label", "Close");
  close.style.setProperty("--i", qualities.length);
  close.innerHTML = CLOSE_ICON;
  close.addEventListener("click", () => closePicker());
  el.picker.append(close);
  el.picker.classList.remove("merging");
  el.picker.hidden = false;
  el.actionArea.classList.add("picking");
  renderButtons();
}

function closePicker(instant = false) {
  if (el.picker.hidden) return;
  const finish = () => {
    el.picker.hidden = true;
    el.picker.classList.remove("merging");
    el.actionArea.classList.remove("picking");
    el.actions.classList.remove("restore");
    void el.actions.offsetWidth;
    if (!instant) el.actions.classList.add("restore");
    renderButtons();
  };
  if (instant) return finish();
  el.picker.classList.add("merging");
  setTimeout(finish, 180);
}

function pickQuality(quality, label) {
  closePicker();
  startDownload("best", quality, label);
}

function flashHint(text) {
  clearTimeout(state.flashTimer);
  state.flash = text;
  renderButtons();
  state.flashTimer = setTimeout(() => {
    state.flash = "";
    renderButtons();
  }, 1800);
}

document.addEventListener("click", (e) => {
  if (!el.picker.hidden && !e.target.closest("#picker, #videoBtn")) closePicker();
});

for (const mode of MODES) el.buttons[mode].addEventListener("click", () => onAction(mode));

function renderButtons() {
  for (const mode of MODES) renderButton(mode, jobById(state.cardJobs[mode]));
  renderBadges();
  renderHint();
}

function renderHint() {
  const active = (mode) => ACTIVE.includes(jobById(state.cardJobs[mode])?.status);
  let text = state.flash;
  if (!text && el.picker.hidden) {
    if (active("best")) text = "Tap to stop & pick quality";
    else if (active("mp3")) text = "Tap MP3 again to stop";
  }
  if (text) el.hint.textContent = text;
  el.hint.classList.toggle("show", !!text);
}

// Expected quality after fetching; the quality actually saved once a download is done.
function renderBadges() {
  if (!state.info) return;
  for (const mode of MODES) {
    const job = jobById(state.cardJobs[mode]);
    // The quality being downloaded (e.g. one picked by hand), then what was actually saved.
    const current = job && !["error", "cancelled"].includes(job.status) && job.label;
    const badge = el.badges[mode];
    badge.textContent = current || (mode === "mp3" ? state.info.mp3Label : state.info.label) || "";
    badge.classList.toggle("fallback", !!(current && job.status === "done" && job.fallback));
  }
}

function renderButton(mode, job) {
  const btn = el.buttons[mode];
  const label = btn.querySelector(".label");
  const fill = btn.querySelector(".fill");
  const status = job ? job.status : "idle";
  const prev = btn.dataset.status;
  btn.dataset.status = status;
  btn.classList.toggle("busy", ACTIVE.includes(status));
  btn.classList.toggle("processing", status === "processing");
  btn.classList.toggle("done", status === "done");
  btn.classList.toggle("failed", status === "error");
  if (status === "done" && prev && prev !== "done") {
    btn.classList.remove("pop");
    void btn.offsetWidth;
    btn.classList.add("pop");
  }

  let pct = 0;
  let html;
  switch (status) {
    case "queued":
      html = "Waiting…";
      break;
    case "downloading":
      pct = job.percent || 0;
      html = `${Math.floor(pct)}%` + (job.speed ? `<span class="speed">${esc(job.speed)}</span>` : "");
      break;
    case "processing":
      pct = 100;
      html = mode === "mp3" ? "Converting…" : "Finishing…";
      break;
    case "done":
      html = CHECK + esc(state.env.revealLabel || "Show file");
      break;
    case "error":
      html = "Try again";
      break;
    default:
      html = mode === "best" ? "Download Video" : "MP3";
  }
  fill.style.transform = `scaleX(${pct / 100})`;
  if (label.innerHTML !== html) label.innerHTML = html;
}

// ---------- queue ----------

// Ask for progress often while something downloads, rarely otherwise.
function kickPoll() {
  clearTimeout(state.pollTimer);
  poll().finally(() => {
    const busy = state.jobs.some((j) => ACTIVE.includes(j.status));
    state.pollTimer = setTimeout(kickPoll, busy ? 400 : 3000);
  });
}

async function poll() {
  if (state.polling) return;
  state.polling = true;
  try {
    const jobs = await state.backend.jobs();
    if (Array.isArray(jobs)) state.jobs = jobs;
  } finally {
    state.polling = false;
  }
  const bound = Object.values(state.cardJobs);
  for (const j of state.jobs) {
    if (j.status === "error" && !state.shownErrors.has(j.id)) {
      state.shownErrors.add(j.id);
      setError(bound.includes(j.id) ? j.error : `“${j.title}” couldn't be downloaded. ${j.error}`);
      if (bound.includes(j.id)) shake();
    }
  }
  renderButtons();
  renderStack();
}

// Slim cards for downloads that aren't on the big card.
function renderStack() {
  const bound = new Set(Object.values(state.cardJobs).filter(Boolean));
  const keep = new Set();
  for (const j of state.jobs) {
    if (!ACTIVE.includes(j.status) || bound.has(j.id) || state.cancelling.has(j.id)) continue;
    keep.add(String(j.id));
    let row = el.stack.querySelector(`[data-id="${j.id}"]`);
    if (!row) {
      row = document.createElement("div");
      row.className = "slim";
      row.dataset.id = j.id;
      row.innerHTML = `${siteIcon(platformOf(j.url))}<div class="slim-main"><div class="slim-title"></div><div class="slim-bar"><i></i></div></div><span class="slim-pct"></span>`;
      el.stack.append(row);
    }
    const pct = j.status === "processing" ? 100 : j.percent || 0;
    const title = j.quality === "mp3" ? `${j.title} · MP3` : j.title;
    row.querySelector(".slim-title").textContent = title;
    row.querySelector(".slim-bar i").style.transform = `scaleX(${pct / 100})`;
    row.querySelector(".slim-pct").textContent =
      j.status === "queued" ? "Waiting" : j.status === "processing" ? "Finishing" : `${Math.floor(pct)}%`;
  }
  for (const row of [...el.stack.children]) {
    if (!keep.has(row.dataset.id) && !row.classList.contains("leaving")) {
      row.classList.add("leaving");
      setTimeout(() => row.remove(), 250);
    }
  }
}

// ---------- panels ----------

function openPanel(id) {
  closePanels();
  $(id).classList.add("open");
  $("scrim").classList.add("show");
  if (id === "settingsPanel") refreshSettings();
}

function closePanels() {
  document.querySelectorAll(".panel.open").forEach((p) => p.classList.remove("open"));
  $("scrim").classList.remove("show");
}

$("settingsBtn").addEventListener("click", () => openPanel("settingsPanel"));
$("scrim").addEventListener("click", closePanels);
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closePanels));
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!el.picker.hidden) closePicker();
  else closePanels();
});

// Settings exist only on the desktop.
async function refreshSettings() {
  const info = await state.backend.info();
  state.env = info;
  $("folderPath").textContent = info.outputDir;
  $("folderPath").title = info.outputDir;
  const source = info.ytdlpSource === "updated" ? "updated" : "built in";
  $("ytdlpVersion").textContent = `Version ${info.ytdlp} · ${source}`;
  $("appVersion").textContent = `Dlr ${info.version}`;
  $("browserSelect").value = info.browser;
  $("browserAuto").textContent = info.defaultBrowser ? `Default browser (${info.defaultBrowser})` : "Default browser";
  // A note (e.g. an update that didn't load) or the waiting update; never shown in red.
  if (!$("updateMsg").textContent) {
    $("updateMsg").textContent = info.ytdlpNote
      || (info.updatePending ? `Version ${info.updatePending} is ready. Restart Dlr to use it.` : "")
      || (info.updateAvailable ? `Version ${info.updateAvailable} is available.` : "");
  }
  showUpdateDot(info.updatePending || info.updateAvailable);
}

// Small dot on the settings icon when a newer yt-dlp is ready (after a restart) or available.
function showUpdateDot(version) {
  $("settingsBtn").classList.toggle("has-update", !!version);
  $("settingsBtn").title = version ? `Settings · yt-dlp ${version}` : "Settings";
}

// Tools built into Dlr that are somehow missing: how to get them back (reinstalling the app,
// or a command when running from source).
function showSetupNotice(missing) {
  const box = $("setupNotice");
  box.hidden = !missing?.length;
  box.innerHTML = (missing || []).map((t) => t.command
    ? `<p><b>${esc(t.name)} isn't installed</b> (${esc(t.why)}). Install it in Terminal:</p><code>${esc(t.command)}</code>`
    : `<p><b>${esc(t.name)} is missing</b> (${esc(t.why)}). ${esc(t.fix)}</p>`).join("")
    + (missing?.some((t) => t.command) ? "<p>Then restart Dlr.</p>" : "");
}

$("browserSelect").addEventListener("change", (e) => desktop.call("set_browser", e.target.value));

async function checkForUpdate() {
  showUpdateDot(await desktop.call("update_status"));
}

$("folderBtn").addEventListener("click", async () => {
  const dir = await desktop.call("choose_folder");
  if (typeof dir === "string") {
    $("folderPath").textContent = dir;
    $("folderPath").title = dir;
  }
});

$("updateBtn").addEventListener("click", async () => {
  const btn = $("updateBtn");
  btn.disabled = true;
  btn.textContent = "Updating…";
  $("updateMsg").textContent = "";
  const r = await desktop.call("update_ytdlp");
  btn.disabled = false;
  btn.textContent = "Update";
  $("updateMsg").textContent = r.message || r.error || "";
  showUpdateDot(r.updateAvailable);
});

// Dropping a file on the window would make WebKit open it in place of this page.
for (const type of ["dragover", "drop"]) window.addEventListener(type, (e) => e.preventDefault());

// ---------- start ----------

async function init(backend) {
  state.backend = backend;
  state.env = await backend.info();
  document.body.classList.add(backend.kind);
  showSetupNotice(state.env.missing);
  el.fieldIcon.innerHTML = LINK_ICON;
  for (const mode of MODES) renderButton(mode, null);

  // Don't replay errors for downloads that failed before this page opened.
  state.jobs = (await backend.jobs()) || [];
  for (const j of state.jobs) {
    if (j.status === "error") state.shownErrors.add(j.id);
  }
  renderStack();
  kickPoll();
  // The once-a-day check runs in the background at launch; look at its answer shortly after.
  setTimeout(checkForUpdate, 6000);

  // Pause the border animation while the window isn't in front.
  const away = () => document.body.classList.toggle("away", document.hidden || !document.hasFocus());
  window.addEventListener("focus", away);
  window.addEventListener("blur", away);
  document.addEventListener("visibilitychange", away);
  away();

  if (backend.clipboard) {
    window.addEventListener("focus", checkClipboard);
    document.addEventListener("visibilitychange", () => !document.hidden && checkClipboard());
    checkClipboard();
  }
  el.input.focus();
}

if (window.pywebview?.api) init(desktop);
else window.addEventListener("pywebviewready", () => init(desktop), { once: true });
