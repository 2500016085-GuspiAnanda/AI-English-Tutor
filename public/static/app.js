// =====================================================================
// Ikon: SVG garis sederhana yang senada dengan wajah tutor (bukan emoji)
// =====================================================================
const svg = (body) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
const ICON = {
  mic: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>'),
  speakerOn: svg('<path d="M4 9.5h3.5L12 6v12l-4.5-3.5H4z"/><path d="M15.5 9.5a3.5 3.5 0 0 1 0 5M18 7a7 7 0 0 1 0 10"/>'),
  speakerOff: svg('<path d="M4 9.5h3.5L12 6v12l-4.5-3.5H4z"/><path d="M16 10l4.5 4.5M20.5 10L16 14.5"/>'),
  chat: svg('<path d="M4 5.5h16v10.5H9.5L5 19.5V16H4z"/>'),
  face: svg('<path d="M6 5h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/><path d="M9.5 10.5v.5M14.5 10.5v.5M9.5 15h5"/>'),
  notes: svg('<path d="M6 3.5h9l3.5 3.5v13.5H6z"/><path d="M9 10h6.5M9 13.5h6.5M9 17h3.5"/>'),
  check: svg('<path d="M5 12.5l4.5 4.5L19 7"/>'),
  warn: svg('<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.3"/>'),
};

// =====================================================================
// State aplikasi: apa yang perlu diingat browser selama halaman terbuka
// =====================================================================
const state = { user: null, sessionId: null, sessionOpen: false, busy: false, screen: "login", header: "", lastUserBubble: null };
const $ = (id) => document.getElementById(id);

function load(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } }
function save(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch {} }

function notice(id, text) { $(id).innerHTML = text ? `${ICON.warn}<span>${escapeHtml(text)}</span>` : ""; }

// =====================================================================
// api(): satu pintu untuk semua request ke server (mirip call_llm di Python)
// =====================================================================
async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;   // 422 dari Pydantic berupa daftar error; selain itu berupa teks
    throw new Error(Array.isArray(d) ? d.map((e) => e.msg).join("; ") : d || `Error ${res.status}`);
  }
  return data;
}

// =====================================================================
// Layar & mode tampilan
// =====================================================================
state.mode = load("mode", "suara");   // "suara" (wajah + tahan-untuk-bicara) atau "chat" (balon chat)

function show(screen) {
  state.screen = screen;
  for (const s of ["login", "placement", "home", "chat"]) $(`screen-${s}`).classList.toggle("hidden", s !== screen);
  refreshLayout();
}

function refreshLayout() {
  const inChat = state.screen === "chat", voice = state.mode === "suara";
  $("stage").classList.toggle("hidden", !voice);
  $("messages").classList.toggle("hidden", voice);
  $("stage-controls").classList.toggle("hidden", !state.sessionOpen);
  const composer = inChat && !voice && state.sessionOpen;
  $("composer").classList.toggle("hidden", !composer);
  document.body.classList.toggle("composer-open", composer);
  $("btn-mode").innerHTML = voice ? `${ICON.chat}<span>Mode chat</span>` : `${ICON.face}<span>Mode suara</span>`;
  $("btn-end").disabled = !state.sessionOpen || state.busy;
}

$("btn-mode").addEventListener("click", () => {
  state.mode = state.mode === "suara" ? "chat" : "suara";
  save("mode", state.mode);
  refreshLayout();
  $("messages").lastElementChild?.scrollIntoView({ block: "end" });
});

// =====================================================================
// Markdown mini untuk balasan tutor (**tebal**, *miring*, daftar, kutipan).
// Teks di-escape DULU agar HTML dari luar tidak pernah dijalankan (cegah XSS).
// =====================================================================
function escapeHtml(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function inline(s) {
  return escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*\s][^*]*?)\*/g, "<em>$1</em>")
    .replace(/(^|\s)_([^_]+?)_(?=\s|$|[.,!?:;])/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}
