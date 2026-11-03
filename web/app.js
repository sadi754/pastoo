"use strict";
// The window: Dashboard (one card per job, live progress), the change preview,
// and History. Talks to the app over the WebSocket (see server.py).

let REMINDER_DAYS = 7;            // older than this = "time for a backup" (from the settings, in "hello")
const token = new URLSearchParams(location.search).get("token") || "";
const $ = (id) => document.getElementById(id);
const cards = new Map();          // job id -> {el, job}
let ws = null;
let run = null;                   // the running backup, or null
let lines = [];
let previewJob = null;            // job id shown in the preview sheet
let history = { job: null, runs: [], selected: null };
let task = null;                  // a running restore or verify, or null
let taskLines = [];

// ---------- formatting ----------

function size(n) {
  n = n || 0;
  const units = LANG === "fa" ? ["بایت", "کیلوبایت", "مگابایت", "گیگابایت"] : ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return i ? `${num(n, 1)} ${units[i]}` : `${num(n)} ${units[0]}`;
}

function ago(time) {
  if (!time) return t("never");
  const s = Date.now() / 1000 - time;
  if (s < 90) return t("just now");
  if (s < 3600) return t("{n} min ago", { n: Math.round(s / 60) });
  if (s < 86400 * 2) return t("{n} h ago", { n: Math.round(s / 3600) });
  return t("{n} days ago", { n: Math.round(s / 86400) });
}

