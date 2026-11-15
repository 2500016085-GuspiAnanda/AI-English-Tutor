"""Tes database: fungsi ORM di db.py dijalankan ke PostgreSQL sungguhan."""

import pytest
from django.db import IntegrityError

import db
from tests.conftest import PREFIX
from tutor.models import Kesalahan, Pelajar


def new_user(name="db"):
    return db.get_or_create_user(PREFIX + name)


def test_get_or_create_user_idempoten(bersihkan):
    a, b = new_user(), new_user()
    assert a["id"] == b["id"]
    assert (a["level"], a["sudah_tes"], a["persona_default"]) == ("pemula", False, None)


def test_set_placement(bersihkan):
    u = new_user()
    db.set_placement(u["id"], "menengah")
    assert db.get_user(u["id"])["level"] == "menengah"
    assert db.get_user(u["id"])["sudah_tes"] is True


def test_constraint_menolak_level_dan_persona_karangan(bersihkan):
    u = new_user()
    with pytest.raises(IntegrityError):   # Django membungkus CheckViolation PostgreSQL jadi IntegrityError
        db.set_persona(u["id"], "marah")
    with pytest.raises(IntegrityError):   # Django membungkus CheckViolation PostgreSQL jadi IntegrityError
        db.set_placement(u["id"], "dewa")


def test_pola_dikuasai_setelah_3_sesi_benar_berturut_turut(bersihkan):
    uid = new_user()["id"]
    db.record_pattern_failure(uid, "to be")
    assert db.record_pattern_success(uid, "to be")["streak_benar"] == 1
    assert db.record_pattern_success(uid, "to be")["sudah_dikuasai"] is False
    row = db.record_pattern_success(uid, "to be")
    assert (row["streak_benar"], row["sudah_dikuasai"]) == (3, True)


def test_salah_lagi_mereset_streak_dan_status_dikuasai(bersihkan):
    uid = new_user()["id"]
    for _ in range(3):
        db.record_pattern_success(uid, "to be")
    db.record_pattern_failure(uid, "to be")
    p = db.get_pattern_progress(uid)[0]
    assert (p["jumlah_salah"], p["streak_benar"], p["sudah_dikuasai"]) == (1, 0, False)


def test_hitung_sesi_hari_ini_dan_topik(bersihkan):
    uid = new_user()["id"]
    topics = db.list_topics_with_history(uid, "pemula")
    assert len(topics) == 6, "jalankan seed.sql"
    db.create_session(uid, topics[0]["id"], None, ["to be"])
    assert db.count_sessions_today(uid) == 1
    assert db.list_topics_with_history(uid, "pemula")[0]["kali_dipelajari"] == 1


def test_error_log_terbaru_dulu(bersihkan):
    uid = new_user()["id"]
    sid = db.create_session(uid, None, "interview magang", [])
    db.insert_mistake(uid, sid, "I go", "I went", "grammar", "simple past")
    db.insert_mistake(uid, sid, "a apple", "an apple", "grammar", "article a/an")
    log = db.get_error_log(uid)
    assert [m["kalimat_benar"] for m in log] == ["an apple", "I went"]


def test_hapus_pengguna_ikut_menghapus_datanya(bersihkan):
    uid = new_user()["id"]
    sid = db.create_session(uid, None, "presentasi kelas", [])
    db.insert_mistake(uid, sid, "x", "y", "grammar", "p")
    Pelajar.objects.filter(pk=uid).delete()
    assert Kesalahan.objects.filter(user_id=uid).count() == 0
