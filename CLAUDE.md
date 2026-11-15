# AI English Tutor

Web app tutor bahasa Inggris berbasis agen AI untuk mahasiswa Indonesia.
Tujuan utama: portofolio belajar agentic AI (tool calling, memori, planner).

## Aturan kerja
- Jawab dalam Bahasa Indonesia, formal dan langsung ke inti.
- Perubahan kode minimal dan terarah. Jangan mengubah hal yang tidak diminta.
- Jangan pakai framework agen (LangGraph, CrewAI, dll.). Loop agen ditulis manual.
- Akses database lewat ORM Django, dan SEMUA akses data tetap di `db.py` (agen/tools/planner tidak memakai model langsung).
  Fungsi `db.py` mengembalikan dict biasa. Perubahan skema: ubah `tutor/models.py` lalu `manage.py makemigrations`.
- Jalankan Python dengan `uv run`, tambah library dengan `uv add`.
- Jangan pernah membaca, mencetak, atau commit isi `.env`.
- Pengguna sedang belajar Django: setiap perubahan Django disertai penjelasan singkat konsepnya.

## Stack
- Python + `uv`, Django 6 (lapisan web, ORM, admin), Pydantic v2 (validasi request API & argumen tool)
- LLM: DeepSeek `deepseek-v4-flash` via OpenAI SDK, langsung (tanpa router)
  - Config di `.env`: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`
  - Semua pemanggilan API lewat satu fungsi `call_llm()`; retry 2x, tanpa fallback
- Database: PostgreSQL native (tanpa Docker), driver `psycopg` 3, dikelola migration Django
  - Model di `tutor/models.py` (nama tabel lama via `db_table`); `seed.sql` untuk kurikulum pemula;
    `schema.sql` hanya referensi sejarah. DB lama: `manage.py adopt_legacy_db` (sekali jalan)
  - Koneksi lewat `DATABASE_URL` di `.env`; `psql` ada di `D:\Program Files\PostgreSQL\18\bin` (tidak di PATH)
- Django: project `config/` (settings, urls), app `tutor/` (models, views, urls, admin, schemas). TIME_ZONE Asia/Jakarta.
  API JSON di `tutor/views.py` memakai decorator `@api(method, SkemaPydantic)`; panel admin di `/admin/`.
- Frontend: satu halaman tanpa framework, dipisah jadi `public/index.html` (struktur), `public/static/style.css`
  (tampilan), `public/static/app.js` (perilaku); di Vercel disajikan CDN, di lokal oleh Django (DEBUG).
  STT via Web Speech API browser.
- Suara tutor: Gemini TTS (`tts.py`, `gemini-3.8-flash-tts`, WAJIB API `v1beta`), `GEMINI_API_KEY` di `.env` (opsional).
  Suara Bodi (galak) / Fola (lembut), catatan sutradara per mood. Paket gratis 10 suara/hari: Gemini hanya untuk mood
  marah/koreksi/senang; selebihnya & saat gagal/kuota habis memakai suara browser.
- Jalankan web: `uv run python manage.py runserver`, CLI: `uv run main.py`
- Tes: `uv run pytest` (LLM & Gemini tiruan, tanpa biaya). Setelah mengubah prompt, WAJIB juga
  `RUN_LIVE=1 uv run pytest tests/test_live.py`: perubahan prompt bisa diam-diam menghentikan tool calling.

## Desain produk
- Hanya bahasa Inggris. Level: pemula (dari nol), menengah, lanjut.
- Tes penempatan 5 soal saat pertama masuk; opsi "mulai dari nol" melewati tes.
  Pilihan ganda statis di `placement.py`, dinilai kode: skor 0-2 pemula, 3-4 menengah, 5 lanjut.
- Bahasa penjelasan: pemula = Indonesia, menengah = campuran, lanjut = English.
- Gaya mentor dipilih pengguna di beranda (`users.persona_default`, NULL = galak):
  - galak: galak saat salah, santai saat benar. Pemula tanpa sarkas; menengah/lanjut boleh sarkas ke jawaban.
  - lembut: sabar, akui usaha dulu lalu koreksi dengan tenang, tanpa sarkas.
  Apa pun gayanya: tidak pernah menghina orangnya dan kesalahan tetap dikoreksi (save_mistake).
  Teks gaya ada di `PERSONAS` (agent.py), diletakkan tepat setelah prompt statis agar cache tetap per gaya.
  Ekspresi & nada suara: galak+salah = marah, lembut+salah = koreksi, benar = senang.
- Kurikulum pemula 6 topik (di database): perkenalan diri, kampus & jurusan,
  rutinitas harian, hobi, arah & tempat, minta tolong.
- Skenario menengah/lanjut: interview magang, presentasi kelas.
- Tidak ada penilaian pelafalan di MVP; cukup tampilkan transkrip STT.
- Web punya 2 mode: suara (wajah berekspresi + tahan tombol/spasi untuk bicara) dan chat.
  Ekspresi wajah dari tool agen per giliran: save_mistake = marah, giliran pengguna tanpa salah = senang.
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
5. M5: voice (Web Speech API)  -- selesai
   - Migrasi backend FastAPI -> Django (ORM, migrations, admin) + suara tutor Gemini TTS  -- selesai (branch `django`)
6. M6: deploy ke VPS (PostgreSQL hanya listen di localhost) + uji coba teman sekelas  <- posisi sekarang
   Wajib HTTPS: input suara (SpeechRecognition) hanya jalan di localhost atau HTTPS.

Output portofolio: repo GitHub publik, README (diagram arsitektur, loop agen,
4 tool, prompt caching), video demo 1-2 menit.
