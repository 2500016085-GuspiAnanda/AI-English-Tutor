"""Tes panel admin: setiap halaman daftar & form terbuka tanpa error untuk admin yang login.

Akun admin di sini hanya untuk tes (tanpa password, login lewat force_login) dan dihapus setelah tes.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

import db
from tests.conftest import PREFIX
from tutor.models import Pelajar, Sesi


@pytest.fixture
def admin_client(bersihkan):
    User = get_user_model()
    admin_user = User.objects.create_superuser(username=PREFIX + "admin", email=None, password=None)
    c = Client(HTTP_HOST="localhost")
    c.force_login(admin_user)
    yield c
    admin_user.delete()


def test_halaman_admin_butuh_login():
    r = Client(HTTP_HOST="localhost").get("/admin/tutor/pelajar/")
    assert r.status_code == 302 and "/admin/login/" in r["Location"]


@pytest.mark.parametrize("model", ["pelajar", "topik", "sesi", "pesan", "kesalahan", "progrespola"])
def test_daftar_setiap_model_terbuka(admin_client, model):
    assert admin_client.get(f"/admin/tutor/{model}/").status_code == 200


def test_halaman_pelajar_dan_sesi_beserta_isinya(admin_client):
    uid = db.get_or_create_user(PREFIX + "admin_data")["id"]
    sid = db.create_session(uid, None, "interview magang", ["simple past"])
    db.save_message(sid, "user", "I go to campus yesterday")
    db.insert_mistake(uid, sid, "I go to campus yesterday", "I went to campus yesterday", "grammar", "simple past")
    db.record_pattern_failure(uid, "simple past")

    pelajar = admin_client.get(f"/admin/tutor/pelajar/{uid}/change/")
    assert pelajar.status_code == 200 and b"simple past" in pelajar.content       # inline progres pola
    sesi = admin_client.get(f"/admin/tutor/sesi/{sid}/change/")
    assert sesi.status_code == 200 and b"I went to campus yesterday" in sesi.content  # inline kesalahan
    cari = admin_client.get("/admin/tutor/pelajar/", {"q": PREFIX + "admin_data"})
    assert PREFIX.encode() + b"admin_data" in cari.content
    assert Pelajar.objects.filter(pk=uid).exists() and Sesi.objects.filter(pk=sid).exists()
