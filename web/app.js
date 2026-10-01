// ===================== J.A.R.V.I.S. HUD =====================
const $ = (s) => document.querySelector(s);
let TOKEN = localStorage.getItem("jarvis-token") || "";
let TITLE = "sir";
let state = "idle"; // idle | listening | thinking | speaking
const busy = {};    // agent -> count of running steps

// ---------- API ----------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "content-type": "application/json", "x-jarvis-token": TOKEN, ...(opts.headers || {}) },
  });
  if (res.status === 401) {
    TOKEN = prompt("Access token required:") || "";
    localStorage.setItem("jarvis-token", TOKEN);
    return api(path, opts);
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res;
}

// ---------- Boot sequence ----------
async function boot() {
  const lines = [
    "Initializing core systems .............. OK",
    "Loading neural intent router ........... OK",
    "Mounting long-term memory core ......... OK",
    "Calibrating voice synthesis ............ OK",
    "Linking research division .............. OK",
    "Linking engineering division ........... OK",
    "Linking comms division ................. OK",
    "All systems nominal.",
  ];
  const log = $("#boot-log");
  for (const l of lines) { log.textContent += l + "\n"; await sleep(140); }
  await sleep(200);
  $("#activate").hidden = false;
  $("#activate").focus();
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- Clock ----------
setInterval(() => {
  const d = new Date();
  $("#clock-time").textContent = d.toLocaleTimeString([], { hour12: false });
  $("#clock-date").textContent = d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }).toUpperCase();
}, 1000);

// ---------- Arc reactor ----------
const cv = $("#reactor"), cx = cv.getContext("2d");
let t = 0, level = 0;
function drawReactor() {
  const W = cv.width, C = W / 2;
  t += 0.016;
  const target = { idle: 0.15, listening: 0.6, thinking: 0.45, speaking: 0.5 + Math.abs(Math.sin(t * 9)) * 0.5 }[state];
  level += (target - level) * 0.08;
  const color = { idle: "63,208,255", listening: "77,255,176", thinking: "255,181,71", speaking: "63,208,255" }[state];
  cx.clearRect(0, 0, W, W);

  const g = cx.createRadialGradient(C, C, 10, C, C, 90 + level * 60);
  g.addColorStop(0, `rgba(${color},${0.55 + level * 0.4})`);
  g.addColorStop(1, `rgba(${color},0)`);
  cx.fillStyle = g; cx.beginPath(); cx.arc(C, C, 150, 0, 7); cx.fill();

  const speed = state === "thinking" ? 3 : 1;
  const ring = (r, w, segs, gap, dir, alpha) => {
    cx.strokeStyle = `rgba(${color},${alpha})`; cx.lineWidth = w;
    for (let i = 0; i < segs; i++) {
      const a = (i / segs) * Math.PI * 2 + t * dir * speed;
      cx.beginPath(); cx.arc(C, C, r, a, a + (Math.PI * 2) / segs - gap); cx.stroke();
    }
  };
  ring(178, 2, 60, 0.04, 0.1, 0.35);
  ring(160, 6, 3, 0.5, -0.4, 0.8);
  ring(140, 1, 1, 0, 0, 0.5);
  ring(125, 10, 10, 0.12, 0.6, 0.6 + level * 0.3);
  ring(100, 2, 24, 0.08, -1, 0.7);
  ring(80, 4, 6, 0.3, 1.4, 0.9);

  // spectrum
  cx.strokeStyle = `rgba(${color},0.9)`; cx.lineWidth = 2;
  for (let i = 0; i < 64; i++) {
    const a = (i / 64) * Math.PI * 2;
    const amp = 6 + level * 26 * (0.5 + 0.5 * Math.sin(i * 1.7 + t * 12)) * (state === "idle" ? 0.3 : 1);
    cx.beginPath();
    cx.moveTo(C + Math.cos(a) * 190, C + Math.sin(a) * 190);
    cx.lineTo(C + Math.cos(a) * (190 + amp), C + Math.sin(a) * (190 + amp));
    cx.stroke();
  }
  cx.fillStyle = `rgba(230,250,255,${0.85 + level * 0.15})`;
  cx.beginPath(); cx.arc(C, C, 28 + level * 10, 0, 7); cx.fill();
  requestAnimationFrame(drawReactor);
}
function setState(s) {
  state = s;
  $("#state-label").textContent = { idle: "ONLINE", listening: "LISTENING", thinking: "PROCESSING", speaking: "SPEAKING" }[s];
}