function markdown(src) {
  const out = []; let para = []; let list = null;
  const flushPara = () => { if (para.length) { out.push(`<p>${para.join("<br>")}</p>`); para = []; } };
  const flushList = () => {
    if (!list) return;
    const start = list.start > 1 ? ` start="${list.start}"` : "";  // daftar bernomor yang terpotong paragraf tetap lanjut nomornya
    out.push(`<${list.tag}${start}>${list.items.map((i) => `<li>${i}</li>`).join("")}</${list.tag}>`);
    list = null;
  };
  const addItem = (tag, text, start = 1) => {
    flushPara();
    if (!list || list.tag !== tag) { flushList(); list = { tag, start, items: [] }; }
    list.items.push(inline(text));
  };
  for (const raw of src.split("\n")) {
    const line = raw.trimEnd(); let m;
    if ((m = line.match(/^\s*[-*]\s+(.*)/))) addItem("ul", m[1]);
    else if ((m = line.match(/^\s*(\d+)[.)]\s+(.*)/))) addItem("ol", m[2], Number(m[1]));
    else if ((m = line.match(/^>\s?(.*)/))) { flushPara(); flushList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); }
    else if ((m = line.match(/^#{1,6}\s+(.*)/))) { flushPara(); flushList(); out.push(`<p><strong>${inline(m[1])}</strong></p>`); }
    else if (!line.trim()) { flushPara(); flushList(); }
    else { flushList(); para.push(inline(line)); }
  }
  flushPara(); flushList();
  return out.join("");
}

// =====================================================================
// Layar 1: Masuk
// =====================================================================
async function login(username) {
  state.user = await api("/api/login", { username });
  save("username", state.user.username);
  $("who").textContent = state.user.username;
  if (state.user.sudah_tes) await showHome(); else showPlacement();
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();  // cegah form memuat ulang halaman
  notice("login-error", "");
  try { await login($("username").value.trim()); }
  catch (err) { notice("login-error", err.message); }
});

// =====================================================================
// Layar 2: Tes penempatan
// =====================================================================
function showPlacement() {
  $("placement-intro").classList.remove("hidden");
  $("placement-form").classList.add("hidden");
  $("placement-result").classList.add("hidden");
  notice("placement-error", "");
  show("placement");
}

$("btn-take-test").addEventListener("click", async () => {
  try {
    const questions = await api("/api/placement/questions");
    $("questions").innerHTML = questions.map((q) => `
      <fieldset class="question">
        <legend>${q.no}. ${escapeHtml(q.soal)}</legend>
        <div class="opts">${Object.entries(q.opsi).map(([letter, text]) => `
          <label><input type="radio" name="q${q.no}" value="${letter}" required>
                 <span class="letter">${letter}</span><span>${escapeHtml(text)}</span></label>
        `).join("")}</div>
      </fieldset>`).join("");
    $("placement-intro").classList.add("hidden");
    $("placement-form").classList.remove("hidden");
    $("questions").querySelector("input")?.focus();
  } catch (err) { notice("placement-error", err.message); }
});

$("placement-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const answers = [1, 2, 3, 4, 5].map((n) => document.querySelector(`input[name=q${n}]:checked`)?.value);
  if (answers.includes(undefined)) { notice("placement-error", "Masih ada soal yang belum dijawab."); return; }
  await submitPlacement(answers);
});

$("btn-skip-test").addEventListener("click", () => submitPlacement(null));

async function submitPlacement(answers) {
  notice("placement-error", "");
  try {
    const r = await api("/api/placement", { user_id: state.user.id, answers });
    state.user.level = r.level; state.user.sudah_tes = true;
    $("placement-result-text").textContent = r.skor === null
      ? "Oke, kita mulai dari level pemula."
      : `Skor kamu ${r.skor}/5. Kamu masuk level ${r.level}.`;
    $("placement-intro").classList.add("hidden");
    $("placement-form").classList.add("hidden");
    $("placement-result").classList.remove("hidden");
    $("btn-to-home").focus();
  } catch (err) { notice("placement-error", err.message); }
}

$("btn-to-home").addEventListener("click", () => showHome());

// =====================================================================
// Layar 3: Beranda
// =====================================================================
async function showHome() {
  stopSpeaking(); cancelPtt();
  state.user = await api("/api/login", { username: state.user.username });  // segarkan jumlah sesi hari ini
  const u = state.user, full = u.sesi_hari_ini >= u.batas_sesi;
  const boxes = Array.from({ length: u.batas_sesi }, (_, i) =>
    i < u.sesi_hari_ini ? `<span class="used">${ICON.check}</span>` : "<span></span>").join("");
  $("home-greeting").textContent = `Halo, ${u.username}.`;
  $("home-info").innerHTML = `Level <strong>${escapeHtml(u.level)}</strong> · Sesi hari ini
    <span class="quota" role="img" aria-label="${u.sesi_hari_ini} dari ${u.batas_sesi} sesi terpakai">${boxes}</span>`;
  state.persona = u.persona_default || "galak";
  document.querySelector(`input[name=persona][value=${state.persona}]`).checked = true;
  $("persona-status").textContent = "";
  $("btn-start").disabled = full;
  notice("home-error", full ? "Jatah 3 sesi hari ini sudah habis. Besok bisa lanjut lagi." : "");
  show("home");
}

