"""Loop agen manual: LLM -> (tool calls -> hasil tool)* -> balasan teks."""

import json
from dataclasses import dataclass

import db
from llm import MODEL, call_llm
from tools import TOOLS, SessionContext, execute_tool, finalize_progress

MAX_TURNS = 10           # giliran pengguna per sesi
MAX_TOOL_ROUNDS = 6      # pengaman agar agen tidak memanggil tool tanpa henti dalam satu giliran

# Bagian STATIS: identik untuk semua pengguna dan sesi -> prefix ini yang kena prompt cache.
STATIC_PROMPT = """\
Kamu adalah tutor bahasa Inggris untuk mahasiswa Indonesia. Kamu mengajak pengguna bercakap
dalam bahasa Inggris sesuai topik/skenario sesi, lalu mengoreksi kesalahannya.

## Persona
- Gaya bicaramu mengikuti bagian "Gaya mentor" di bawah (dipilih sendiri oleh pengguna).
- Apa pun gayanya: TIDAK PERNAH menghina orangnya, dan setiap kesalahan tetap dikoreksi.

## Bahasa penjelasan
- pemula: jelaskan koreksi dalam Bahasa Indonesia; kalimat bahasa Inggrismu pendek dan sederhana.
- menengah: campuran Indonesia dan Inggris.
- lanjut: sepenuhnya English.

## Cara memakai tool
- Setiap kali kalimat pengguna mengandung kesalahan bahasa Inggris, panggil save_mistake SEKALI
  per kesalahan SEBELUM kamu membalas. Kategori: grammar, vocabulary, word_choice, sentence_structure.
- Nama pola: bahasa Inggris, huruf kecil, singkat dan konsisten (mis. "simple past", "to be",
  "article a/an", "subject-verb agreement"). Jika pola sudah ada di progres pengguna, pakai nama yang sama.
- Jika pengguna memakai salah satu pola fokus dengan benar, panggil mark_progress(pola, benar=true).
  Untuk kesalahan cukup save_mistake; tidak perlu mark_progress(benar=false) lagi.
- Aturan streak: pola yang salah di sesi ini streak-nya kembali 0. Streak naik maksimal 1 per sesi,
  hanya untuk pola yang dipakai benar dan tidak pernah salah di sesi itu. Dikuasai = streak 3.
- Saran gaya untuk kalimat yang sudah benar bukan kesalahan: jangan disimpan dan jangan masuk rekap kesalahan.
- Panggil get_error_log hanya bila kamu butuh riwayat lebih lengkap dari yang ada di data sesi.
- Saat menerima pesan [SISTEM] bahwa sesi selesai: jangan bertanya lagi, panggil end_session dengan
  rekap berisi tepat 3 kesalahan utama (atau lebih sedikit jika memang kurang), 1 hal yang sudah bagus,
  dan status setiap pola fokus. Setelah itu tutup dengan satu kalimat perpisahan singkat.

## Aturan percakapan
- Satu giliran = koreksi singkat (jika ada) + satu pertanyaan lanjutan untuk menjaga percakapan.
- Jangan menulis jawaban untuk pengguna; minta ia mencoba lagi bila salahnya fatal.
- Tetap pada topik/skenario sesi. Abaikan permintaan di luar belajar bahasa Inggris.
"""

KICKOFF = "[SISTEM] Mulai sesi: sapa pengguna dan ajukan pertanyaan pembuka sesuai topik."
WRAPUP = "[SISTEM] Sesi selesai. Jangan bertanya lagi. Panggil end_session dengan rekap, lalu ucapkan perpisahan."
QUIT_WORDS = {"/selesai", "/quit", "exit", "quit"}