// ---------- Transcript ----------
function md(text) { return DOMPurify.sanitize(marked.parse(text || "")); }
function addMsg(role, text, id, extra = "") {
  const el = document.createElement("div");
  el.className = `msg ${role} ${extra}`;
  el.innerHTML = role === "user" ? escapeHtml(text) : md(text);
  if (role === "jarvis" && id) {
    const r = document.createElement("div");
    r.className = "rate";
    r.innerHTML = `<button title="Good reply">👍</button><button title="Not great">👎</button>`;
    r.querySelectorAll("button").forEach((b, i) => b.onclick = async () => {
      r.querySelectorAll("button").forEach((x) => x.classList.remove("picked"));
      b.classList.add("picked");
      await api("/api/feedback", { method: "POST", body: JSON.stringify({ message_id: id, score: i === 0 ? 1 : -1 }) });
    });
    el.appendChild(r);
  }
  $("#transcript").appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let pending = 0;
async function send(text) {
  text = text.trim();
  if (!text) return;
  addMsg("user", text);
  caption("user", text);
  const wait = addMsg("jarvis", "…", null, "thinking");
  pending++;
  if (!speaking) setState("thinking");
  try {
    const res = await (await api("/api/chat", { method: "POST", body: JSON.stringify({ text }) })).json();
    wait.remove();
    addMsg("jarvis", res.reply, res.message_id);
    pending--;
    speak(res.reply);
  } catch (e) {
    wait.remove();
    pending--;
    const msg = `My apologies, ${TITLE}. I've hit a fault: ${e.message}`;
    addMsg("jarvis", msg, null);
    speak(msg);
  }
}
$("#composer").onsubmit = (e) => { e.preventDefault(); send($("#input").value); $("#input").value = ""; };

// ---------- Voice out ----------
// Jarvis speaks every reply. While he talks the mic pauses (so he doesn't hear himself),
// then it opens again on its own. Tap the reactor or press Esc to cut him off.
let voice = null, audio = null, speaking = false;
const speakQueue = [];
function pickVoice() {
  const vs = speechSynthesis.getVoices();
  const prefs = ["Daniel", "Google UK English Male", "Microsoft Ryan", "Arthur", "Oliver", "Microsoft George", "Microsoft Thomas"];
  voice = prefs.map((n) => vs.find((v) => v.name.includes(n))).find(Boolean)
       || vs.find((v) => v.lang === "en-GB" && /male/i.test(v.name))
       || vs.find((v) => v.lang === "en-GB") || null;
}
if ("speechSynthesis" in window) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }

