-- Skema database AI English Tutor (PostgreSQL)
-- Jalankan: psql -d ai_english_tutor -f schema.sql

CREATE TABLE users (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    level           TEXT NOT NULL DEFAULT 'pemula'
                    CHECK (level IN ('pemula', 'menengah', 'lanjut')),
    persona_default TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE curriculum_topics (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    level          TEXT NOT NULL
                   CHECK (level IN ('pemula', 'menengah', 'lanjut')),
    urutan         INTEGER NOT NULL,
    judul          TEXT NOT NULL,
    tujuan         TEXT NOT NULL,
    contoh_kalimat TEXT,
    UNIQUE (level, urutan)
);

CREATE TABLE sessions (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    topic_id   INTEGER REFERENCES curriculum_topics (id),  -- diisi untuk pemula
    skenario   TEXT,                                       -- diisi untuk menengah/lanjut
    fokus_pola TEXT[] NOT NULL DEFAULT '{}',               -- 1-2 pola dari planner
    ringkasan  TEXT,                                       -- diisi oleh end_session
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (topic_id IS NOT NULL OR skenario IS NOT NULL)
);

CREATE TABLE messages (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content    TEXT NOT NULL,
    model      TEXT,
    tokens     INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE mistakes (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    session_id    INTEGER NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    kalimat_asli  TEXT NOT NULL,
    kalimat_benar TEXT NOT NULL,
    kategori      TEXT NOT NULL
                  CHECK (kategori IN ('grammar', 'vocabulary', 'word_choice', 'sentence_structure')),
    pola          TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pattern_progress (
    user_id         INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    pola            TEXT NOT NULL,
    jumlah_salah    INTEGER NOT NULL DEFAULT 0,
    streak_benar    INTEGER NOT NULL DEFAULT 0,   -- sesi berturut-turut tanpa salah
    sudah_dikuasai  BOOLEAN NOT NULL DEFAULT false,
    terakhir_muncul TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, pola)                        -- target ON CONFLICT untuk upsert
);

-- Index untuk query yang sering: error log per user, riwayat per sesi,
-- dan hitung sesi per hari (batas 3 sesi/hari).
CREATE INDEX idx_mistakes_user  ON mistakes (user_id, created_at DESC);
CREATE INDEX idx_messages_sess  ON messages (session_id, created_at);
CREATE INDEX idx_sessions_user  ON sessions (user_id, created_at DESC);