// Gaya mentor disimpan begitu dipilih; berlaku mulai sesi berikutnya
for (const radio of document.querySelectorAll("input[name=persona]")) {
  radio.addEventListener("change", async () => {
    try {
      const r = await api("/api/persona", { user_id: state.user.id, persona: radio.value });
      state.persona = state.user.persona_default = r.persona;
      $("persona-status").textContent = `Tersimpan. Sesi berikutnya pakai gaya ${r.persona}.`;
    } catch (err) { $("persona-status").textContent = err.message; }
  });
}

$("btn-logout").addEventListener("click", () => {
  state.user = null; save("username", null); $("username").value = ""; $("who").textContent = ""; show("login");
});

// =====================================================================
// Wajah tutor: mood = hasil giliran terakhir (dari tool yang dipanggil agen),
// activity = apa yang sedang terjadi sekarang (mendengar / berpikir / berbicara)
// =====================================================================
function setMood(mood) { $("face").dataset.mood = mood || "netral"; }
function setActivity(activity) { $("face").dataset.activity = activity; }

// kind: "" biasa · "rec" sedang merekam (titik merah) · "warn" peringatan
function liveText(text, kind = "") {
  for (const id of ["live", "live2"]) { $(id).textContent = text; $(id).className = `live ${kind}`; }
}

// =====================================================================
// Suara keluar (TTS): balasan tutor dibacakan
// =====================================================================
const canSpeak = "speechSynthesis" in window;
let ttsOn = load("tts", "on") !== "off";
let voices = [];

// Kata umum bahasa Indonesia untuk menebak bahasa tiap kalimat (balasan pemula bercampur dua bahasa)
const ID_WORDS = new Set(("yang dan ini itu kamu kau aku saya tidak bukan dengan untuk ya sudah belum coba kita " +
  "pakai harus jangan lagi juga ada kalau karena atau tapi tetapi bisa sekarang dulu nah oke bagus benar salah " +
  "kalimat jadi supaya agar sama seperti dari pada akan masih sangat lebih giliranmu ingat artinya contoh " +
  "contohnya jawab jawaban perhatikan sesi kesalahan selamat sampai jumpa tulis ulangi lanjut mau apa").split(" "));