function speakable(text) {
  return text.replace(/```[\s\S]*?```/g, " (code on screen) ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/https?:\/\/\S+/g, "")
    .replace(/[#*_`>|-]/g, " ").replace(/\s+/g, " ").trim().slice(0, 900);
}
function speak(text) {
  const say = speakable(text);
  if (!say) return;
  speakQueue.push(say);
  if (!speaking) nextSpeech();
}
async function nextSpeech() {
  const say = speakQueue.shift();
  if (!say) { speaking = false; afterSpeaking(); return; }
  speaking = true;
  pauseListening();
  setState("speaking");
  caption("jarvis", say);
  try {
    const res = await api("/api/tts", { method: "POST", body: JSON.stringify({ text: say }) });
    if (res.status === 200) {
      audio = new Audio(URL.createObjectURL(await res.blob()));
      audio.onended = audio.onerror = () => { audio = null; nextSpeech(); };
      await audio.play();
      return;
    }
  } catch (_) { /* fall back to the browser voice */ }
  if (!("speechSynthesis" in window)) return nextSpeech();
  // Chrome sometimes never fires onend, so a watchdog makes sure the mic always comes back.
  let finished = false;
  const done = () => { if (!finished) { finished = true; clearTimeout(watchdog); nextSpeech(); } };
  const watchdog = setTimeout(done, 4000 + say.length * 90);
  try {
    const u = new SpeechSynthesisUtterance(say);
    if (voice) u.voice = voice;
    u.lang = "en-GB"; u.rate = 1.02; u.pitch = 0.88;
    u.onend = u.onerror = done;
    speechSynthesis.speak(u);
  } catch (_) { done(); }
}
function interrupt() {
  speakQueue.length = 0;
  if (audio) { audio.onended = null; audio.pause(); audio = null; }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  if (!speaking) return;
  speaking = false;
  afterSpeaking();
}
function afterSpeaking() {
  if (pending > 0) setState("thinking");
  else setState(micOn ? "listening" : "idle");
  resumeListening();
}
$("#reactor").onclick = interrupt;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") interrupt(); });

// ---------- Voice in ----------
// Always listening: talk normally, pause, and Jarvis answers. Optional wake-word mode
// only reacts to sentences that contain "Jarvis".
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, micOn = false;
function startRec() {
  if (!SR || !micOn || speaking || rec) return;
  rec = new SR();
  rec.lang = "en-GB"; rec.continuous = true; rec.interimResults = true;
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const s = e.results[i][0].transcript;
      if (e.results[i].isFinal) heard(s);
      else interim += s;
    }
    if (interim) caption("user", interim, true);
  };
  rec.onend = () => { rec = null; if (micOn && !speaking) setTimeout(startRec, 250); };
  rec.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      setMic(false);
      caption("jarvis", "I can't access the microphone. Please allow it in the browser and tap the mic.");
    }
  };
  try { rec.start(); } catch (_) { rec = null; }
}
function pauseListening() { if (rec) { const r = rec; rec = null; r.onend = null; r.abort(); } }
function resumeListening() { startRec(); }
function heard(text) {
  text = text.trim();
  if (!text) return;
  if ($("#mode").value === "wake") {
    const m = text.match(/\bjarvis\b[,.!?]?\s*(.*)/i);
    if (!m) return caption("user", text + "  (ignored – say “Jarvis” first)", true);
    text = m[1].trim();
    if (!text) return speak(`Yes, ${TITLE}?`);
  } else {
    text = text.replace(/^(hey |ok |okay )?jarvis[,.!?]?\s*/i, "") || text;
  }
  if (/^(stop|quiet|shut up|never ?mind|cancel)\.?$/i.test(text)) return interrupt();
  send(text);
}
function setMic(on) {
  micOn = on && !!SR;
  $("#mic").classList.toggle("live", micOn);
  $("#mic").title = micOn ? "Listening – click to mute" : "Muted – click to listen";
  if (micOn) { startRec(); if (!speaking && !pending) setState("listening"); }
  else { pauseListening(); if (!speaking && !pending) setState("idle"); }
}
$("#mic").onclick = () => setMic(!micOn);

// ---------- Live caption ----------
let captionTimer = null;
function caption(who, text, interim = false) {
  const el = $("#caption");
  el.className = `${who} ${interim ? "interim" : ""}`;
  el.textContent = text;
  clearTimeout(captionTimer);
  if (who === "user" && !interim) captionTimer = setTimeout(() => (el.textContent = ""), 4000);
}

// ---------- Activate (browsers need one click before using mic + audio) ----------
function activate() {
  $("#boot").classList.add("done");
  if (!SR) {
    caption("jarvis", "Voice input needs Chrome or Edge. You can still type.");
  }
  const h = new Date().getHours();
  const greet = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  setMic(true);
  speak(`${greet}, ${TITLE}. All systems are online. I'm listening.`);
}