// Persian: the Jalali (Shamsi) calendar and Persian digits
const FA_DATE = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { year: "numeric", month: "2-digit", day: "2-digit",
                                                                hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

function when(time) {
  const d = new Date(time * 1000);
  if (LANG === "fa") return FA_DATE.format(d);
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function plural(n, word) {
  return LANG === "fa" ? `${num(n)} ${FA_WORDS[word] || word}` : `${num(n)} ${word}${n === 1 ? "" : "s"}`;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const STATUS_TEXT = { ok: "Done", nothing: "No changes", failed: "Failed", cancelled: "Stopped", running: "Running",
                      held: "Waited for OK" };
const statusText = (status) => (STATUS_TEXT[status] ? t(STATUS_TEXT[status]) : status);

// ---------- the change tree (preview and history) ----------

function newNode() { return { dirs: new Map(), files: [], counts: { new: 0, changed: 0, deleted: 0 } }; }

function buildTree(ch) {
  const root = newNode();
  for (const kind of ["new", "changed", "deleted"]) {
    for (const [path, bytes, bundle] of ch[kind] || []) {
      const parts = path.split("/");
      let node = root;
      node.counts[kind]++;
      for (const p of parts.slice(0, -1)) {
        if (!node.dirs.has(p)) node.dirs.set(p, newNode());
        node = node.dirs.get(p);
        node.counts[kind]++;
      }
      node.files.push({ name: parts[parts.length - 1], kind, bytes, bundle });
    }
  }
  return root;
}

function counts(c) {
  const f = document.createDocumentFragment();
  for (const kind of ["new", "changed", "deleted"]) {
    if (c[kind]) f.append(el("span", `count ${kind}`, `${kind === "new" ? "+" : kind === "changed" ? "~" : "−"}${num(c[kind])}`));
  }
  return f;
}

function renderNode(node, depth, openAll) {
  const f = document.createDocumentFragment();
  const dirs = [...node.dirs.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (let [name, child] of dirs) {
    // a folder holding only one folder: show them as one line ("a / b / c")
    while (child.files.length === 0 && child.dirs.size === 1) {
      const [n2, c2] = child.dirs.entries().next().value;
      name += " / " + n2;
      child = c2;
    }
    const d = el("details");
    d.open = openAll || depth < 2 || child.counts.deleted > 0;
    const s = el("summary");
    s.append(el("span", "dir", name), counts(child.counts));
    d.append(s, renderNode(child, depth + 1, openAll));
    f.append(d);
  }
  const marks = { new: "+", changed: "~", deleted: "−" };
  for (const file of node.files.sort((a, b) => a.name.localeCompare(b.name))) {
    const row = el("div", `file ${file.kind}`);
    row.title = file.bundle ? t("in {bundle}", { bundle: file.bundle }) : "";
    row.append(el("span", "mark", marks[file.kind]), el("span", "name", file.name), el("span", "size", size(file.bytes)));
    f.append(row);
  }
  return f;
}

function renderChanges(target, ch, { forPreview }) {
  target.replaceChildren();
  const n = (ch.new || []).length, c = (ch.changed || []).length, d = (ch.deleted || []).length;
  const bundles = ch.bundles || [];
  const chips = el("div", "chips");
  if (ch.first) chips.append(el("span", "chip", t("First backup: {files}", { files: plural(n, "file") })));
  else {
    chips.append(el("span", "chip new", t("{n} new", { n })), el("span", "chip changed", t("{n} changed", { n: c })),
                 el("span", "chip deleted", t("{n} deleted", { n: d })));
  }
  const raw = bundles.reduce((s, b) => s + b[2], 0);
  chips.append(el("span", "chip", t("{bundles} · {size} before zipping", { bundles: plural(bundles.length, "bundle"), size: size(raw) })));
  target.append(chips);

  if (d && forPreview) {
    const box = el("div", "callout");
    box.innerHTML = LANG === "fa" || d !== 1
      ? t("<b>{files} deleted</b> since the last backup (in red below). The backup will no longer have them in its current bundles; the old bundles stay in <b>_versions</b> for at least 30 days. If a deletion was a mistake, close this and restore the file first.", { files: plural(d, "file") })
      : "<b>1 file deleted</b> since the last backup (in red below). The backup will no longer have it in its current " +
        "bundles; the old bundles stay in <b>_versions</b> for at least 30 days. If the deletion was a mistake, close this and restore the file first.";
    target.append(box);
  }
  if (!n && !c && !d && !bundles.length && !(ch.stale || []).length) {
    target.append(el("div", "loading", t("Nothing changed since the last backup.")));
    return;
  }
  if (n || c || d) {
    const tree = el("div", "tree");
    tree.append(renderNode(buildTree(ch), 0, n + c + d <= 40));
    target.append(tree);
  }
  if (bundles.length) {
    target.append(el("div", "section-title", t(forPreview ? "Bundles to upload" : "Bundles uploaded")));
    const list = el("div", "bundle-list");
    for (const [key, files, bytes] of bundles) {
      const row = el("div");
      row.append(el("bdi", "", key), "  ", el("span", "size", t("{files}, {size}", { files: plural(files, "file"), size: size(bytes) })));
      list.append(row);
    }
    target.append(list);
  }
  if ((ch.stale || []).length) {
    target.append(el("div", "section-title", t("Bundles split into smaller ones (old ones go to _versions)")));
    const list = el("div", "bundle-list");
    ch.stale.forEach((k) => list.append(el("div", "", k)));
    target.append(list);
  }
}

// ---------- preview sheet ----------

// "  ·  automatic: every day at 21:00, next ..." for a job's card
function autoText(job) {
  if (!job.schedule || job.schedule === "off") return "";
  const how = job.schedule === "daily" ? t("every day at {time}", { time: digits(job.schedule_time) })
    : t("every {hours}", { hours: plural(job.schedule_hours, "hour") });
  const next = job.next_auto && job.next_auto * 1000 > Date.now() ? t(", next {when}", { when: when(job.next_auto) }) : t(", next soon");
  return t("automatic: {how}{next}", { how, next });
}

// files another program is writing to (a mounted VeraCrypt container, an open .pst ...)
function busyText(names, count, waiting) {
  const which = names.map((r) => r.split("/").pop()).join(", ") + (count > names.length ? " ..." : "");
  return t("{files} in use by another program ({which}): the last backed-up copy stays", { files: plural(count, "file"), which })
    + (waiting ? t(", and {bundles} with other changes wait", { bundles: plural(waiting, "bundle") }).replace(/wait$/, waiting === 1 ? "waits" : "wait") : "")
    + t(". Close it, then back up again.");
}

function openPreview(jobId) {
  previewJob = jobId;
  const job = cards.get(jobId).job;
  $("preview-title").textContent = t("Changes in {name}", { name: job.name });
  $("preview-sub").textContent = t("Looking for changes ...");
  $("preview-foot").textContent = "";
  $("preview-body").replaceChildren(el("div", "loading", t("Looking for changes ...")));
  $("preview-backup").disabled = true;
  $("preview").hidden = false;
  send({ type: "preview", job: jobId });
}

function showPreview(m) {
  if (m.job !== previewJob || $("preview").hidden) return;
  $("preview-sub").textContent = t("{source} · checked {when}", { source: cards.get(m.job).job.source, when: ago(m.checked) });
  renderChanges($("preview-body"), m, { forPreview: true });
  const d = (m.deleted || []).length;
  $("preview-foot").textContent = d ? t("{files} will leave the current backup", { files: plural(d, "deleted file") }) : "";
  const busy = m.busy || [];
  if (busy.length) $("preview-body").prepend(el("div", "busy-note", busyText(busy.slice(0, 5), busy.length, (m.waiting || []).length)));
  $("preview-backup").textContent = d ? t("Back up now (with {n} deletions)", { n: d }).replace("(with 1 deletions)", "(with 1 deletion)")
    : t("Back up now");
  $("preview-backup").disabled = !!run || !(m.bundles.length || (m.stale || []).length || d);
}

function closePreview() { $("preview").hidden = true; previewJob = null; }

$("preview-close").onclick = closePreview;
$("preview-cancel").onclick = closePreview;
$("preview").onclick = (e) => { if (e.target === $("preview")) closePreview(); };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePreview(); });
$("preview-backup").onclick = () => {
  send({ type: "backup", job: previewJob });
  closePreview();
};

// ---------- dashboard ----------

function card(job) {
  let c = cards.get(job.id);
  if (!c) {
    const node = document.getElementById("job-card").content.firstElementChild.cloneNode(true);
    const backup = () => {
      const p = cards.get(job.id).job.pending;
      // deletions are always looked at before they go out
      if (p && p.deleted) openPreview(job.id);
      else send({ type: "backup", job: job.id });
    };
    node.querySelector(".backup").onclick = backup;
    node.querySelector(".small-backup").onclick = backup;
    node.querySelector(".job-head").onclick = (e) => {
      if (!e.target.closest("button")) foldCard(job.id, !node.classList.contains("folded"));
    };
    node.classList.toggle("folded", cardFolds[job.id] ?? false);
    node.querySelector(".check").onclick = () => {
      node.querySelector(".pending-text").textContent = t("Checking ...");
      send({ type: "check", job: job.id });
    };
    node.querySelector(".review").onclick = () => openPreview(job.id);
    node.querySelector(".stop").onclick = () => {
      node.querySelector(".stop").disabled = true;
      send({ type: "stop" });
    };
    $("view-dashboard").append(node);
    c = { el: node };
    cards.set(job.id, c);
    for (const select of [$("history-job"), $("restore-job")]) {
      const opt = el("option", "", job.name);
      opt.value = job.id;
      select.append(opt);
    }
  }
  c.job = job;
  return c;
}

// which dashboard cards are folded - kept in settings.json (comes with "hello")
let cardFolds = {};

function foldCard(jobId, fold) {
  const c = cards.get(jobId);
  if (!c) return;
  c.el.classList.toggle("folded", fold);
  cardFolds[jobId] = fold;
  send({ type: "fold", job: jobId, folded: fold });
}

function pendingShort(p) {
  if (!p || p.error) return "";
  if (!(p.new || p.changed || p.deleted || p.todo)) return t("no changes");
  return `<span class="changes">${changeParts(p) || t("bundles to tidy up")}</span> ${ARROW()} ${plural(p.todo, "bundle")}`;
}

// "3 new, 1 changed, 2 deleted" (deleted in red)
function changeParts(p) {
  const parts = [];
  if (p.new) parts.push(t("{n} new", { n: p.new }));
  if (p.changed) parts.push(t("{n} changed", { n: p.changed }));
  if (p.deleted) parts.push(`<span class="deleted-count">${t("{n} deleted", { n: p.deleted })}</span>`);
  return parts.join(LANG === "fa" ? "، " : ", ");
}

function health(job) {
  if (run && run.job === job.id) return ["running", t("Backing up")];
  if (job.last_run && job.last_run.status === "failed") return ["failed", t("Last backup failed")];
  if (job.last_run && job.last_run.status === "held") return ["waiting", t("Needs your OK")];
  const p = job.pending;
  if (p && !p.error && (p.new || p.changed || p.deleted || p.todo)) return ["waiting", t("Changes to back up")];
  if (!job.last_ok) return ["old", t("Never backed up")];
  if (Date.now() / 1000 - job.last_ok > REMINDER_DAYS * 86400) return ["old", t("Time for a backup")];
  return ["ok", t("Up to date")];
}

function runRow(r, columns) {
  const tr = document.createElement("tr");
  const all = {
    when: when(r.started), result: statusText(r.status), new: r.new == null ? "" : num(r.new),
    changed: r.changed == null ? "" : num(r.changed), deleted: r.deleted == null ? "" : num(r.deleted),
    bundles: r.bundles == null ? "" : num(r.bundles), sent: r.sent ? size(r.sent) : "",
  };
  for (const col of columns) {
    const td = el("td", ["when", "result"].includes(col) ? "" : "num", all[col]);
    if (col === "result") {
      td.className = `status-${r.status}`;
      if (r.error) td.title = tMsg(r.error);
    }
    tr.append(td);
  }
  return tr;
}

function renderJob(job) {
  const { el: node } = card(job);
  const q = (s) => node.querySelector(s);
  q(".job-name").textContent = job.name;
  // the folder stays left to right in the Persian page (<bdi>)
  q(".job-route").replaceChildren(el("bdi", "", `${job.source}  →  files.ir / ${job.remote_root}`),
                                  autoText(job) ? `  ·  ${autoText(job)}` : "");
  const [cls, text] = health(job);
  q(".badge").className = `badge ${cls}`;
  q(".badge").textContent = text;

  const last = job.last_run;
  q(".last").textContent = ago(job.last_ok);
  q(".last").className = "tile-value last " + (cls === "failed" ? "bad" : cls === "old" ? "fair" : "");
  q(".last-sub").textContent = last ? `${when(last.started)} · ${statusText(last.status)}` : "";
  q(".files").textContent = t("{n} files", { n: job.files });
  q(".size").textContent = size(job.size);
  q(".remote").textContent = size(job.remote_size);
  q(".bundles").textContent = plural(job.bundles, "bundle");
  q(".versions").textContent = num(job.versions);
  q(".versions-sub").textContent = job.versions ? size(job.versions_size) : t("none yet");

  const p = job.pending;
  const pt = q(".pending-text");
  const changes = p && !p.error && (p.new || p.changed || p.deleted || p.todo);
  const checked = p ? `<span class="muted">${t("· checked {when}", { when: ago(p.checked) })}</span>` : "";
  if (!p) pt.textContent = t("Not checked yet");
  else if (p.error) pt.textContent = t("Checking failed: {error}", { error: tMsg(p.error) });
  else if (!changes) pt.innerHTML = `${t("No changes since the last backup")} ${checked}`;
  else {
    pt.innerHTML = `<span class="changes">${changeParts(p) || t("Bundles to tidy up")}</span> ${ARROW()} ` +
      `${t("{bundles} to upload", { bundles: `<b>${plural(p.todo, "bundle")}</b>` })} ${checked}`;
  }
  if (p && p.busy_count) pt.append(el("div", "busy-note", busyText(p.busy, p.busy_count, p.waiting)));
  if (job.last_run && job.last_run.status === "held") {
    pt.append(el("div", "busy-note", t("The automatic backup waits for you: {why}. Look at the changes, then press Back up now if they are right.",
                                         { why: tMsg(job.last_run.error) })));
  }
  q(".review").hidden = !changes;

  const busy = !!run || !!task;
  q(".backup").disabled = busy;
  q(".small-backup").disabled = busy;
  q(".check").disabled = busy;
  q(".review").disabled = busy;
  // the one line a folded card shows
  const short = pendingShort(p);
  q(".job-summary").innerHTML = run && run.job === job.id
    ? t("Backing up - {progress}", { progress: run.total ? `${num(run.i)} / ${plural(run.total, "bundle")}` : t("looking for changes") })
    : t("Last backup {when}", { when: ago(job.last_ok) }) + (short ? ` · ${short}` : "");
  q(".runs tbody").replaceChildren(...job.recent.map(
    (r) => runRow(r, ["when", "result", "new", "changed", "deleted", "bundles", "sent"])));
}

function renderRun() {
  for (const [id, { el: node }] of cards) {
    const mine = run && run.job === id;
    node.querySelector(".progress").hidden = !mine || run.phase === "done";
    if (!mine) continue;
    if (node._openedFor !== run.started) {      // a backup starting opens its card (once per run)
      node._openedFor = run.started;
      node.classList.remove("folded");
    }
    node.querySelector(".result").hidden = true;
    const phase = t({ scanning: "Looking for changes ...", uploading: "Uploading", finishing: "Finishing ..." }[run.phase] || run.phase);
    node.querySelector(".phase").textContent = phase;
    const bar = node.querySelector(".bar");
    const known = run.phase === "uploading" && run.total > 0;
    bar.classList.toggle("indeterminate", !known);
    bar.querySelector("i").style.width = known ? `${(100 * run.i) / run.total}%` : "";
    node.querySelector(".progress-numbers").textContent = known
      ? t("{i} / {bundles} · {size} sent · {s} s", { i: run.i, bundles: plural(run.total, "bundle"), size: size(run.sent),
                                                         s: Math.round(Date.now() / 1000 - run.started) }) : "";
    const log = node.querySelector(".log");
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
    log.textContent = lines.join("\n");
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
}

function showResult(r) {
  const c = cards.get(r.job);
  if (!c) return;
  const res = r.result;
  const box = c.el.querySelector(".result");
  box.className = `result ${res.status}`;
  box.textContent = {
    ok: t("Backup finished: {bundles}, {size} uploaded", { bundles: plural(res.bundles || 0, "bundle"), size: size(res.sent) })
      + (res.report ? t(" · report {report}", { report: res.report }) : ""),
    nothing: t("Nothing changed - the backup is up to date."),
    cancelled: t("Stopped. The next backup continues where this one stopped."),
    failed: t("The backup failed: {error}. Run it again - it continues where it stopped.", { error: tMsg(res.error) || t("see the log") }),
    busy: t("Another backup is running (from the command line?). Try again when it is done."),
    held: t("The automatic backup waits for you: {why}.", { why: tMsg(res.error) }),
  }[res.status] || res.status;
  box.hidden = false;
  c.el.querySelector(".stop").disabled = false;
}

// ---------- history ----------

function loadHistory(before) {
  const job = $("history-job").value;
  if (!job) return;
  if (!before) {
    history = { job, runs: [], selected: null };
    $("history-rows").replaceChildren();
    $("history-detail").replaceChildren(el("div", "muted empty", t("Choose a run to see what it backed up.")));
  }
  send({ type: "history", job, before });
}

function showHistory(m) {
  if (m.job !== history.job) return;
  history.runs = m.append ? history.runs.concat(m.runs) : m.runs;
  $("history-rows").replaceChildren(...history.runs.map((r) => {
    const tr = runRow(r, ["when", "result", "new", "changed", "deleted", "sent"]);
    tr.classList.toggle("selected", r.id === history.selected);
    tr.onclick = () => {
      history.selected = r.id;
      for (const row of $("history-rows").children) row.classList.remove("selected");
      tr.classList.add("selected");
      $("history-detail").replaceChildren(el("div", "loading", t("Loading ...")));
      send({ type: "run_detail", job: history.job, id: r.id });
    };
    return tr;
  }));
  $("history-more").hidden = !m.more;
  if (!history.runs.length) $("history-detail").replaceChildren(el("div", "muted empty", t("No backups yet.")));
}

function showRunDetail(m) {
  const r = m.run;
  if (m.job !== history.job || r.id !== history.selected) return;
  const box = $("history-detail");
  box.replaceChildren();
  box.append(el("div", "detail-title", `${when(r.started)} · ${statusText(r.status)}`));
  const facts = [];
  if (r.finished) facts.push(t("took {s} s", { s: Math.max(1, Math.round(r.finished - r.started)) }));
  if (r.sent) facts.push(t("{size} uploaded", { size: size(r.sent) }));
  if (r.report) facts.push(t("report: {report}", { report: r.report }));
  box.append(el("div", "muted", facts.join(" · ")));
  if (r.error) box.append(el("div", "callout", tMsg(r.error)));
  const body = el("div");
  body.style.marginTop = "14px";
  box.append(body);
  if (r.changes) renderChanges(body, r.changes, { forPreview: false });
  else if (r.report_text) body.append(el("pre", "report-text", r.report_text));
  else body.append(el("div", "muted", t(r.status === "nothing" ? "Nothing had changed." : "No details were kept for this run.")));
}

$("history-job").onchange = () => loadHistory();
$("history-more").onclick = () => loadHistory(history.runs[history.runs.length - 1].id);

// ---------- views ----------

function showView() {
  const view = (location.hash || "#dashboard").slice(1);
  for (const v of ["dashboard", "history", "restore", "settings"]) $(`view-${v}`).hidden = v !== view;
  for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.view === view);
  if (view === "history") loadHistory();
  if (view === "restore" && restore.job !== $("restore-job").value) loadRestore();
  if (view === "settings" && !settingsLoaded) send({ type: "settings" });
  if (view === "settings") send({ type: "usage" });
}

// ---------- settings ----------

let settingsLoaded = false;
let settingsData = null;
const forms = new Map();          // job id ("" = a new one) -> form element
let savingForm = null;            // the form whose Save is on its way
const MB = 1048576;
const splitLines = (text) => text.split("\n").map((s) => s.trim()).filter(Boolean);
let justSaved = null;              // job id whose form shows "Saved." once it is redrawn

function formValues(form) {
  const f = form.elements;
  const number = (name) => Number(f[name].value);
  return {
    id: form.dataset.id || undefined, name: f.name.value, source: f.source.value, remote_root: f.remote_root.value,
    skip_dir_names: splitLines(f.skip_dir_names.value), skip_paths: splitLines(f.skip_paths.value),
    skip_files: splitLines(f.skip_files.value), bundle_mb: number("bundle_mb"), big_file_mb: number("big_file_mb"),
    keep_versions: number("keep_versions"), keep_days: number("keep_days"),
    schedule: f.schedule.value, schedule_time: f.schedule_time.value, schedule_hours: number("schedule_hours"),
  };
}

// the time / hours fields that go with the chosen automatic backup
function showAuto(form) {
  const mode = form.elements.schedule.value;
  form.querySelector(".auto-time").hidden = mode !== "daily";
  form.querySelector(".auto-hours").hidden = mode !== "hours";
  form.querySelector(".auto-hint").hidden = mode === "off";
}

function fillForm(form, job) {
  const f = form.elements;
  f.name.value = job.name || "";
  f.source.value = job.source || "";
  f.remote_root.value = job.remote_root || "";
  f.skip_dir_names.value = (job.skip_dir_names || []).join("\n");
  f.skip_paths.value = (job.skip_paths || []).join("\n");
  f.skip_files.value = (job.skip_files || []).join("\n");
  f.bundle_mb.value = Math.round((job.bundle_limit || 10 * MB) / MB);
  f.big_file_mb.value = Math.round((job.big_file || 5 * MB) / MB);
  f.keep_versions.value = job.keep_versions ?? 5;
  f.keep_days.value = job.keep_days ?? 30;
  f.schedule.value = job.schedule || "off";
  f.schedule_time.value = job.schedule_time || "21:00";
  f.schedule_hours.value = job.schedule_hours ?? 6;
  form._saved = JSON.stringify(formValues(form));
  form._job = job;
  form.querySelector(".form-sub").textContent = job.id ? `${job.source}  →  files.ir / ${job.remote_root}` : "";
  f.source.disabled = f.remote_root.disabled = !!job.locked;
  form.querySelector(".browse").disabled = !!job.locked;
  form.querySelector(".lock-note").hidden = !job.locked;
  form.querySelector(".form-title").textContent = job.id ? job.name : t("New backup job");
  form.querySelector(".remove").hidden = !job.id;
  formChanged(form);
}

function formChanged(form) {
  const now = formValues(form);
  const dirty = JSON.stringify(now) !== form._saved;
  form.querySelector(".save").disabled = !dirty && !!form.dataset.id;
  form.querySelector(".cancel").hidden = !dirty || !form.dataset.id;
  const warn = [];
  if (form._job.locked) {
    const was = JSON.parse(form._saved);
    if (now.bundle_mb !== was.bundle_mb || now.big_file_mb !== was.big_file_mb) {
      warn.push(t("Changing the bundle sizes re-packs the folders: the next backup uploads most bundles again."));
    }
    const rules = ["skip_dir_names", "skip_paths", "skip_files"];
    if (rules.some((k) => JSON.stringify(now[k]) !== JSON.stringify(was[k]))) {
      warn.push(t("Files that the new rules skip leave the backup: the next backup shows them as deleted (red in the preview)."));
    }
  }
  if (now.schedule !== "off" && settingsData && !settingsData.app.start_with_windows) {
    warn.push(t("Start with Windows is off (App, below): automatic backups only run while Pastoo is open."));
  }
  showAuto(form);
  const box = form.querySelector(".warn");
  box.innerHTML = warn.join("<br>");
  box.hidden = !warn.length;
  form.querySelector(".unsaved").hidden = !dirty || !form.dataset.id;
  clearTimeout(form._timer);
  if (!form.classList.contains("folded")) form._timer = setTimeout(() => measureForm(form), 500);
  else form._measured = false;            // count when it is opened
}

const folded = new Map();          // job id -> folded? (jobs start folded, a new one open)

function setFolded(form, fold) {
  form.classList.toggle("folded", fold);
  folded.set(form.dataset.id, fold);
  if (!fold && !form._measured) {
    form._measured = true;
    measureForm(form);
  }
}

function measureForm(form) {
  const v = formValues(form);
  const box = form.querySelector(".measure");
  if (!v.source.trim()) { box.textContent = t("Choose the folder to back up."); return; }
  box.textContent = t("Counting ...");
  form._ref = String(Math.random());
  send({ type: "measure", job: v, ref: form._ref });
}

function showMeasure(m) {
  const form = [...forms.values()].find((f) => f._ref === m.ref);
  if (!form) return;
  const box = form.querySelector(".measure");
  box.replaceChildren();
  const head = el("div");
  head.innerHTML = t("Backed up with these rules: <b>{files} · {size}</b> in about {bundles}",
                     { files: t("{n} files", { n: m.files }), size: size(m.size), bundles: plural(m.bundles, "bundle") }) +
    t(" &nbsp;·&nbsp; skipped: {files} · {size}", { files: t("{n} files", { n: m.skipped_files }), size: size(m.skipped_size) });
  box.append(head);
  if (m.skipped.length) {
    const grid = el("div", "skips");
    for (const [what, files, bytes] of m.skipped) grid.append(el("span", "", what), el("span", "", plural(files, "file")), el("span", "", size(bytes)));
    box.append(el("div", "", t("Biggest skipped:")), grid);
  }
}

function makeForm(job) {
  const form = document.getElementById("job-form").content.firstElementChild.cloneNode(true);
  form.dataset.id = job.id || "";
  form.classList.toggle("new", !job.id);
  form.addEventListener("input", () => formChanged(form));
  form.querySelector(".form-head").onclick = (e) => {
    if (e.target.closest("button")) return;
    setFolded(form, !form.classList.contains("folded"));
  };
  form.querySelector(".common").onclick = () => {
    const common = (settingsData && settingsData.common_skips) || {};
    for (const [name, add] of Object.entries(common)) {
      const area = form.elements[name];
      const have = splitLines(area.value);
      const lower = new Set(have.map((x) => x.toLowerCase()));
      area.value = have.concat(add.filter((x) => !lower.has(x.toLowerCase()))).join("\n");
    }
    formChanged(form);
  };
  form.onsubmit = (e) => {
    e.preventDefault();
    savingForm = form;
    setFormMsg(form, t("Saving ..."), "");
    send({ type: "save_job", job: formValues(form) });
  };
  form.querySelector(".cancel").onclick = () => fillForm(form, form._job);
  form.querySelector(".remove").onclick = () => {
    if (!confirm(t("Remove \"{name}\" from Pastoo?\nIts backup on files.ir stays as it is.", { name: form._job.name }))) return;
    savingForm = form;
    send({ type: "remove_job", id: form.dataset.id });
  };
  form.querySelector(".browse").onclick = async () => {
    if (!(window.pywebview && window.pywebview.api)) { showError(t("The folder dialog works in the app's own window - type the folder instead.")); return; }
    const folder = await window.pywebview.api.pick_folder(form.elements.source.value);
    if (!folder) return;
    const f = form.elements;
    f.source.value = folder;
    const base = folder.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
    if (!f.name.value) f.name.value = base;
    if (!f.remote_root.value) f.remote_root.value = `${base} backup`;
    formChanged(form);
  };
  form.classList.add("folded");           // so fillForm does not count yet
  fillForm(form, job);
  setFolded(form, folded.has(form.dataset.id) ? folded.get(form.dataset.id) : !!job.id);
  return form;
}

function setFormMsg(form, text, cls) {
  const msg = form.querySelector(".form-msg");
  msg.textContent = text;
  msg.className = `form-msg ${cls}`;
}

function showSettings(m) {
  settingsLoaded = true;
  settingsData = m;
  const status = $("key-status");
  status.textContent = t(m.key ? "Key saved in Windows Credential Manager." : "No files.ir key yet - paste one below.");
  status.className = m.key ? "good" : "bad";
  $("app-autostart").checked = m.app.start_with_windows;
  if (document.activeElement !== $("app-reminder")) $("app-reminder").value = m.app.reminder_days;
  $("app-language").value = m.app.language || "auto";
  // keep forms with unsaved edits; redraw the rest
  const box = $("job-forms");
  for (const job of m.jobs) {
    const old = forms.get(job.id);
    if (old && JSON.stringify(formValues(old)) !== old._saved && old !== savingForm) continue;
    const form = makeForm(job);
    if (old) old.replaceWith(form); else box.append(form);
    forms.set(job.id, form);
  }
  for (const [id, form] of [...forms]) {
    if (id && !m.jobs.some((j) => j.id === id)) { form.remove(); forms.delete(id); }
  }
  if (justSaved && forms.has(justSaved)) {
    setFormMsg(forms.get(justSaved), t("Saved."), "good");
    justSaved = null;
  }
}

function onSaved(m) {
  const form = savingForm;
  savingForm = null;
  if (m.what === "job") {
    if (form && !form.dataset.id) {       // the saved job's own form comes with "settings" - open, like this one
      form.remove();
      forms.delete("");
      folded.delete("");
      folded.set(m.job.id, false);
    }
    else if (form) form._saved = JSON.stringify(formValues(form));       // so the redraw replaces it
    justSaved = m.job.id;
  }
  if (m.what === "key") {
    $("key-input").value = "";
    $("key-status").textContent = t("Key checked with files.ir and saved in Windows Credential Manager.");
  }
}

$("job-add").onclick = () => {
  if (forms.has("")) { forms.get("").scrollIntoView({ behavior: "smooth" }); return; }
  folded.delete("");                      // a new job always opens
  const form = makeForm({ ...(settingsData ? settingsData.new_job : {}), name: "", source: "", remote_root: "" });
  $("job-forms").prepend(form);
  forms.set("", form);
  form.querySelector(".cancel").hidden = true;
  const remove = form.querySelector(".remove");
  remove.hidden = false;
  remove.textContent = t("Cancel");
  remove.onclick = () => { form.remove(); forms.delete(""); };
};
$("key-save").onclick = () => {
  $("key-status").textContent = t("Checking the key with files.ir ...");
  $("key-status").className = "muted";
  send({ type: "set_key", key: $("key-input").value });
};
$("key-test").onclick = () => {
  $("key-status").textContent = t("Connecting to files.ir ...");
  $("key-status").className = "muted";
  send({ type: "test_key" });
};
$("app-autostart").onchange = () => send({ type: "save_app", app: { start_with_windows: $("app-autostart").checked } });
$("app-language").onchange = () => {
  send({ type: "save_app", app: { language: $("app-language").value } });
  setTimeout(() => location.reload(), 400);         // everything drawn again in the new language
};

// ---------- files.ir usage (Settings, and a warning on every page from 70 %) ----------

const WARN_AT = 0.7;

function showUsage(u) {
  if (!u) return;
  const lim = u.limits;
  const describe = (l) => t("{space} · {files} · {file} per file", { space: size(l.space), files: t("{n} files", { n: l.files }), file: size(l.file) });
  $("limits-mode").value = u.mode;
  $("limits-check").hidden = u.mode !== "auto";
  $("custom-limits").hidden = u.mode !== "custom";
  const text = $("plan-limits");
  if (u.mode === "custom") {
    text.textContent = describe(lim);
    text.className = "muted";
  } else if (u.plan_error) {
    text.textContent = t("files.ir did not say ({error}) - using {which}: {limits}", { error: tMsg(u.plan_error),
      which: t(u.detected ? "what it said last time" : "the Free plan's limits"), limits: describe(lim) });
    text.className = "bad";
  } else {
    // the plan's name comes from files.ir in Persian: <bdi> keeps it from reordering the English around it
    text.replaceChildren(el("bdi", "", lim.name || "?"),
                         `: ${describe(lim)}` + (u.detected ? t(" · read {when}", { when: ago(u.detected.checked) }) : ""));
    text.className = "muted";
  }
  if (![$("custom-space"), $("custom-files"), $("custom-file")].includes(document.activeElement)) {
    $("custom-space").value = Math.round(u.custom.space / 1073741824);
    $("custom-files").value = u.custom.files;
    $("custom-file").value = Math.round(u.custom.file / 1048576);
  }
  const bar = (id, used, total) => {
    const share = total ? used / total : 0;
    const i = $(id);
    i.style.width = `${Math.min(100, Math.max(share * 100, used ? 1 : 0))}%`;
    i.className = share >= 0.9 ? "bad" : share >= WARN_AT ? "fair" : "";
    return share;
  };
  const space = u.space_used == null ? 0 : bar("space-bar", u.space_used, u.space_total);
  const files = bar("files-bar", u.files, u.files_total);
  $("space-text").textContent = u.space_used == null ? t("unknown") :
    t("{used} of {total} ({p}%)", { used: size(u.space_used), total: size(u.space_total), p: Math.round(space * 100) });
  $("files-text").textContent = t("about {used} of {total} ({p}%)", { used: u.files, total: u.files_total, p: Math.round(files * 100) });
  $("usage-note").textContent = (u.error ? t("Could not ask files.ir about the space: {error}. ", { error: tMsg(u.error) }) : "") +
    t("Space is the whole account's; files are Pastoo's own (other apps' files on the account count too). Files bigger than {size} go up in parts. Checked {when}.",
      { size: size(u.part_size), when: ago(u.checked) });
  const warn = $("usage-warn");
  const worst = Math.max(space, files);
  warn.hidden = worst < WARN_AT;
  warn.className = `banner${worst >= 0.9 ? " error" : ""}`;
  warn.textContent = t("files.ir is {p}% full ({what}) - see Settings → files.ir. A bigger plan, fewer old versions, or more skips will help.",
                       { p: Math.round(worst * 100), what: t(space >= files ? "space" : "number of files") });
}

$("limits-mode").onchange = () => send({ type: "save_app", app: { limits_mode: $("limits-mode").value } });
$("limits-check").onclick = () => {
  $("plan-limits").textContent = t("Asking files.ir ...");
  send({ type: "usage" });
};
$("custom-save").onclick = () => send({ type: "save_app", app: { custom_limits: {
  space_gb: Number($("custom-space").value), files: Number($("custom-files").value),
  file_mb: Number($("custom-file").value) } } });
$("usage-warn").onclick = () => { location.hash = "#settings"; };
$("welcome-go").onclick = () => { location.hash = "#settings"; };
$("app-reminder").onchange = () => {
  const days = Math.round(Number($("app-reminder").value));
  if (days >= 1 && days <= 365) send({ type: "save_app", app: { reminder_days: days } });
};

function showError(message) {
  const box = $("error");
  box.textContent = tMsg(message);
  box.hidden = false;
  clearTimeout(showError.timer);
  showError.timer = setTimeout(() => { box.hidden = true; }, 7000);
}

// ---------- restore ----------

const restore = { job: null, source: "latest", browse: null, files: [], tree: null, picked: new Set(),
                  versions: new Map() };
const fileSize = new Map();       // path -> bytes, for the selection summary

function loadRestore() {
  const job = $("restore-job").value;
  if (!job) return;
  restore.job = job;
  restore.picked.clear();
  $("restore-tree").replaceChildren(el("div", "loading", t("Loading ...")));
  send({ type: "browse", job });
}

function showBrowse(m) {
  if (m.job !== restore.job) return;
  restore.browse = m;
  $("restore-original").textContent = m.source;
  const select = $("restore-source");
  const keep = select.value;
  select.replaceChildren();
  const latest = el("option", "", t("Latest backup"));
  latest.value = "latest";
  select.append(latest);
  if (m.versions.length) {
    const group = document.createElement("optgroup");
    group.label = t("Old versions (bundles that were replaced)");
    for (const v of m.versions) {
      const o = el("option", "", t("until {when} · {key} ({size})", { when: when(v.created), key: v.key, size: size(v.size) }));
      o.value = String(v.id);
      group.append(o);
    }
    select.append(group);
  }
  select.value = [...select.options].some((o) => o.value === keep) ? keep : "latest";
  $("verify-all").textContent = t("Check everything ({bundles}, {size})", { bundles: plural(m.bundles, "bundle"), size: size(m.remote_size) });
  showLastCheck(m.last_check);
  chooseSource();
}

function chooseSource() {
  restore.source = $("restore-source").value;
  restore.picked.clear();
  if (restore.source === "latest") return setRestoreFiles(restore.browse.files);
  const id = Number(restore.source);
  if (restore.versions.has(id)) return setRestoreFiles(restore.versions.get(id));
  $("restore-tree").replaceChildren(el("div", "loading", t("Downloading that version from files.ir ...")));
  updateSummary();
  send({ type: "version_files", job: restore.job, id });
}

function pickNode() { return { dirs: new Map(), files: [], rels: [] }; }

function setRestoreFiles(files) {
  restore.files = files;
  fileSize.clear();
  const root = pickNode();
  for (const [rel, bytes] of files) {
    fileSize.set(rel, bytes);
    const parts = rel.split("/");
    let node = root;
    node.rels.push(rel);
    for (const p of parts.slice(0, -1)) {
      if (!node.dirs.has(p)) node.dirs.set(p, pickNode());
      node = node.dirs.get(p);
      node.rels.push(rel);
    }
    node.files.push([parts[parts.length - 1], rel, bytes]);
  }
  restore.tree = root;
  renderPick();
}

function checkbox(rels) {
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb._rels = rels;
  cb.onclick = (e) => {
    e.stopPropagation();          // a click on a folder's box must not open/close the folder
    const all = rels.every((r) => restore.picked.has(r));
    for (const r of rels) all ? restore.picked.delete(r) : restore.picked.add(r);
    refreshChecks();
  };
  return cb;
}

function fileRow(name, rel, bytes, showPath) {
  const row = el("label", "file");
  row.append(checkbox([rel]), el("span", "name", name));
  if (showPath) row.append(el("span", "path", rel.slice(0, rel.length - name.length).replace(/\/$/, "")));
  row.append(el("span", "size", size(bytes)));
  return row;
}

function renderPickNode(node) {
  const f = document.createDocumentFragment();
  for (const [name, child] of [...node.dirs.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const d = el("details");
    const s = el("summary");
    const total = child.rels.reduce((sum, r) => sum + fileSize.get(r), 0);
    s.append(checkbox(child.rels), el("span", "dir", name), el("span", "size", `${plural(child.rels.length, "file")} · ${size(total)}`));
    d.append(s);
    d.addEventListener("toggle", () => {   // the contents are made when the folder is first opened
      if (d.open && d.children.length === 1) {
        d.append(renderPickNode(child));
        refreshChecks();
      }
    });
    f.append(d);
  }
  for (const [name, rel, bytes] of node.files.sort((a, b) => a[0].localeCompare(b[0]))) f.append(fileRow(name, rel, bytes));
  return f;
}

function renderPick() {
  const box = $("restore-tree");
  const q = $("restore-filter").value.trim().toLowerCase();
  box.replaceChildren();
  if (!restore.files.length) box.append(el("div", "note", t("Nothing in here.")));
  else if (!q) box.append(renderPickNode(restore.tree));
  else {
    // folders whose own name matches (tick one = all its files), then matching files
    const folders = new Map();
    for (const [rel] of restore.files) {
      const parts = rel.split("/");
      for (let i = 1; i < parts.length; i++) {
        if (parts[i - 1].toLowerCase().includes(q)) {
          const path = parts.slice(0, i).join("/");
          if (!folders.has(path)) folders.set(path, []);
          folders.get(path).push(rel);
        }
      }
    }
    const hits = restore.files.filter(([rel]) => rel.split("/").pop().toLowerCase().includes(q));
    for (const [path, rels] of [...folders.entries()].slice(0, 50)) {
      const row = el("label", "file");
      const total = rels.reduce((sum, r) => sum + fileSize.get(r), 0);
      row.append(checkbox(rels), el("span", "dir", path), el("span", "size", `${plural(rels.length, "file")} · ${size(total)}`));
      box.append(row);
    }
    for (const [rel, bytes] of hits.slice(0, 300)) box.append(fileRow(rel.split("/").pop(), rel, bytes, true));
    if (!folders.size && !hits.length) box.append(el("div", "note", t("Nothing matches.")));
    else if (hits.length > 300 || folders.size > 50) box.append(el("div", "note", t("More match - type more of the name.")));
  }
  refreshChecks();
}

function refreshChecks() {
  for (const cb of $("restore-tree").querySelectorAll("input[type=checkbox]")) {
    const n = cb._rels.filter((r) => restore.picked.has(r)).length;
    cb.checked = n > 0 && n === cb._rels.length;
    cb.indeterminate = n > 0 && n < cb._rels.length;
  }
  updateSummary();
}

function updateSummary() {
  const n = restore.picked.size;
  const total = [...restore.picked].reduce((sum, r) => sum + (fileSize.get(r) || 0), 0);
  $("restore-summary").innerHTML = n ? t("<b>{files}</b> chosen · {size}", { files: plural(n, "file"), size: size(total) })
    : t("Tick the files or folders to get back.");
  $("restore-go").disabled = !n || !!run || !!task;
  $("restore-go").textContent = n ? t("Restore {files}", { files: plural(n, "file") }) : t("Restore");
}

function showLastCheck(c) {
  const box = $("verify-last");
  box.className = c && c.bad ? "bad" : "muted";
  box.textContent = !c ? t("Not checked yet.") :
    t("Last check: {when} ({ago}) · {what}, {files} · {result}", { when: when(c.time), ago: ago(c.time),
      what: c.full ? t("everything") : plural(c.bundles, "random bundle"), files: plural(c.files, "file"),
      result: c.bad ? plural(c.bad, "problem") : t("all good") });
}

function renderTask() {
  for (const kind of ["restore", "verify"]) {
    const box = $(`${kind}-task`);
    const mine = task && task.kind === kind;
    box.hidden = !mine;
    if (!mine) continue;
    $(`${kind}-result`).hidden = true;
    box.querySelector(".bar i").style.width = task.total ? `${(100 * task.i) / task.total}%` : "0";
    const log = box.querySelector(".log");
    log.textContent = taskLines.join("\n");
    log.scrollTop = log.scrollHeight;
  }
  const busy = !!run || !!task;
  $("verify-some").disabled = busy;
  $("verify-all").disabled = busy;
  $("verify-stop").hidden = !(task && task.kind === "verify");
  updateSummary();
}

function showTaskResult(done) {
  const r = done.result;
  const box = $(`${done.kind}-result`);
  let text;
  if (done.kind === "restore") {
    text = r.status === "ok" || r.written !== undefined
      ? t("Restored {files} into {to}.", { files: plural(r.written || 0, "file"), to: r.to }) : t("The restore failed: {error}", { error: tMsg(r.error) });
    if (r.skipped_count) text += t(" {n} files were already there and skipped - tick \"Replace\" to overwrite.", { n: r.skipped_count });
    if (r.bad && r.bad.length) text += t(" {files} FAILED the check and were not written: {which}", { files: plural(r.bad.length, "file"), which: r.bad.slice(0, 5).join(", ") });
    if (r.error && r.written !== undefined) text += ` ${tMsg(r.error)}`;
  } else {
    text = r.status === "ok" ? t("All {files} in {bundles} are fine.", { files: plural(r.files, "file"), bundles: plural(r.bundles, "bundle") })
      : r.status === "cancelled" ? t("Stopped.")
      : r.problems ? t("{problems}: ", { problems: plural(r.problems.length, "problem") }) + r.problems.slice(0, 5).map((p) => `${p[0]} ${p[1]} (${p[2]})`).join("; ")
      : t("The check failed: {error}", { error: tMsg(r.error) });
  }
  box.className = `result ${r.status === "ok" ? "ok" : r.status === "cancelled" ? "cancelled" : "failed"}`;
  box.textContent = text;
  box.hidden = false;
  if (done.job === restore.job) send({ type: "browse", job: restore.job });   // last check, new versions
}

$("restore-job").onchange = () => loadRestore();
$("restore-source").onchange = () => chooseSource();
$("restore-filter").oninput = () => renderPick();
$("restore-folder").oninput = () => { document.querySelector("input[name=restore-to][value=other]").checked = true; };
$("restore-browse").onclick = async () => {
  if (!(window.pywebview && window.pywebview.api)) {
    showError(t("The folder dialog works in the app's own window - type the folder instead."));
    return;
  }
  const folder = await window.pywebview.api.pick_folder($("restore-folder").value);
  if (folder) {
    $("restore-folder").value = folder;
    document.querySelector("input[name=restore-to][value=other]").checked = true;
  }
};
$("restore-go").onclick = () => {
  const original = document.querySelector("input[name=restore-to]:checked").value === "original";
  const to = original ? "" : $("restore-folder").value.trim();
  if (!original && !/^([a-zA-Z]:\\|\\\\)/.test(to)) {
    showError(t("Choose the folder to restore into - a full path such as D:\\Restored."));
    return;
  }
  const overwrite = $("restore-overwrite").checked;
  if (overwrite && original && !confirm(t("Replace files in {folder} with their backed-up copies?\nChanges made to them since that backup will be lost.",
                                         { folder: restore.browse.source }))) return;
  $("restore-result").hidden = true;
  send({ type: "restore", job: restore.job, source: restore.source === "latest" ? "latest" : Number(restore.source),
         files: [...restore.picked], to, overwrite });
};
$("verify-some").onclick = () => { $("verify-result").hidden = true; send({ type: "verify", job: restore.job, sample: 5 }); };
$("verify-all").onclick = () => { $("verify-result").hidden = true; send({ type: "verify", job: restore.job }); };
$("verify-stop").onclick = () => send({ type: "stop" });
window.addEventListener("hashchange", showView);

// ---------- connection ----------

function send(message) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
}

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws?token=${encodeURIComponent(token)}`);
  ws.onopen = () => { $("offline").hidden = true; };
  ws.onclose = () => {
    $("offline").hidden = false;
    setTimeout(connect, 3000);
  };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "hello") {
      if (LANG !== m.lang && !connect.languageSet) setLanguage(m.lang);    // before anything is drawn
      connect.languageSet = true;
      $("version").textContent = `v${m.version}`;
      run = m.run && m.run.phase !== "done" ? m.run : null;
      lines = run ? run.lines || [] : [];
      task = m.task && m.task.phase !== "done" ? m.task : null;
      taskLines = task ? task.lines || [] : [];
      REMINDER_DAYS = m.reminder_days || 7;
      cardFolds = m.folded || {};
      showUsage(m.usage);
      // jobs added or removed on the Settings page
      const ids = new Set(m.jobs.map((j) => j.id));
      for (const [id, c] of [...cards]) {
        if (!ids.has(id)) { c.el.remove(); cards.delete(id); }
      }
      for (const select of [$("history-job"), $("restore-job")]) {
        for (const o of [...select.options]) if (!ids.has(o.value)) o.remove();
      }
      m.jobs.forEach(renderJob);
      $("welcome").hidden = m.jobs.length > 0;
      document.body.classList.toggle("no-jobs", !m.jobs.length);     // History / Restore: a note instead
      for (const select of [$("history-job"), $("restore-job")]) {     // names may have changed
        for (const o of select.options) o.textContent = m.jobs.find((j) => j.id === o.value).name;
      }
      renderRun();
      renderTask();
      showView();
      // a fresh look at what changed, unless a backup is doing that already
      if (!run) m.jobs.forEach((j) => send({ type: "check", job: j.id }));
    } else if (m.type === "job") {
      renderJob(m.job);
    } else if (m.type === "run") {
      if (m.run.phase === "done") {
        run = null;
        lines = [];
        showResult(m.run);
        if (!$("view-history").hidden && history.job === m.run.job) loadHistory();
      } else {
        if (!run || run.job !== m.run.job || run.started !== m.run.started) lines = [];
        run = m.run;
        if (m.line) lines = lines.concat(m.line.split("\n")).slice(-200);
      }
      renderRun();
      for (const { job } of cards.values()) renderJob(job);
    } else if (m.type === "preview") {
      showPreview(m);
    } else if (m.type === "history") {
      showHistory(m);
    } else if (m.type === "run_detail") {
      showRunDetail(m);
    } else if (m.type === "task") {
      if (m.task.phase === "done") {
        task = null;
        taskLines = [];
        showTaskResult(m.task);
      } else {
        if (!task || task.started !== m.task.started) taskLines = [];
        task = m.task;
        if (m.line) taskLines = taskLines.concat(m.line.split("\n")).slice(-200);
      }
      renderTask();
      for (const { job } of cards.values()) renderJob(job);
    } else if (m.type === "browse") {
      showBrowse(m);
    } else if (m.type === "version_files") {
      restore.versions.set(m.id, m.files);
      if (m.job === restore.job && restore.source === String(m.id)) setRestoreFiles(m.files);
    } else if (m.type === "usage") {
      showUsage(m.usage);
    } else if (m.type === "settings") {
      showSettings(m);
    } else if (m.type === "measure") {
      showMeasure(m);
    } else if (m.type === "saved") {
      onSaved(m);
    } else if (m.type === "key_test") {
      $("key-status").textContent = m.ok ? t("Connected - files.ir accepts the key.") : t("files.ir refused: {message}", { message: tMsg(m.message) });
      $("key-status").className = m.ok ? "good" : "bad";
    } else if (m.type === "error") {
      if (m.where && savingForm && ["save_job", "remove_job"].includes(m.where)) {
        setFormMsg(savingForm, tMsg(m.message), "bad");
        savingForm = null;
        return;
      }
      if (m.where === "set_key") { $("key-status").textContent = tMsg(m.message); $("key-status").className = "bad"; return; }
      if (m.where === "measure") {
        const f = [...forms.values()].find((x) => x._ref === m.ref);
        if (f) f.querySelector(".measure").textContent = tMsg(m.message);
        return;
      }
      showError(m.message);
      if (restore.source !== "latest" && !restore.versions.has(Number(restore.source))) {
        $("restore-tree").replaceChildren(el("div", "note", t("Could not open that version.")));
      }
    }
  };
}

setInterval(() => { for (const { job } of cards.values()) renderJob(job); }, 30000);   // "3 min ago"
connect();