function guessLang(sentence) {
  const words = sentence.toLowerCase().match(/[a-z']+/g) || [];
  const indo = words.filter((w) => ID_WORDS.has(w)).length;
  return indo >= Math.max(1, words.length * 0.15) ? "id-ID" : "en-US";
}

function toSentences(markdownText) {
  const plain = markdownText
    .replace(/\p{Extended_Pictographic}|️/gu, "")    // emoji tidak dibacakan
    .replace(/[*_`#]/g, "")                                // simbol markdown
    .replace(/^\s*(>|[-*]|\d+[.)])\s+/gm, "")              // penanda kutipan dan daftar
    .replace(/\s*(→|->)\s*/g, ", ");                      // panah koreksi jadi jeda
  // Pecah di akhir kalimat dan setelah titik dua ("Coba jawab: Where are you from?" -> 2 bagian, 2 bahasa)
  return plain.split(/(?<=[.!?:])\s+|\n+/).map((s) => s.trim()).filter((s) => /[a-z0-9]/i.test(s));
}

function voiceFor(lang) {
  return voices.find((v) => v.lang.replace("_", "-") === lang) || voices.find((v) => v.lang.startsWith(lang.slice(0, 2)));
}

// Nada suara = ekspresi giliran itu × gaya mentor. Catatan: sebagian suara online (Google, Microsoft
// "Natural") mengabaikan pitch; kecepatan (rate) tetap berpengaruh di semua suara.
const TONE = {
  marah:   { rate: 1.08, pitch: 0.82, volume: 1 },     // galak + salah: tegas, sedikit cepat, nada rendah
  koreksi: { rate: 0.95, pitch: 1.0,  volume: 0.9 },   // lembut + salah: tenang dan pelan
  senang:  { rate: 0.96, pitch: 1.12, volume: 0.95 },  // benar: ringan dan ceria
  netral:  { rate: 0.98, pitch: 1.0,  volume: 1 },
};
const PERSONA_TONE = { galak: { rate: 1, pitch: 0.95, volume: 1 }, lembut: { rate: 0.95, pitch: 1.05, volume: 0.9 } };

function tone(lang, mood, persona) {
  const m = TONE[mood] || TONE.netral, p = PERSONA_TONE[persona] || PERSONA_TONE.galak;
  const enSlow = lang === "en-US" ? 0.95 : 1;   // bahasa Inggris sedikit diperlambat agar mudah ditangkap
  return {
    rate: Math.min(1.5, Math.max(0.6, m.rate * p.rate * enSlow)),
    pitch: Math.min(2, Math.max(0, m.pitch * p.pitch)),
    volume: Math.min(1, m.volume * p.volume),
  };
}

let speakToken = 0;   // naik setiap kali ucapan dibatalkan/diganti, agar timer lama tidak ikut berbicara

function stopSpeaking() {
  speakToken++;
  if (canSpeak && (speechSynthesis.speaking || speechSynthesis.pending)) speechSynthesis.cancel();
}

// Dibacakan per kalimat: bahasa bisa berganti, dan Chrome kadang memotong ucapan yang terlalu panjang.
// useChosenVoice=false -> biarkan browser memilih suara sendiri (dipakai saat percobaan kedua).
function speakSentences(sentences, token, useChosenVoice, hooks) {
  const attempt = { started: false, failed: null };
  speechSynthesis.resume();   // pulihkan mesin suara yang "macet" dalam keadaan pause (bug Chrome/Edge)
  sentences.forEach((sentence, i) => {
    const u = new SpeechSynthesisUtterance(sentence);
    u.lang = guessLang(sentence);
    const voice = useChosenVoice ? voiceFor(u.lang) : null;
    if (voice) u.voice = voice;
    Object.assign(u, tone(u.lang, hooks.mood, hooks.persona));   // nada ikut ekspresi & gaya mentor
    u.onstart = () => {
      if (token !== speakToken || attempt.started) return;
      attempt.started = true;
      hooks.onStart?.();
    };
    if (i === sentences.length - 1) u.onend = () => { if (token === speakToken) hooks.onEnd?.(); };
    u.onerror = (e) => {
      if (["interrupted", "canceled"].includes(e.error) || token !== speakToken) return;  // dibatalkan sengaja
      attempt.failed ??= e.error;
      console.warn("TTS error:", e.error, voice?.name || "(suara bawaan)", sentence);
    };
    speechSynthesis.speak(u);
  });
  return attempt;
}

// hooks.onStart: dipanggil saat suara benar-benar mulai (untuk info kecepatan)
function speak(text, hooks = {}) {
  if (!canSpeak) return;
  stopSpeaking();
  const token = speakToken;
  const sentences = toSentences(text);
  if (!sentences.length) return;
  const wrapped = {
    mood: hooks.mood, persona: state.persona,
    onStart: () => { setActivity("speaking"); hooks.onStart?.(); },
    onEnd: () => setActivity("idle"),
  };

  // Jeda singkat setelah cancel(): Chrome/Edge kadang membuang ucapan yang langsung dikirim setelahnya
  setTimeout(() => {
    if (token !== speakToken) return;
    const first = speakSentences(sentences, token, true, wrapped);

    // Pengaman: 4 detik tanpa suara -> ulangi dengan suara bawaan browser; gagal lagi -> beri tahu pengguna
    setTimeout(() => {
      if (token !== speakToken || first.started) return;
      speechSynthesis.cancel();
      const second = speakSentences(sentences, token, false, wrapped);
      setTimeout(() => {
        if (token !== speakToken || second.started) return;
        setActivity("idle");
        const reason = second.failed || first.failed || "tidak ada suara";
        liveText(`Suara tutor gagal diputar (${reason}). Cek volume dan output suara Windows, lalu tekan Putar ulang.`, "warn");
      }, 4000);
    }, 4000);
  }, 150);
}

function renderTtsButton() {
  $("btn-tts").innerHTML = ttsOn ? `${ICON.speakerOn}<span>Suara</span>` : `${ICON.speakerOff}<span>Bisu</span>`;
  $("btn-tts").setAttribute("aria-pressed", String(ttsOn));
  $("btn-tts").title = ttsOn ? "Suara tutor menyala. Tekan untuk membisukan." : "Suara tutor mati. Tekan untuk menyalakan.";
}

$("btn-tts").addEventListener("click", () => {
  ttsOn = !ttsOn;
  save("tts", ttsOn ? "on" : "off");
  if (!ttsOn) { stopSpeaking(); setActivity("idle"); }
  renderTtsButton();
});

if (canSpeak) {
  voices = speechSynthesis.getVoices();
  speechSynthesis.onvoiceschanged = () => { voices = speechSynthesis.getVoices(); };  // Chrome memuat daftar suara belakangan
} else {
  $("btn-tts").classList.add("hidden");
}

// =====================================================================
// Suara masuk (STT): TAHAN tombol / spasi untuk bicara, LEPAS untuk mengirim
// =====================================================================
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;  // Chrome/Edge pakai awalan webkit
// wantListening = keinginan PENGGUNA (tombol sedang ditahan);
// listening     = kondisi BROWSER (bisa berhenti sendiri walau tombol masih ditahan)
let recognizer = null, wantListening = false, listening = false, micError = false;
let heardText = "", sendOnEnd = false, pressedAt = 0, releasedAt = 0;

const MIC_ERRORS = {
  "not-allowed": "Akses mikrofon ditolak. Klik ikon di kiri address bar, lalu izinkan mikrofon.",
  "no-speech": "Tidak terdengar suara. Tahan tombol sambil bicara, lalu lepas.",
  "audio-capture": "Mikrofon tidak ditemukan.",
  "network": "Layanan pengenal suara tidak bisa dihubungi. Pakai Google Chrome atau Microsoft Edge asli " +
             "(Brave, Opera, dan browser bawaan editor tidak didukung), dan pastikan internet/VPN tidak memblokir.",
};

function setPttUi(on) {
  for (const id of ["btn-ptt", "btn-ptt2"]) {
    $(id).classList.toggle("listening", on);
    $(id).setAttribute("aria-pressed", String(on));
  }
}

function setupMic() {
  for (const id of ["btn-ptt", "btn-ptt2"]) $(id).innerHTML = ICON.mic;
  if (!Recognition) {
    for (const id of ["btn-ptt", "btn-ptt2"]) $(id).disabled = true;
    liveText("Browser ini belum mendukung input suara. Pakai Chrome atau Edge, atau ketik jawabanmu.", "warn");
    return;
  }
  recognizer = new Recognition();
  recognizer.lang = "en-US";          // yang dilatih adalah bahasa Inggris
  recognizer.interimResults = true;   // teks muncul bertahap selagi pengguna bicara
  recognizer.continuous = true;       // tetap mendengar walau pengguna jeda untuk berpikir
  let before = "";                    // teks dari potongan sebelumnya (bila mic menyala ulang)

  recognizer.onstart = () => {
    listening = true;
    if (!wantListening) { recognizer.stop(); return; }  // tombol sudah dilepas sebelum mic sempat menyala
    before = heardText ? heardText + " " : "";
  };
  recognizer.onresult = (e) => {
    let heard = "";
    for (const result of e.results) heard += result[0].transcript;  // [0] = tebakan terbaik
    heardText = (before + heard).trim();
    liveText(heardText, "rec");
  };
  recognizer.onerror = (e) => {
    if (e.error === "aborted") return;
    micError = true;   // error = jangan dinyalakan ulang otomatis (cegah loop tanpa akhir)
    liveText(MIC_ERRORS[e.error] || `Input suara gagal (${e.error}).`, "warn");
  };
  recognizer.onend = () => {
    listening = false;
    // Chrome bisa menghentikan mic sendiri walau tombol masih ditahan: nyalakan ulang, teks lama disimpan
    if (wantListening && !micError) {
      try { recognizer.start(); return; } catch { /* gagal menyala ulang: anggap selesai */ }
    }
    finishPtt();
  };
}

function pttDown() {
  if (!recognizer || state.busy || !state.sessionOpen || wantListening) return;
  stopSpeaking();                    // jangan sampai suara tutor ikut terekam
  heardText = ""; sendOnEnd = false; micError = false;
  wantListening = true; pressedAt = performance.now();
  setPttUi(true); setActivity("listening"); liveText("Mendengarkan...", "rec");
  try { recognizer.start(); } catch { /* sudah dalam proses menyala */ }
}

function pttUp() {
  if (!wantListening) return;
  wantListening = false; releasedAt = performance.now();
  if (releasedAt - pressedAt < 350) {          // cuma diketuk, bukan ditahan
    sendOnEnd = false;
    liveText("Tahan tombolnya selama kamu bicara, lalu lepas untuk mengirim.");
    if (listening) recognizer.abort(); else finishPtt();
    return;
  }
  sendOnEnd = true;
  if (listening) recognizer.stop(); else finishPtt();   // stop() -> hasil akhir dikirim -> onend -> finishPtt
}

function cancelPtt() { wantListening = false; sendOnEnd = false; if (listening) recognizer?.abort(); setPttUi(false); }

function finishPtt() {
  setPttUi(false);
  if (!sendOnEnd || micError) { if (!state.busy) setActivity("idle"); sendOnEnd = false; return; }
  sendOnEnd = false;
  const text = heardText.trim();
  if (!text) { setActivity("idle"); liveText("Tidak terdengar apa-apa. Coba lagi lebih dekat ke mikrofon.", "warn"); return; }
  liveText("");
  sendText(text, performance.now() - releasedAt);   // waktu "dengar" = dari tombol dilepas sampai teks final
}

function bindPtt(btn) {
  btn.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    try { btn.setPointerCapture(e.pointerId); } catch { /* pointerup tetap diterima walau jari bergeser */ }
    pttDown();
  });
  btn.addEventListener("pointerup", pttUp);
  btn.addEventListener("pointercancel", pttUp);
  btn.addEventListener("contextmenu", (e) => e.preventDefault());   // tahan lama di HP tidak membuka menu
}
bindPtt($("btn-ptt"));
bindPtt($("btn-ptt2"));

// Spasi = tombol bicara, kecuali sedang mengetik di kotak teks
const isTyping = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || state.screen !== "chat" || isTyping(e.target)) return;
  e.preventDefault();
  if (!e.repeat) pttDown();
});
document.addEventListener("keyup", (e) => {
  if (e.code !== "Space" || !wantListening) return;
  e.preventDefault();
  pttUp();
});
window.addEventListener("blur", pttUp);   // pindah jendela saat menahan spasi -> anggap dilepas

// =====================================================================
// Layar 4: Sesi
// =====================================================================
function addBubble(role, text, withReplay = true, mood = "netral") {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  if (role === "tutor") div.innerHTML = markdown(text);  // aman: markdown() meng-escape dulu
  else div.textContent = text;                           // teks pengguna tidak pernah jadi HTML
  if (role === "tutor" && withReplay && canSpeak) div.appendChild(replayButton(text, mood));
  $("messages").appendChild(div);
  if (state.mode === "chat") div.scrollIntoView({ behavior: "smooth", block: "end" });
  return div;
}

function addSystemNote(text) {
  const div = document.createElement("div");
  div.className = "system";
  div.innerHTML = `${ICON.warn}<span>${escapeHtml(text)}</span>`;
  $("messages").appendChild(div);
}

function replayButton(text, mood = "netral") {
  const b = document.createElement("button");
  b.className = "replay";
  b.innerHTML = `${ICON.speakerOn}<span>Putar ulang</span>`;
  b.addEventListener("click", () => speak(text, { mood }));
  return b;
}

function showStageReply(text, mood = "netral") {
  $("stage-reply").innerHTML = markdown(text);
  if (canSpeak) $("stage-reply").appendChild(replayButton(text, mood));
  $("stage-reply").scrollTop = 0;
}

// Coretan pena merah: kalimat asli dicoret, perbaikannya ditulis tangan. Data langsung dari tool save_mistake.
// Agen kadang menyimpan 2 kesalahan dengan kalimat yang persis sama; tampilkan sekali saja.
function uniqueMarks(list) {
  const seen = new Set();
  return list.filter((k) => {
    const key = `${k.kalimat_asli}\u0000${k.kalimat_benar}`;
    return seen.has(key) ? false : seen.add(key);
  });
}

function marksHtml(list) {
  return uniqueMarks(list).map((k) => `
    <div class="mark">
      <span class="sr-only">Salah:</span><span class="was">${escapeHtml(k.kalimat_asli)}</span>
      <span class="sr-only">Benar:</span><span class="fix">${escapeHtml(k.kalimat_benar)}</span>
      <span class="why">${escapeHtml(k.pola)} · ${escapeHtml(k.kategori.replace("_", " "))}</span>
    </div>`).join("");
}

function showMarks(list) {
  $("stage-marks").innerHTML = list?.length ? marksHtml(list) : "";
  if (list?.length && state.lastUserBubble) {
    const box = document.createElement("div");
    box.className = "marks";
    box.setAttribute("aria-label", "Koreksi");
    box.innerHTML = marksHtml(list);
    state.lastUserBubble.after(box);
  }
}

function setBusy(busy, label = "Tutor sedang membaca jawabanmu...") {
  state.busy = busy;
  for (const id of ["btn-send", "input", "stage-input", "btn-ptt", "btn-ptt2"]) $(id).disabled = busy;
  if (!Recognition) for (const id of ["btn-ptt", "btn-ptt2"]) $(id).disabled = true;
  $("typing")?.remove();
  if (busy) {
    setActivity("thinking");
    liveText(label);
    const t = document.createElement("div");
    t.id = "typing"; t.className = "typing"; t.textContent = label;
    $("messages").appendChild(t);
  } else {
    liveText("");
  }
  refreshLayout();
}

function updateInfo(r) {
  if (r.topik !== undefined) {
    const materi = r.topik ? `Topik: ${r.topik}` : `Skenario: ${r.skenario}`;
    state.persona = r.persona || "galak";
    state.header = `${materi} · Fokus: ${r.fokus_pola.join(", ")} · Gaya: ${state.persona}`;
  }
  $("chat-info-text").textContent = `${state.header} · Giliran ${r.turn}/${r.max_turns}`;
}

// ---- Info kecepatan: dengar (STT) · agen (server: LLM + tool) · suara (TTS mulai berbunyi) ----
function sec(ms) { return `${(ms / 1000).toFixed(1)} s`; }
function renderStats(listenMs, stats, voiceMs) {
  if (!stats) return;
  const counts = {};
  for (const t of stats.tools) counts[t] = (counts[t] || 0) + 1;
  const tools = Object.entries(counts).map(([t, n]) => (n > 1 ? `${t} ×${n}` : t)).join(", ");
  const parts = [];
  if (listenMs != null) parts.push(`dengar ${sec(listenMs)}`);
  parts.push(`agen ${sec(stats.server_ms)} (${stats.llm_calls}× LLM${tools ? ", " + tools : ""})`);
  parts.push(voiceMs != null ? `suara ${sec(voiceMs)}` : ttsOn && canSpeak ? "suara …" : "suara mati");
  $("stats").textContent = parts.join(" · ");
}

// ---- Catatan tutor: memori jangka panjang agen yang tersimpan di database ----
async function loadMemory() {
  try {
    const m = await api(`/api/users/${state.user.id}/memory`);
    if (!m.progres.length && !m.kesalahan.length) {
      $("memory-body").innerHTML = `<p class="muted" style="margin:var(--s3) 0 0">Masih kosong. Begitu kamu salah, tutor mencatatnya di sini, lalu melatihnya lagi di sesi berikutnya.</p>`;
      return;
    }
    const pola = m.progres.map((p) => `<li>${escapeHtml(p.pola)}${p.sudah_dikuasai
      ? `<span class="chip ok">${ICON.check}dikuasai</span>`
      : `<span class="chip">salah ${p.jumlah_salah}× · streak ${p.streak_benar}/3</span>`}</li>`).join("");
    const salah = uniqueMarks(m.kesalahan).map((k) => `<li class="mark"><span class="sr-only">Salah:</span><span class="was">${escapeHtml(k.kalimat_asli)}</span>
      <span class="sr-only">Benar:</span><span class="fix">${escapeHtml(k.kalimat_benar)}</span></li>`).join("");
    $("memory-body").innerHTML =
      (pola ? `<h3>Pola yang sedang dilatih</h3><ul>${pola}</ul>` : "") +
      (salah ? `<h3>Kesalahan terakhir</h3><ul>${salah}</ul>` : "");
  } catch { /* catatan bersifat tambahan; abaikan bila gagal */ }
}

// ---- Satu pintu untuk semua balasan dari server ----
function handleReply(r, listenMs) {
  updateInfo(r);
  setMood(r.mood);
  showMarks(r.koreksi);
  if (r.reply) { addBubble("tutor", r.reply, true, r.mood); showStageReply(r.reply, r.mood); }
  renderStats(listenMs, r.stats, null);
  setActivity("idle");   // selesai berpikir; berubah jadi "speaking" saat suara benar-benar mulai
  if (r.reply && ttsOn && canSpeak) {
    const t0 = performance.now();
    speak(r.reply, { mood: r.mood, onStart: () => renderStats(listenMs, r.stats, performance.now() - t0) });
  }
  loadMemory();
  if (r.selesai) showRecap(r);
}

async function post(path, body, listenMs) {
  setBusy(true);
  try {
    const r = await api(path, body);
    setBusy(false);
    handleReply(r, listenMs);
  } catch (err) {
    setBusy(false);
    setActivity("idle"); setMood("netral");
    addSystemNote(err.message);
    liveText(err.message, "warn");
  }
}

function sendText(text, listenMs = null) {
  text = text.trim();
  if (!text || state.busy || !state.sessionOpen) return;
  stopSpeaking();
  state.lastUserBubble = addBubble("user", text);
  $("stage-user").textContent = `“${text}”`;
  $("stage-marks").innerHTML = "";
  post(`/api/sessions/${state.sessionId}/messages`, { user_id: state.user.id, text }, listenMs);
}

$("btn-send").addEventListener("click", () => { sendText($("input").value); $("input").value = ""; });
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendText($("input").value); $("input").value = ""; }
});
$("stage-form").addEventListener("submit", (e) => { e.preventDefault(); sendText($("stage-input").value); $("stage-input").value = ""; });
$("btn-end").addEventListener("click", () => {
  if (!state.sessionOpen || state.busy) return;
  cancelPtt(); stopSpeaking();
  state.lastUserBubble = null;
  $("stage-user").textContent = "";
  post(`/api/sessions/${state.sessionId}/end`, { user_id: state.user.id });
});

$("btn-start").addEventListener("click", async () => {
  notice("home-error", "");
  for (const id of ["messages", "recap", "stage-user", "stage-marks", "stage-reply", "stats", "chat-info-text"]) $(id).innerHTML = "";
  state.lastUserBubble = null;
  setMood("netral");
  state.sessionOpen = true;
  show("chat");
  setBusy(true, "Menyiapkan materi dari catatanmu...");
  try {
    const r = await api("/api/sessions", { user_id: state.user.id });
    state.sessionId = r.session_id;
    setBusy(false);
    handleReply(r, null);
  } catch (err) {
    state.sessionOpen = false;
    setBusy(false); setActivity("idle");
    show("home");
    notice("home-error", err.message);
  }
});

function showRecap(r) {
  state.sessionOpen = false;
  cancelPtt();
  refreshLayout();
  const rows = (r.progres || []).map((p) => `
    <tr><td>${escapeHtml(p.pola)}</td><td>${p.jumlah_salah}×</td>
        <td>${p.sudah_dikuasai ? `<span class="chip ok" style="margin:0">${ICON.check}dikuasai</span>` : `streak ${p.streak_benar}/3`}</td></tr>`).join("");
  $("recap").innerHTML = `
    <div class="sheet">
      <h2 tabindex="-1" id="h-recap">Rekap sesi</h2>
      ${r.ringkasan ? `<div class="summary">${markdown(r.ringkasan)}</div>` : ""}
      <h2 style="margin-top:var(--s5); font-size:var(--t2)">Progres pola</h2>
      ${rows ? `<table><thead><tr><th scope="col">Pola</th><th scope="col">Salah</th><th scope="col">Status</th></tr></thead><tbody>${rows}</tbody></table>`
             : `<p class="muted">Belum ada pola yang tercatat di sesi ini.</p>`}
      <div class="row" style="margin-top:var(--s5)"><button id="btn-back">Kembali ke beranda</button></div>
    </div>`;
  $("btn-back").addEventListener("click", () => showHome());
  $("recap").scrollIntoView({ behavior: "smooth", block: "start" });
  $("h-recap").focus({ preventScroll: true });
}

// =====================================================================
// Saat halaman dibuka: masuk otomatis jika username pernah disimpan
// =====================================================================
$("memory").querySelector("summary").innerHTML = `${ICON.notes}<span>Catatan tutor tentang kamu</span>`;
setupMic();
renderTtsButton();
refreshLayout();
const saved = load("username", null);
if (saved) login(saved).catch(() => show("login")); else show("login");