// ---------- Activity stream ----------
const AGENT_NAMES = { core: "core", research: "research", code: "engineer", comms: "comms", memory: "memory", router: "router" };
function logEvent(ev) {
  const line = describe(ev);
  if (!line) return;
  const el = document.createElement("div");
  el.className = `ev a-${ev.agent} ${line.err ? "err" : ""}`;
  const time = new Date(ev.ts * 1000).toLocaleTimeString([], { hour12: false });
  el.innerHTML = `<time>${time}</time><span class="a">${AGENT_NAMES[ev.agent] || ev.agent}</span>${line.html}` +
    (line.detail ? `<span class="d">${line.detail}</span>` : "");
  const log = $("#activity");
  log.appendChild(el);
  while (log.children.length > 250) log.firstChild.remove();
  log.scrollTop = log.scrollHeight;
}
function describe(ev) {
  const e = escapeHtml, j = (o) => e(JSON.stringify(o)).slice(0, 220);
  switch (ev.kind) {
    case "user_said": return { html: `heard: “${e(ev.text.slice(0, 120))}”` };
    case "agent_start": return { html: "spinning up" + (ev.task_id ? ` (task #${ev.task_id})` : "") };
    case "agent_done": return { html: "finished" };
    case "agent_error": return { html: `fault: ${e(ev.error)}`, err: true };
    case "narration": return { html: e(ev.text.slice(0, 240)) };
    case "tool_call":
      if (ev.tool === "web_search") return { html: `🔎 searching <b>${e(ev.input.query || "")}</b>` };
      if (ev.tool === "web_fetch") return { html: `📄 reading ${e(ev.input.url || "")}` };
      return { html: `⚙ ${e(ev.tool)}`, detail: j(ev.input) };
    case "tool_result":
      if (ev.items) return { html: `↳ ${e(ev.summary)}`, detail: ev.items.map((i) => `· <a href="${e(i.url)}" target="_blank" rel="noopener">${e(i.title || i.url)}</a>`).join("\n") };
      return { html: `↳ ${e(ev.tool)} ${ev.error ? "failed" : "ok"}`, detail: e((ev.summary || "").slice(0, 200)), err: ev.error };
    case "route": return { html: `intent → <b>${ev.label}</b> (${Math.round(ev.confidence * 100)}%)` };
    case "router_learned": return { html: `retrained on “${ev.label}” · ${ev.n} samples` };
    case "recall": return { html: `recalled ${ev.items.length} memories`, detail: ev.items.map((i) => `· ${e(i.text)} (${i.score})`).join("\n") };
    case "learned": return { html: `learned ${ev.items.length} thing(s)`, detail: ev.items.map((i) => `· ${e(i.key)} = ${e(i.value)}`).join("\n") };
    case "forgot": return { html: `forgot ${e(ev.key)}` };
    case "style_learned": return { html: `style model updated (${ev.n} ratings)` };
    case "task_start": return { html: `▶ task #${ev.task_id}: ${e(ev.label)}` };
    case "task_done": return { html: `✔ task #${ev.task_id} complete` };
    case "task_failed": return { html: `✖ task #${ev.task_id} failed: ${e(ev.error)}`, err: true };
    case "file_written": return { html: `✎ wrote ${e(ev.path)} (${ev.bytes} chars)` };
    case "comms_in": return { html: `${ev.medium === "call" ? "📞" : "💬"} ${e(ev.contact)}: “${e(ev.text.slice(0, 120))}”` };
    case "comms_out": return { html: `${ev.simulated ? "(sim) " : ""}→ ${e(ev.contact)}: “${e(ev.text.slice(0, 120))}”` };
    case "comms_draft": return { html: `drafted reply to ${e(String(ev.contact))} — awaiting approval` };
    case "call_summary": return { html: `call with ${e(ev.contact)} ended`, detail: e(ev.summary) };
  }
  return null;
}

// ---------- Agent matrix ----------
function agentEvent(ev) {
  const card = document.querySelector(`.agent[data-agent="${ev.agent}"]`);
  if (!card) return;
  const em = card.querySelector("em");
  if (ev.kind === "agent_start") { busy[ev.agent] = (busy[ev.agent] || 0) + 1; card.classList.remove("err"); }
  if (ev.kind === "agent_done") busy[ev.agent] = Math.max(0, (busy[ev.agent] || 1) - 1);
  if (ev.kind === "agent_error") { busy[ev.agent] = Math.max(0, (busy[ev.agent] || 1) - 1); card.classList.add("err"); }
  const d = describe(ev);
  if (d) em.innerHTML = d.html.replace(/<[^>]+>/g, "");
  card.classList.toggle("busy", (busy[ev.agent] || 0) > 0 || ["learned", "recall", "comms_in"].includes(ev.kind));
  if (!busy[ev.agent] && ["agent_done", "agent_error"].includes(ev.kind)) setTimeout(() => { if (!busy[ev.agent]) em.textContent = "Standing by"; }, 6000);
  if (["learned", "recall", "comms_in"].includes(ev.kind)) setTimeout(() => !busy[ev.agent] && card.classList.remove("busy"), 1500);
}