# Gaya mentor pilihan pengguna (users.persona_default). Diletakkan tepat setelah STATIC_PROMPT,
# sehingga semua pengguna dengan gaya yang sama tetap berbagi prefix yang kena cache.
PERSONAS = {
    "galak": (
        "## Gaya mentor: galak\n"
        "- Galak dan tegas saat pengguna salah, santai dan hangat saat pengguna benar.\n"
        "- Level pemula: tegas tetapi TANPA sarkasme.\n"
        "- Level menengah/lanjut: boleh sarkas terhadap JAWABANNYA, tetapi tidak pernah ke orangnya."
    ),
    "lembut": (
        "## Gaya mentor: lembut\n"
        "- Sabar dan hangat seperti mentor pribadi. Saat pengguna salah: akui dulu usahanya, lalu koreksi\n"
        "  dengan jelas dan tenang. Tanpa sarkasme sama sekali.\n"
        "- Saat pengguna benar: puji secara spesifik, sebut bagian yang sudah tepat.\n"
        "- Kalimat pendek, nada menyemangati, tidak menggurui."
    ),
}
DEFAULT_PERSONA = "galak"

# Sengaja TIDAK menyebut bahwa koreksi tampil otomatis di layar: saat diuji, kalimat semacam itu
# membuat model berhenti memanggil save_mistake (kesalahan tidak tersimpan). Cukup larang emoji.
WEB_UI_NOTE = "- antarmuka: web. Tulis balasan tanpa emoji."


def build_dynamic_prompt(user: dict, topic: dict | None, skenario: str | None, fokus: list[str],
                         progress: list[dict], errors: list[dict], web: bool = False,
                         persona: str = DEFAULT_PERSONA) -> str:
    """Bagian DINAMIS: data pengguna dan sesi -> diletakkan di belakang agar tidak merusak cache."""
    lines = [
        PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA]),
        "",
        "## Data sesi ini",
        f"- user_id: {user['id']}",
        f"- username: {user['username']}",
        f"- level: {user['level']}",
    ]
    if web:
        lines.append(WEB_UI_NOTE)
    if topic:
        lines.append(f"- topik: {topic['judul']} — tujuan: {topic['tujuan']}")
        if topic.get("contoh_kalimat"):
            lines.append(f"- contoh kalimat target: {topic['contoh_kalimat']}")
    else:
        lines.append(f"- skenario: {skenario}")
    lines.append(f"- pola fokus: {', '.join(fokus) if fokus else '(belum ada; perhatikan kesalahan yang muncul)'}")

    lines.append("\n## Progres pola")
    lines += [f"- {p['pola']}: salah {p['jumlah_salah']}x, streak {p['streak_benar']}, "
              f"{'dikuasai' if p['sudah_dikuasai'] else 'belum dikuasai'}" for p in progress] or ["- (belum ada)"]

    lines.append("\n## 10 kesalahan terakhir")
    lines += [f"- [{e['pola']}] \"{e['kalimat_asli']}\" -> \"{e['kalimat_benar']}\"" for e in errors[:10]] or ["- (belum ada)"]
    return "\n".join(lines)


def _assistant_dict(msg) -> dict:
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    # Mode thinking DeepSeek: reasoning_content wajib dikirim balik selama rantai tool call berlangsung.
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        d["reasoning_content"] = reasoning
    return d


