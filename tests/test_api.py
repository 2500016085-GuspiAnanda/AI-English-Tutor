"""Tes API + loop agen dengan LLM tiruan (lihat FakeLLM di conftest.py).

Alur nyata dari request HTTP sampai ke database diuji, tanpa memanggil DeepSeek.
"""

from datetime import timedelta

import pytest

from django.db.models.functions import Now

import db
from tests.conftest import PREFIX, llm_text, llm_tools
from tutor.models import Pesan, Sesi

MISTAKE = {"kalimat_asli": "I go to campus yesterday", "kalimat_benar": "I went to campus yesterday",
           "kategori": "grammar", "pola": "Simple Past"}


def login(client, name, placement=True, persona=None):
    user = client.post("/api/login", json={"username": PREFIX + name}).json()
    if placement:
        client.post("/api/placement", json={"user_id": user["id"], "answers": None})
    if persona:
        client.post("/api/persona", json={"user_id": user["id"], "persona": persona})
    return user["id"]


def start(client, uid, fake_llm, greeting="Hi! What's your name?"):
    fake_llm.queue.append(llm_text(greeting))
    r = client.post("/api/sessions", json={"user_id": uid})
    assert r.status_code == 200, r.text
    return r.json()


def say(client, uid, sid, text):
    return client.post(f"/api/sessions/{sid}/messages", json={"user_id": uid, "text": text})


# --- Login, tes penempatan, gaya mentor -------------------------------------------------

def test_alur_login_dan_tes_penempatan(client, bersihkan):
    uid = login(client, "api_a", placement=False)
    assert client.post("/api/sessions", json={"user_id": uid}).status_code == 409   # belum tes
    bad = client.post("/api/placement", json={"user_id": uid, "answers": ["a", "z"]})
    assert bad.status_code == 422                                                     # Pydantic menolak
    ok = client.post("/api/placement", json={"user_id": uid, "answers": ["b", "c", "c", "b", "c"]})
    assert ok.json() == {"skor": 5, "level": "lanjut"}
    assert client.post("/api/placement", json={"user_id": uid, "answers": None}).status_code == 409


def test_kunci_jawaban_tidak_dikirim_ke_browser(client):
    soal = client.get("/api/placement/questions").json()
    assert len(soal) == 5 and all("jawaban" not in q for q in soal)


@pytest.mark.parametrize("username", ["", "a b", "<script>", "x" * 41])
def test_username_tidak_valid_ditolak(client, username):
    assert client.post("/api/login", json={"username": username}).status_code == 422


def test_gaya_mentor(client, bersihkan):
    uid = login(client, "api_persona")
    assert client.post("/api/persona", json={"user_id": uid, "persona": "marah"}).status_code == 422
    assert client.post("/api/persona", json={"user_id": uid, "persona": "lembut"}).status_code == 200
    assert client.post("/api/login", json={"username": PREFIX + "api_persona"}).json()["persona_default"] == "lembut"


def test_halaman_dan_file_statis_tersaji(client):
    for path, kind in [("/", "text/html"), ("/static/style.css", "text/css"), ("/static/app.js", "javascript")]:
        # lokal disajikan Django dari public/; di Vercel file yang sama disajikan CDN
        r = client.get(path)
        assert r.status_code == 200 and kind in r.headers["content-type"]


# --- Loop agen ----------------------------------------------------------------------------

def test_sesi_penuh_salah_lalu_rekap(client, bersihkan, fake_llm):
    uid = login(client, "api_full")
    s = start(client, uid, fake_llm)
    assert (s["mood"], s["topik"], s["persona"], s["fokus_pola"]) == ("netral", "Perkenalan diri", "galak", ["to be"])

    # Agen: panggil save_mistake, lalu balas teks
    fake_llm.queue += [llm_tools(("save_mistake", MISTAKE)), llm_text("Use the past tense!")]
    r = say(client, uid, s["session_id"], "I go to campus yesterday").json()
    assert r["mood"] == "marah"
    assert r["koreksi"][0]["kalimat_benar"] == "I went to campus yesterday"
    assert r["stats"]["llm_calls"] == 2 and r["stats"]["tools"] == ["save_mistake"]
    assert r["turn"] == 1 and r["selesai"] is False

    # Kesalahan benar-benar tersimpan, dengan nama pola yang sudah dinormalisasi
    mem = client.get(f"/api/users/{uid}/memory").json()
    assert mem["kesalahan"][0]["pola"] == "simple past"
    assert mem["progres"][0]["jumlah_salah"] == 1

    # Akhiri sesi: agen memanggil end_session
    fake_llm.queue += [llm_tools(("end_session", {"ringkasan": "1 kesalahan: simple past."})), llm_text("Bye!")]
    end = client.post(f"/api/sessions/{s['session_id']}/end", json={"user_id": uid}).json()
    assert end["selesai"] is True and end["ringkasan"] == "1 kesalahan: simple past."
    assert db.load_chat_state(s["session_id"])["state"]["closed"] is True
    assert say(client, uid, s["session_id"], "hi").status_code == 404   # sesi selesai tidak bisa dilanjutkan

    # Riwayat percakapan tersimpan di tabel messages
    roles = list(Pesan.objects.filter(session_id=s["session_id"]).order_by("id").values_list("role", flat=True))
    assert roles.count("tool") == 2 and roles[0] == "user"