// ---------- Router ----------
function renderRouter(probs, label) {
  $("#router-bars").innerHTML = Object.entries(probs).map(([k, v]) =>
    `<div class="bar ${k === label ? "top" : ""}"><span>${k}</span><div class="track"><div class="fill" style="width:${v * 100}%"></div></div><span>${Math.round(v * 100)}%</span></div>`).join("");
}

// ---------- Panels ----------
function renderPrefs(prefs, fresh = []) {
  $("#mem-n").textContent = `${prefs.length} facts`;
  if (!prefs.length) return;
  $("#prefs").innerHTML = prefs.map((p) => `
    <div class="pref ${fresh.includes(p.key) ? "new" : ""}">
      <span class="v">${escapeHtml(p.value)}</span>
      <span class="k">${escapeHtml(p.category)} · ${escapeHtml(p.key)}</span>
      <button title="Forget" data-k="${escapeHtml(p.key)}">✕</button>
      <div class="conf"><div style="width:${Math.round((p.score ?? p.confidence) * 100)}%"></div></div>
    </div>`).join("");
  $("#prefs").querySelectorAll("button").forEach((b) => b.onclick = async () => {
    await api(`/api/preferences/${encodeURIComponent(b.dataset.k)}`, { method: "DELETE" }); refresh();
  });
}
function renderStyle(style) {
  const w = style.weights || {};
  const keys = Object.keys(w);
  $("#style-learned").textContent = keys.length
    ? "style model: " + keys.map((k) => `${k} ${w[k] > 0 ? "+" : ""}${w[k]}`).join(" · ")
    : `style model: needs ${Math.max(0, 4 - (style.n || 0))} more 👍/👎`;
}
function renderTasks(tasks) {
  if (!tasks.length) return;
  $("#tasks").innerHTML = tasks.slice().reverse().map((t) => `
    <div class="task ${t.status}"><div class="k"><span>#${t.id} ${t.kind.toUpperCase()}</span><b>${t.status.toUpperCase()}</b></div>${escapeHtml(t.label)}</div>`).join("");
}
function renderComms(rows, mode) {
  $("#comms-mode").textContent = mode === "auto" ? "auto-reply" : "approval mode";
  if (!rows.length) return;
  $("#comms").innerHTML = rows.map((r) => `
    <div class="comm">
      <div class="who"><span>${r.kind === "call" ? "📞" : "💬"} ${escapeHtml(r.contact)}</span><span>${r.status}</span></div>
      ${r.incoming && r.kind !== "call" ? `<div class="in">“${escapeHtml(r.incoming.slice(0, 200))}”</div>` : ""}
      ${r.status === "pending"
        ? `<textarea rows="2" data-id="${r.id}">${escapeHtml(r.draft || "")}</textarea>
           <div class="acts"><button data-ok="${r.id}">SEND</button><button class="no" data-no="${r.id}">DISMISS</button></div>`
        : `<div>${escapeHtml(r.draft || "")}</div>`}
    </div>`).join("");
  $("#comms").querySelectorAll("[data-ok]").forEach((b) => b.onclick = async () => {
    const text = $(`#comms textarea[data-id="${b.dataset.ok}"]`).value;
    try { await api("/api/comms/approve", { method: "POST", body: JSON.stringify({ id: +b.dataset.ok, text }) }); }
    catch (e) { alert(e.message); }
    refresh();
  });
  $("#comms").querySelectorAll("[data-no]").forEach((b) => b.onclick = async () => {
    await api("/api/comms/reject", { method: "POST", body: JSON.stringify({ id: +b.dataset.no }) }); refresh();
  });
}
function renderFiles(files, fresh) {
  if (!files.length) return;
  $("#files").innerHTML = files.map((f) => `<div class="file ${f === fresh ? "new" : ""}" data-f="${escapeHtml(f)}">▸ ${escapeHtml(f)}</div>`).join("");
  $("#files").querySelectorAll(".file").forEach((el) => el.onclick = async () => {
    const r = await (await api(`/api/file?path=${encodeURIComponent(el.dataset.f)}`)).json();
    $("#viewer-title").textContent = r.path; $("#viewer-body").textContent = r.content; $("#viewer").showModal();
  });
}
function pill(id, on, warn) { const p = $(id); p.classList.toggle("on", !!on); p.classList.toggle("warn", !!warn); }

