"""Tes database: query SQL di db.py dijalankan ke PostgreSQL sungguhan."""

import psycopg
import pytest

import db
from tests.conftest import PREFIX


def new_user(conn, name="db"):
    return db.get_or_create_user(conn, PREFIX + name)


def test_get_or_create_user_idempoten(conn):
    a, b = new_user(conn), new_user(conn)
    assert a["id"] == b["id"]
    assert (a["level"], a["sudah_tes"], a["persona_default"]) == ("pemula", False, None)


def test_set_placement(conn):
    u = new_user(conn)
    db.set_placement(conn, u["id"], "menengah")
    assert db.get_user(conn, u["id"])["level"] == "menengah"
    assert db.get_user(conn, u["id"])["sudah_tes"] is True


def test_constraint_menolak_level_dan_persona_karangan(conn):
    u = new_user(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.set_persona(conn, u["id"], "marah")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.set_placement(conn, u["id"], "dewa")


def test_pola_dikuasai_setelah_3_sesi_benar_berturut_turut(conn):
    uid = new_user(conn)["id"]
    db.record_pattern_failure(conn, uid, "to be")
    assert db.record_pattern_success(conn, uid, "to be")["streak_benar"] == 1
    assert db.record_pattern_success(conn, uid, "to be")["sudah_dikuasai"] is False
    row = db.record_pattern_success(conn, uid, "to be")
    assert (row["streak_benar"], row["sudah_dikuasai"]) == (3, True)


def test_salah_lagi_mereset_streak_dan_status_dikuasai(conn):
    uid = new_user(conn)["id"]
    for _ in range(3):
        db.record_pattern_success(conn, uid, "to be")
    db.record_pattern_failure(conn, uid, "to be")
    p = db.get_pattern_progress(conn, uid)[0]
    assert (p["jumlah_salah"], p["streak_benar"], p["sudah_dikuasai"]) == (1, 0, False)


def test_hitung_sesi_hari_ini_dan_topik(conn):
    uid = new_user(conn)["id"]
    topics = db.list_topics_with_history(conn, uid, "pemula")
    assert len(topics) == 6, "jalankan seed.sql"
    db.create_session(conn, uid, topics[0]["id"], None, ["to be"])
    assert db.count_sessions_today(conn, uid) == 1
    assert db.list_topics_with_history(conn, uid, "pemula")[0]["kali_dipelajari"] == 1


def test_error_log_terbaru_dulu(conn):
    uid = new_user(conn)["id"]
    sid = db.create_session(conn, uid, None, "interview magang", [])
    db.insert_mistake(conn, uid, sid, "I go", "I went", "grammar", "simple past")
    db.insert_mistake(conn, uid, sid, "a apple", "an apple", "grammar", "article a/an")
    log = db.get_error_log(conn, uid)
    assert [m["kalimat_benar"] for m in log] == ["an apple", "I went"]


def test_hapus_pengguna_ikut_menghapus_datanya(conn):
    uid = new_user(conn)["id"]
    sid = db.create_session(conn, uid, None, "presentasi kelas", [])
    db.insert_mistake(conn, uid, sid, "x", "y", "grammar", "p")
    conn.execute("DELETE FROM users WHERE id = %s", (uid,))
    assert conn.execute("SELECT count(*) AS n FROM mistakes WHERE user_id = %s", (uid,)).fetchone()["n"] == 0