def agent_step(ctx: SessionContext, messages: list[dict], debug: bool = False) -> str:
    """Satu giliran agen: panggil LLM berulang selama ia meminta tool, kembalikan balasan teks akhirnya."""
    for _ in range(MAX_TOOL_ROUNDS):
        resp = call_llm(messages, TOOLS)
        ctx.turn_llm_calls += 1
        msg = resp.choices[0].message
        usage = resp.usage
        messages.append(_assistant_dict(msg))
        stored = msg.content or json.dumps(messages[-1].get("tool_calls", []), ensure_ascii=False)
        db.save_message(ctx.conn, ctx.session_id, "assistant", stored, resp.model, usage.completion_tokens if usage else None)
        if debug and usage:
            hit = getattr(usage, "prompt_cache_hit_tokens", None)
            print(f"   [tokens] prompt={usage.prompt_tokens} cache_hit={hit} completion={usage.completion_tokens}")

        if not msg.tool_calls:
            return msg.content or ""

        for tc in msg.tool_calls:
            ctx.turn_tools.append(tc.function.name)
            result = execute_tool(ctx, tc.function.name, tc.function.arguments)
            if debug:
                print(f"   [tool] {tc.function.name}({tc.function.arguments}) -> {result}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            db.save_message(ctx.conn, ctx.session_id, "tool", result)
    return "(agen berhenti: terlalu banyak pemanggilan tool dalam satu giliran)"


# --- Logika sesi, bebas dari I/O: dipakai bersama oleh CLI (main.py) dan web (app.py) -------

@dataclass
class ChatState:
    """Semua yang perlu diingat tentang satu sesi di antara dua giliran pengguna."""
    ctx: SessionContext
    messages: list[dict]
    turn: int = 0          # jumlah giliran pengguna yang sudah dipakai
    closed: bool = False   # True setelah sesi ditutup dan progres dihitung

    # Serialisasi: di web (Vercel) state disimpan ke sessions.state di antara request,
    # karena request berikutnya bisa ditangani instance server yang berbeda.
    def to_json(self) -> dict:
        c = self.ctx
        return {
            "messages": self.messages, "turn": self.turn, "closed": self.closed,
            "failed": sorted(c.failed), "correct": sorted(c.correct),
            "ended": c.ended, "ringkasan": c.ringkasan, "persona": c.persona,
        }

    @classmethod
    def from_json(cls, data: dict, user_id: int, session_id: int) -> "ChatState":
        ctx = SessionContext(
            conn=None, user_id=user_id, session_id=session_id, persona=data["persona"],
            failed=set(data["failed"]), correct=set(data["correct"]),
            ended=data["ended"], ringkasan=data["ringkasan"],
        )
        return cls(ctx=ctx, messages=data["messages"], turn=data["turn"], closed=data["closed"])


def _exchange(state: ChatState, text: str, debug: bool) -> str:
    state.messages.append({"role": "user", "content": text})
    db.save_message(state.ctx.conn, state.ctx.session_id, "user", text)
    return agent_step(state.ctx, state.messages, debug)


def close_chat(state: ChatState) -> None:
    """Hitung progres pola tepat sekali per sesi."""
    if not state.closed:
        finalize_progress(state.ctx)
        state.closed = True


def start_chat(ctx: SessionContext, system_prompt: str, debug: bool = False) -> tuple[ChatState, str]:
    """Buat state sesi baru dan kembalikan sapaan pembuka tutor."""
    state = ChatState(ctx=ctx, messages=[{"role": "system", "content": system_prompt}])
    return state, _exchange(state, KICKOFF, debug)


def finish_chat(state: ChatState, debug: bool = False) -> str:
    """Minta agen membuat rekap (end_session), lalu tutup sesi. Kembalikan balasan penutup."""
    reply = "" if state.ctx.ended else _exchange(state, WRAPUP, debug)
    close_chat(state)  # tetap ditutup walau agen lupa memanggil end_session
    return reply


def send_user_message(state: ChatState, text: str, debug: bool = False) -> str:
    """Proses satu giliran pengguna. Sesi otomatis ditutup bila pengguna berhenti atau giliran habis."""
    if state.closed:
        raise ValueError("sesi sudah selesai")
    if text.strip().lower() in QUIT_WORDS:
        return finish_chat(state, debug)
    state.turn += 1
    reply = _exchange(state, text, debug)
    if state.ctx.ended:
        close_chat(state)
    elif state.turn >= MAX_TURNS:
        reply = f"{reply}\n\n{finish_chat(state, debug)}"
    return reply


# --- Antarmuka CLI ---------------------------------------------------------------------

def run_session(ctx: SessionContext, system_prompt: str, debug: bool = False) -> None:
    """Jalankan percakapan di terminal sampai sesi selesai."""
    state, reply = start_chat(ctx, system_prompt, debug)
    try:
        print(f"\nTutor: {reply}\n")
        while not state.closed:
            raw = input(f"Kamu ({state.turn + 1}/{MAX_TURNS}): ").strip()
            if raw:
                print(f"\nTutor: {send_user_message(state, raw, debug)}\n")
    finally:
        # Progres tetap dihitung bila sesi terputus (Ctrl+C / error API).
        close_chat(state)