def test_gaya_lembut_saat_salah_berekspresi_koreksi(client, bersihkan, fake_llm):
    uid = login(client, "api_lembut", persona="lembut")
    s = start(client, uid, fake_llm)
    assert s["persona"] == "lembut"
    assert "Gaya mentor: lembut" in fake_llm.calls[-1][0]["content"]   # gaya masuk ke system prompt
    fake_llm.queue += [llm_tools(("save_mistake", MISTAKE)), llm_text("Good try! Use 'went'.")]
    assert say(client, uid, s["session_id"], "I go to campus yesterday").json()["mood"] == "koreksi"


def test_kalimat_benar_berekspresi_senang(client, bersihkan, fake_llm):
    uid = login(client, "api_benar")
    s = start(client, uid, fake_llm)
    fake_llm.queue.append(llm_text("Perfect sentence!"))
    r = say(client, uid, s["session_id"], "My name is Budi.").json()
    assert r["mood"] == "senang" and r["koreksi"] == []


def test_argumen_tool_salah_dikembalikan_ke_agen_lalu_sesi_lanjut(client, bersihkan, fake_llm):
    uid = login(client, "api_badtool")
    s = start(client, uid, fake_llm)
    fake_llm.queue += [llm_tools(("save_mistake", MISTAKE | {"kategori": "spelling"})), llm_text("Let's go on.")]
    r = say(client, uid, s["session_id"], "hello").json()
    assert r["reply"] == "Let's go on." and r["koreksi"] == []
    tool_result = next(m for m in fake_llm.calls[-1] if m["role"] == "tool")
    assert "argumen tidak valid" in tool_result["content"]   # agen melihat error-nya


def test_streak_naik_saat_pola_benar_lalu_sesi_ditutup(client, bersihkan, fake_llm):
    uid = login(client, "api_streak")
    s = start(client, uid, fake_llm)
    fake_llm.queue += [llm_tools(("mark_progress", {"pola": "to be", "benar": True})), llm_text("Nice!")]
    say(client, uid, s["session_id"], "I am Budi.")
    fake_llm.queue += [llm_tools(("end_session", {"ringkasan": "ok"})), llm_text("Bye")]
    end = client.post(f"/api/sessions/{s['session_id']}/end", json={"user_id": uid}).json()
    assert [(p["pola"], p["streak_benar"]) for p in end["progres"]] == [("to be", 1)]


def test_sesi_otomatis_selesai_setelah_10_giliran(client, bersihkan, fake_llm):
    uid = login(client, "api_10")
    s = start(client, uid, fake_llm)
    for _ in range(9):
        assert say(client, uid, s["session_id"], "ok").json()["selesai"] is False
    fake_llm.queue += [llm_text("Last reply."), llm_tools(("end_session", {"ringkasan": "10 giliran"})), llm_text("Bye")]
    r = say(client, uid, s["session_id"], "ok").json()
    assert (r["turn"], r["selesai"], r["ringkasan"]) == (10, True, "10 giliran")


def test_planner_ngawur_tetap_bisa_mulai_sesi(client, bersihkan, fake_llm):
    uid = login(client, "api_planner")
    fake_llm.plan = "ini bukan JSON"
    s = start(client, uid, fake_llm)
    assert s["topik"] == "Perkenalan diri"   # rencana cadangan deterministik


# --- Stateless: state di database, bukan di memori server ---------------------------------

def test_state_sesi_tersimpan_di_database(client, bersihkan, fake_llm):
    uid = login(client, "api_state")
    s = start(client, uid, fake_llm)
    fake_llm.queue.append(llm_text("Nice."))
    say(client, uid, s["session_id"], "My name is Budi.")
    state = db.load_chat_state(s["session_id"])["state"]
    assert state["turn"] == 1 and state["closed"] is False
    assert [m["role"] for m in state["messages"]][:2] == ["system", "user"]
    # Riwayat dari DB benar-benar dikirim lagi ke LLM di giliran berikutnya
    say(client, uid, s["session_id"], "I like football.")
    assert any(m.get("content") == "My name is Budi." for m in fake_llm.calls[-1])


def test_kunci_sesi_menolak_pesan_bersamaan(client, bersihkan, fake_llm):
    uid = login(client, "api_lock")
    s = start(client, uid, fake_llm)
    assert db.try_lock_session(s["session_id"])       # seolah request lain sedang memproses
    assert say(client, uid, s["session_id"], "hi").status_code == 409
    db.unlock_session(s["session_id"])
    assert say(client, uid, s["session_id"], "hi").status_code == 200
    assert Sesi.objects.get(pk=s["session_id"]).busy_until is None   # kunci dilepas setelah selesai


