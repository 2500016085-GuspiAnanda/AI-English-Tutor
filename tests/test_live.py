"""Tes langsung ke DeepSeek: memeriksa PERILAKU model, yang tidak bisa diuji dengan LLM tiruan.

Dilewati secara default (berbayar, lambat, dan jawabannya bisa berbeda-beda). Jalankan dengan:
    RUN_LIVE=1 uv run pytest tests/test_live.py -v        (PowerShell: $env:RUN_LIVE=1; uv run pytest ...)

Regresi yang dijaga: instruksi prompt pernah membuat model berhenti memanggil save_mistake,
sehingga kesalahan pengguna tidak tersimpan. Tes ini memastikan itu tidak terulang di kedua gaya mentor.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app import app
from tests.conftest import PREFIX

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="tes live: set RUN_LIVE=1")

WRONG = "Yesterday I go to the market and I buyed some fruits."


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("persona, expected_mood", [("galak", "marah"), ("lembut", "koreksi")])
def test_model_memanggil_save_mistake_untuk_kalimat_salah(client, conn, persona, expected_mood):
    uid = client.post("/api/login", json={"username": f"{PREFIX}live_{persona}"}).json()["id"]
    client.post("/api/placement", json={"user_id": uid, "answers": None})
    client.post("/api/persona", json={"user_id": uid, "persona": persona})
    sid = client.post("/api/sessions", json={"user_id": uid}).json()["session_id"]

    r = client.post(f"/api/sessions/{sid}/messages", json={"user_id": uid, "text": WRONG}).json()

    assert "save_mistake" in r["stats"]["tools"], f"model tidak mencatat kesalahan. Balasan: {r['reply'][:200]}"
    assert r["mood"] == expected_mood
    fixes = " ".join(k["kalimat_benar"].lower() for k in r["koreksi"])
    assert "went" in fixes and "bought" in fixes