let refreshTimer = null;
function refreshSoon(ms = 400) { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, ms); }
async function refresh(first = false, freshPrefs = [], freshFile = null) {
  const s = await (await api("/api/state")).json();
  TITLE = s.user_title || "sir";
  pill("#pill-voice", true, s.voice === "browser");
  $("#pill-voice").lastChild.textContent = s.voice === "browser" ? "VOICE · BROWSER" : "VOICE · ELEVENLABS";
  pill("#pill-comms", s.twilio, !s.twilio);
  $("#pill-comms").lastChild.textContent = s.twilio ? "COMMS · TWILIO" : "COMMS · SIM";
  pill("#pill-exec", s.exec, !s.exec);
  $("#router-n").textContent = `${s.router.trained_on} samples · ${s.memory_size} memories`;
  renderPrefs(s.preferences, freshPrefs);
  renderStyle(s.style);
  renderTasks(s.tasks);
  renderComms(s.comms, s.comms_mode);
  renderFiles(s.files, freshFile);
  if (first) {
    s.messages.forEach((m) => addMsg(m.role === "user" ? "user" : "jarvis", m.content, m.role === "user" ? null : m.id, m.content.startsWith("[") ? "task" : ""));
    s.events.forEach(logEvent);
    const lastRoute = s.events.filter((e) => e.kind === "route").pop();
    renderRouter(lastRoute ? lastRoute.probs : { chat: 0.25, research: 0.25, code: 0.25, comms: 0.25 }, lastRoute && lastRoute.label);
  }
}

// ---------- Live link ----------
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(TOKEN)}`);
  ws.onopen = () => pill("#pill-link", true);
  ws.onclose = () => { pill("#pill-link", false, true); setTimeout(connect, 2000); };
  ws.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    logEvent(ev); agentEvent(ev);
    if (ev.kind === "route") { renderRouter(ev.probs, ev.label); }
    if (ev.kind === "router_learned") $("#router-n").textContent = `${ev.n} samples`;
    if (ev.kind === "learned") refresh(false, ev.items.map((i) => i.key));
    if (ev.kind === "file_written") refresh(false, [], ev.path);
    if (["task_start", "task_done", "task_failed", "comms_draft", "comms_out", "call_summary", "forgot", "style_learned"].includes(ev.kind)) refreshSoon();
    if (ev.kind === "task_done") {
      addMsg("jarvis", `**${ev.agent === "code" ? "Engineering" : "Research"} task #${ev.task_id} complete** — ${ev.label}\n\n${ev.result}`, null, "task");
      speak(ev.agent === "code"
        ? `${cap(TITLE)}, the engineering division has finished. The build is in your workspace.`
        : `${cap(TITLE)}, the research is in. ${firstSentence(ev.result)}`);
    }
    if (ev.kind === "task_failed") speak(`I'm afraid task ${ev.task_id} has failed, ${TITLE}.`);
    if (ev.kind === "comms_draft") speak(`${cap(TITLE)}, I've drafted a reply to a message. It's awaiting your approval.`);
    if (ev.kind === "call_summary") speak(`${cap(TITLE)}, you had a call. ${ev.summary}`);
  };
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const firstSentence = (s) => (speakable(s).match(/^.*?[.!?](\s|$)/) || [""])[0];

// ---------- Go ----------
drawReactor();
boot();
$("#activate").onclick = activate;
refresh(true).then(connect).catch((e) => addMsg("jarvis", `Unable to reach the core: ${e.message}`));
