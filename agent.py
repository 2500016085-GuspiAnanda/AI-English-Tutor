"""Loop agen manual: LLM -> (tool calls -> hasil tool)* -> balasan teks."""

import json

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
- Dinamis: galak dan tegas saat pengguna salah, santai dan hangat saat pengguna benar.
- Level pemula: tegas tetapi TANPA sarkasme.
- Level menengah/lanjut: boleh sarkas terhadap JAWABANNYA, tetapi TIDAK PERNAH menghina orangnya.

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


def build_dynamic_prompt(user: dict, topic: dict | None, skenario: str | None, fokus: list[str],
                         progress: list[dict], errors: list[dict]) -> str:
    """Bagian DINAMIS: data pengguna dan sesi -> diletakkan di belakang agar tidak merusak cache."""
    lines = [
        "## Data sesi ini",
        f"- user_id: {user['id']}",
        f"- username: {user['username']}",
        f"- level: {user['level']}",
    ]
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
            result = execute_tool(ctx, tc.function.name, tc.function.arguments)
            if debug:
                print(f"   [tool] {tc.function.name}({tc.function.arguments}) -> {result}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            db.save_message(ctx.conn, ctx.session_id, "tool", result)
    return "(agen berhenti: terlalu banyak pemanggilan tool dalam satu giliran)"


def run_session(ctx: SessionContext, system_prompt: str, debug: bool = False) -> list[dict]:
    """Jalankan percakapan CLI sampai end_session dipanggil atau batas giliran tercapai.

    Mengembalikan daftar pola yang streak-nya naik di sesi ini.
    """
    messages = [{"role": "system", "content": system_prompt}]
    user_text, turn, wrapping = KICKOFF, 0, False
    try:
        while True:
            messages.append({"role": "user", "content": user_text})
            db.save_message(ctx.conn, ctx.session_id, "user", user_text)
            reply = agent_step(ctx, messages, debug)
            if reply:
                print(f"\nTutor: {reply}\n")
            if ctx.ended or wrapping:
                break  # selesai normal, atau agen tetap tidak memanggil end_session setelah diminta
            if turn >= MAX_TURNS:
                user_text, wrapping = WRAPUP, True
                continue

            raw = ""
            while not raw:
                raw = input(f"Kamu ({turn + 1}/{MAX_TURNS}): ").strip()
            if raw.lower() in QUIT_WORDS:
                user_text, wrapping = WRAPUP, True
            else:
                user_text, turn = raw, turn + 1
    finally:
        # Streak dihitung sekali per sesi, termasuk bila sesi terputus (Ctrl+C / error API).
        promoted = finalize_progress(ctx)
    return promoted