def test_kunci_kedaluwarsa_tidak_membuat_sesi_macet(client, bersihkan, fake_llm):
    uid = login(client, "api_stale")
    s = start(client, uid, fake_llm)
    # Simulasi server mati di tengah proses: kunci tertinggal tetapi sudah lewat waktunya
    Sesi.objects.filter(pk=s["session_id"]).update(busy_until=Now() - timedelta(seconds=1))
    assert say(client, uid, s["session_id"], "hi").status_code == 200


# --- Keamanan & batas ---------------------------------------------------------------------

def test_sesi_orang_lain_403_dan_sesi_hilang_404(client, bersihkan, fake_llm):
    uid = login(client, "api_owner")
    s = start(client, uid, fake_llm)
    assert say(client, uid + 999, s["session_id"], "hi").status_code == 403
    assert say(client, uid, 987654, "hi").status_code == 404


def test_batas_3_sesi_per_hari(client, bersihkan, fake_llm):
    uid = login(client, "api_limit")
    for _ in range(3):
        db.create_session(uid, None, "interview magang", [])
    r = client.post("/api/sessions", json={"user_id": uid})
    assert r.status_code == 429


def test_pesan_kosong_atau_terlalu_panjang_ditolak(client, bersihkan, fake_llm):
    uid = login(client, "api_len")
    s = start(client, uid, fake_llm)
    assert say(client, uid, s["session_id"], "").status_code == 422
    assert say(client, uid, s["session_id"], "a" * 1001).status_code == 422


# --- Suara tutor (Gemini TTS, ditiru agar tes gratis) -------------------------------------

@pytest.fixture
def sesi_tts(bersihkan):
    """Pelajar + sesi miliknya: /api/tts hanya melayani pemilik sesi yang masih baru."""
    uid = db.get_or_create_user(PREFIX + "tts")["id"]
    return {"user_id": uid, "session_id": db.create_session(uid, None, "interview magang", [])}


def test_tts_tanpa_key_503_agar_browser_memakai_suara_cadangan(client, monkeypatch, sesi_tts):
    monkeypatch.setattr("tts.available", lambda: False)
    assert client.post("/api/tts", json={"text": "Hi", **sesi_tts}).status_code == 503


def test_tts_mengalirkan_audio_dan_meneruskan_mood_dan_gaya(client, monkeypatch, sesi_tts):
    diterima = {}

    def fake_stream(text, mood, persona):
        diterima.update(text=text, mood=mood, persona=persona)
        yield b"\x01\x00"
        yield b"\x02\x00"

    monkeypatch.setattr("tts.available", lambda: True)
    monkeypatch.setattr("tts.stream_speech", fake_stream)
    r = client.post("/api/tts", json={"text": "Stop. Itu salah.", "mood": "marah", "persona": "galak", **sesi_tts})
    assert r.status_code == 200 and r["Content-Type"].startswith("audio/L16")
    assert b"".join(r.streaming_content) == b"\x01\x00\x02\x00"
    assert diterima == {"text": "Stop. Itu salah.", "mood": "marah", "persona": "galak"}


def test_tts_layanan_gagal_502_bukan_audio_kosong(client, monkeypatch, sesi_tts):
    def rusak(text, mood, persona):
        raise RuntimeError("layanan error")
        yield  # noqa: menjadikannya generator

    monkeypatch.setattr("tts.available", lambda: True)
    monkeypatch.setattr("tts.stream_speech", rusak)
    assert client.post("/api/tts", json={"text": "Hi", **sesi_tts}).status_code == 502


def test_tts_kuota_habis_429_agar_browser_berhenti_mencoba(client, monkeypatch, sesi_tts):
    import tts

    def habis(text, mood, persona):
        raise tts.QuotaExceeded("429 RESOURCE_EXHAUSTED")
        yield  # noqa: menjadikannya generator

    monkeypatch.setattr("tts.available", lambda: True)
    monkeypatch.setattr("tts.stream_speech", habis)
    r = client.post("/api/tts", json={"text": "Hi", **sesi_tts})
    assert r.status_code == 429 and "kuota" in r.json()["detail"]


def test_tts_hanya_untuk_pemilik_sesi_yang_masih_baru(client, monkeypatch, sesi_tts):
    """Kuota Gemini terbatas: orang lain, sesi tak dikenal, atau sesi lama tidak boleh memakainya."""
    monkeypatch.setattr("tts.available", lambda: True)
    monkeypatch.setattr("tts.stream_speech", lambda text, mood, persona: iter([b"\x00\x00"]))
    lain = {**sesi_tts, "user_id": sesi_tts["user_id"] + 999}
    assert client.post("/api/tts", json={"text": "Hi", **lain}).status_code == 403
    assert client.post("/api/tts", json={"text": "Hi", **sesi_tts, "session_id": 987654}).status_code == 404
    assert client.post("/api/tts", json={"text": "Hi"}).status_code == 422          # tanpa sesi sama sekali
    Sesi.objects.filter(pk=sesi_tts["session_id"]).update(created_at=Now() - timedelta(hours=7))
    assert client.post("/api/tts", json={"text": "Hi", **sesi_tts}).status_code == 403
