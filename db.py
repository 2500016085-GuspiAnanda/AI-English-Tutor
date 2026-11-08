"""Semua query SQL ada di sini. Tanpa ORM."""

import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

MASTERED_STREAK = 3  # sesi berturut-turut tanpa salah agar pola dianggap dikuasai


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row)


# --- users -----------------------------------------------------------------

def get_or_create_user(conn, username: str) -> dict:
    row = conn.execute(
        """
        INSERT INTO users (username) VALUES (%s)
        ON CONFLICT (username) DO UPDATE SET username = EXCLUDED.username
        RETURNING id, username, level, persona_default, sudah_tes
        """,
        (username,),
    ).fetchone()
    return row


def set_placement(conn, user_id: int, level: str) -> None:
    conn.execute("UPDATE users SET level = %s, sudah_tes = true WHERE id = %s", (level, user_id))


def count_sessions_today(conn, user_id: int) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM sessions WHERE user_id = %s AND created_at >= date_trunc('day', now())",
        (user_id,),
    ).fetchone()
    return row["n"]


# --- kurikulum & sesi ----------------------------------------------------

def list_topics_with_history(conn, user_id: int, level: str) -> list[dict]:
    """Semua topik di level ini + berapa kali pengguna sudah mempelajarinya (bahan planner)."""
    return conn.execute(
        """
        SELECT t.id, t.urutan, t.judul, t.tujuan, t.contoh_kalimat,
               count(s.id) AS kali_dipelajari, max(s.created_at)::date AS terakhir
        FROM curriculum_topics t
        LEFT JOIN sessions s ON s.topic_id = t.id AND s.user_id = %s
        WHERE t.level = %s
        GROUP BY t.id
        ORDER BY t.urutan
        """,
        (user_id, level),
    ).fetchall()


def create_session(conn, user_id: int, topic_id: int | None, skenario: str | None, fokus_pola: list[str]) -> int:
    row = conn.execute(
        """
        INSERT INTO sessions (user_id, topic_id, skenario, fokus_pola)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (user_id, topic_id, skenario, fokus_pola),
    ).fetchone()
    return row["id"]


def end_session(conn, session_id: int, ringkasan: str) -> None:
    conn.execute("UPDATE sessions SET ringkasan = %s WHERE id = %s", (ringkasan, session_id))


def save_message(conn, session_id: int, role: str, content: str, model: str | None = None, tokens: int | None = None) -> None:
    conn.execute(
        "INSERT INTO messages (session_id, role, content, model, tokens) VALUES (%s, %s, %s, %s, %s)",
        (session_id, role, content, model, tokens),
    )


# --- kesalahan & progres pola ---------------------------------------------

def insert_mistake(conn, user_id: int, session_id: int, kalimat_asli: str, kalimat_benar: str, kategori: str, pola: str) -> int:
    row = conn.execute(
        """
        INSERT INTO mistakes (user_id, session_id, kalimat_asli, kalimat_benar, kategori, pola)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (user_id, session_id, kalimat_asli, kalimat_benar, kategori, pola),
    ).fetchone()
    return row["id"]


def get_error_log(conn, user_id: int, limit: int = 20) -> list[dict]:
    return conn.execute(
        """
        SELECT kalimat_asli, kalimat_benar, kategori, pola, created_at::date AS tanggal
        FROM mistakes WHERE user_id = %s
        ORDER BY created_at DESC LIMIT %s
        """,
        (user_id, limit),
    ).fetchall()


def record_pattern_failure(conn, user_id: int, pola: str) -> None:
    conn.execute(
        """
        INSERT INTO pattern_progress (user_id, pola, jumlah_salah, streak_benar, sudah_dikuasai)
        VALUES (%s, %s, 1, 0, false)
        ON CONFLICT (user_id, pola) DO UPDATE SET
            jumlah_salah    = pattern_progress.jumlah_salah + 1,
            streak_benar    = 0,
            sudah_dikuasai  = false,
            terakhir_muncul = now()
        """,
        (user_id, pola),
    )


def record_pattern_success(conn, user_id: int, pola: str) -> dict:
    """Dipanggil maksimal sekali per pola per sesi (dijaga di tools.py)."""
    return conn.execute(
        """
        INSERT INTO pattern_progress (user_id, pola, jumlah_salah, streak_benar, sudah_dikuasai)
        VALUES (%(u)s, %(p)s, 0, 1, 1 >= %(m)s)
        ON CONFLICT (user_id, pola) DO UPDATE SET
            streak_benar    = pattern_progress.streak_benar + 1,
            sudah_dikuasai  = pattern_progress.streak_benar + 1 >= %(m)s,
            terakhir_muncul = now()
        RETURNING pola, streak_benar, sudah_dikuasai
        """,
        {"u": user_id, "p": pola, "m": MASTERED_STREAK},
    ).fetchone()


def get_pattern_progress(conn, user_id: int) -> list[dict]:
    return conn.execute(
        """
        SELECT pola, jumlah_salah, streak_benar, sudah_dikuasai
        FROM pattern_progress WHERE user_id = %s
        ORDER BY sudah_dikuasai, terakhir_muncul DESC
        """,
        (user_id,),
    ).fetchall()
