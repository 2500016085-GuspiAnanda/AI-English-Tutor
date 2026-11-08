# AI English Tutor

Web app tutor bahasa Inggris berbasis agen AI untuk mahasiswa Indonesia.
Tujuan utama: portofolio belajar agentic AI (tool calling, memori, planner).

## Aturan kerja
- Jawab dalam Bahasa Indonesia, formal dan langsung ke inti.
- Perubahan kode minimal dan terarah. Jangan mengubah hal yang tidak diminta.
- Jangan pakai framework agen (LangGraph, CrewAI, dll.). Loop agen ditulis manual.
- Jangan pakai ORM. SQL ditulis manual, semua query di `db.py`.
- Jalankan Python dengan `uv run`, tambah library dengan `uv add`.
- Jangan pernah membaca, mencetak, atau commit isi `.env`.

## Stack
- Python + `uv`, FastAPI, Pydantic v2
- LLM: DeepSeek `deepseek-v4-flash` via OpenAI SDK, langsung (tanpa router)
  - Config di `.env`: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`
  - Semua pemanggilan API lewat satu fungsi `call_llm()`; retry 2x, tanpa fallback
- Database: PostgreSQL native (tanpa Docker), driver `psycopg` 3
  - `schema.sql` untuk tabel, `seed.sql` untuk kurikulum pemula
  - Koneksi lewat `DATABASE_URL` di `.env`; `psql` ada di `D:\Program Files\PostgreSQL\18\bin` (tidak di PATH)
- Frontend: satu halaman `static/index.html` (HTML/JS tanpa framework) via `app.py`; voice via Web Speech API (STT + TTS browser)
- Jalankan web: `uv run uvicorn app:app --reload`, CLI: `uv run main.py`

## Desain produk
- Hanya bahasa Inggris. Level: pemula (dari nol), menengah, lanjut.
- Tes penempatan 5 soal saat pertama masuk; opsi "mulai dari nol" melewati tes.
  Pilihan ganda statis di `placement.py`, dinilai kode: skor 0-2 pemula, 3-4 menengah, 5 lanjut.
- Bahasa penjelasan: pemula = Indonesia, menengah = campuran, lanjut = English.
- Persona dinamis: galak saat pengguna salah, santai saat benar.
  Pemula: tegas tanpa sarkas. Menengah/lanjut: boleh sarkas ke jawaban, tidak pernah menghina orangnya.
- Kurikulum pemula 6 topik (di database): perkenalan diri, kampus & jurusan,
  rutinitas harian, hobi, arah & tempat, minta tolong.
- Skenario menengah/lanjut: interview magang, presentasi kelas.
- Tidak ada penilaian pelafalan di MVP; cukup tampilkan transkrip STT.
- Batas 3 sesi/hari per pengguna. Login cukup username (tanpa password).

## Agen
Tool (argumen divalidasi Pydantic, agen memutuskan sendiri kapan memanggil):
- `save_mistake(kalimat_asli, kalimat_benar, kategori, pola)`
- `get_error_log(user_id)`
- `mark_progress(pola, benar)`
- `end_session(ringkasan)`

Kategori valid: `grammar`, `vocabulary`, `word_choice`, `sentence_structure`.

Alur sesi: Planner (1 call: baca level + pattern_progress, pilih skenario dan
1-2 pola) -> Percakapan (maks. 10 giliran) -> Rekap (3 kesalahan utama,
1 hal yang sudah bagus, status pola).

Pola dianggap dikuasai setelah 3 sesi berturut-turut tanpa kesalahan yang sama.

Prompt caching: bagian statis (persona, definisi tool, aturan level) di depan,
bagian dinamis (error log, riwayat) di belakang.

## Tabel
- `users`: id, username, level, persona_default, sudah_tes, created_at
- `curriculum_topics`: id, level, urutan, judul, tujuan, contoh_kalimat
- `sessions`: id, user_id, topic_id/skenario, fokus_pola, ringkasan, created_at
- `messages`: id, session_id, role, content, model, tokens, created_at
- `mistakes`: id, user_id, session_id, kalimat_asli, kalimat_benar, kategori, pola, created_at
- `pattern_progress`: user_id, pola, jumlah_salah, streak_benar, sudah_dikuasai,
  terakhir_muncul; `UNIQUE (user_id, pola)` untuk upsert

Gunakan `GENERATED ALWAYS AS IDENTITY`, `TIMESTAMPTZ`, `BOOLEAN`, dan
`CHECK` constraint untuk level dan kategori.

## Milestone
1. M1: spike test tool calling DeepSeek (`spike_m1.py`)  -- selesai
2. M2: loop agen di CLI + 4 tool + PostgreSQL  -- selesai
3. M3: planner + tes penempatan + level  -- selesai
4. M4: FastAPI + halaman web mode teks  -- selesai
5. M5: voice (Web Speech API)  <- posisi sekarang
6. M6: deploy ke VPS (PostgreSQL hanya listen di localhost) + uji coba teman sekelas

Output portofolio: repo GitHub publik, README (diagram arsitektur, loop agen,
4 tool, prompt caching), video demo 1-2 menit.
