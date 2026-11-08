"""Tes API + loop agen dengan LLM tiruan (lihat FakeLLM di conftest.py).

Alur nyata dari request HTTP sampai ke database diuji, tanpa memanggil DeepSeek.
"""

import pytest
from fastapi.testclient import TestClient

import db
from app import app
from tests.conftest import PREFIX, llm_text, llm_tools

MISTAKE = {"kalimat_asli": "I go to campus yesterday", "kalimat_benar": "I went to campus yesterday",
           "kategori": "grammar", "pola": "Simple Past"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:   # menjalankan lifespan: membuka connection pool
        yield c


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

def test_alur_login_dan_tes_penempatan(client, conn):
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


def test_gaya_mentor(client, conn):
    uid = login(client, "api_persona")
    assert client.post("/api/persona", json={"user_id": uid, "persona": "marah"}).status_code == 422
    assert client.post("/api/persona", json={"user_id": uid, "persona": "lembut"}).status_code == 200
    assert client.post("/api/login", json={"username": PREFIX + "api_persona"}).json()["persona_default"] == "lembut"


def test_halaman_dan_file_statis_tersaji(client):
    for path, kind in [("/", "text/html"), ("/static/style.css", "text/css"), ("/static/app.js", "javascript")]:
        # lokal disajikan FastAPI dari public/; di Vercel file yang sama disajikan CDN
        r = client.get(path)
        assert r.status_code == 200 and kind in r.headers["content-type"]


# --- Loop agen ----------------------------------------------------------------------------

def test_sesi_penuh_salah_lalu_rekap(client, conn, fake_llm):
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
    assert db.load_chat_state(conn, s["session_id"])["state"]["closed"] is True
    assert say(client, uid, s["session_id"], "hi").status_code == 404   # sesi selesai tidak bisa dilanjutkan

    # Riwayat percakapan tersimpan di tabel messages
    roles = [m["role"] for m in conn.execute(
        "SELECT role FROM messages WHERE session_id = %s ORDER BY id", (s["session_id"],)).fetchall()]
    assert roles.count("tool") == 2 and roles[0] == "user"


def test_gaya_lembut_saat_salah_berekspresi_koreksi(client, conn, fake_llm):
    uid = login(client, "api_lembut", persona="lembut")
    s = start(client, uid, fake_llm)
    assert s["persona"] == "lembut"
    assert "Gaya mentor: lembut" in fake_llm.calls[-1][0]["content"]   # gaya masuk ke system prompt
    fake_llm.queue += [llm_tools(("save_mistake", MISTAKE)), llm_text("Good try! Use 'went'.")]
    assert say(client, uid, s["session_id"], "I go to campus yesterday").json()["mood"] == "koreksi"


def test_kalimat_benar_berekspresi_senang(client, conn, fake_llm):
    uid = login(client, "api_benar")
    s = start(client, uid, fake_llm)
    fake_llm.queue.append(llm_text("Perfect sentence!"))
    r = say(client, uid, s["session_id"], "My name is Budi.").json()
    assert r["mood"] == "senang" and r["koreksi"] == []


def test_argumen_tool_salah_dikembalikan_ke_agen_lalu_sesi_lanjut(client, conn, fake_llm):
    uid = login(client, "api_badtool")
    s = start(client, uid, fake_llm)
    fake_llm.queue += [llm_tools(("save_mistake", MISTAKE | {"kategori": "spelling"})), llm_text("Let's go on.")]
    r = say(client, uid, s["session_id"], "hello").json()
    assert r["reply"] == "Let's go on." and r["koreksi"] == []
    tool_result = next(m for m in fake_llm.calls[-1] if m["role"] == "tool")
    assert "argumen tidak valid" in tool_result["content"]   # agen melihat error-nya


def test_streak_naik_saat_pola_benar_lalu_sesi_ditutup(client, conn, fake_llm):
    uid = login(client, "api_streak")
    s = start(client, uid, fake_llm)
    fake_llm.queue += [llm_tools(("mark_progress", {"pola": "to be", "benar": True})), llm_text("Nice!")]
    say(client, uid, s["session_id"], "I am Budi.")
    fake_llm.queue += [llm_tools(("end_session", {"ringkasan": "ok"})), llm_text("Bye")]
    end = client.post(f"/api/sessions/{s['session_id']}/end", json={"user_id": uid}).json()
    assert [(p["pola"], p["streak_benar"]) for p in end["progres"]] == [("to be", 1)]


def test_sesi_otomatis_selesai_setelah_10_giliran(client, conn, fake_llm):
    uid = login(client, "api_10")
    s = start(client, uid, fake_llm)
    for _ in range(9):
        assert say(client, uid, s["session_id"], "ok").json()["selesai"] is False
    fake_llm.queue += [llm_text("Last reply."), llm_tools(("end_session", {"ringkasan": "10 giliran"})), llm_text("Bye")]
    r = say(client, uid, s["session_id"], "ok").json()
    assert (r["turn"], r["selesai"], r["ringkasan"]) == (10, True, "10 giliran")


def test_planner_ngawur_tetap_bisa_mulai_sesi(client, conn, fake_llm):
    uid = login(client, "api_planner")
    fake_llm.plan = "ini bukan JSON"
    s = start(client, uid, fake_llm)
    assert s["topik"] == "Perkenalan diri"   # rencana cadangan deterministik


# --- Stateless: state di database, bukan di memori server ---------------------------------

def test_state_sesi_tersimpan_di_database(client, conn, fake_llm):
    uid = login(client, "api_state")
    s = start(client, uid, fake_llm)
    fake_llm.queue.append(llm_text("Nice."))
    say(client, uid, s["session_id"], "My name is Budi.")
    state = db.load_chat_state(conn, s["session_id"])["state"]
    assert state["turn"] == 1 and state["closed"] is False
    assert [m["role"] for m in state["messages"]][:2] == ["system", "user"]
    # Riwayat dari DB benar-benar dikirim lagi ke LLM di giliran berikutnya
    say(client, uid, s["session_id"], "I like football.")
    assert any(m.get("content") == "My name is Budi." for m in fake_llm.calls[-1])


def test_kunci_sesi_menolak_pesan_bersamaan(client, conn, fake_llm):
    uid = login(client, "api_lock")
    s = start(client, uid, fake_llm)
    assert db.try_lock_session(conn, s["session_id"])       # seolah request lain sedang memproses
    assert say(client, uid, s["session_id"], "hi").status_code == 409
    db.unlock_session(conn, s["session_id"])
    assert say(client, uid, s["session_id"], "hi").status_code == 200
    assert conn.execute("SELECT busy_until FROM sessions WHERE id = %s",
                        (s["session_id"],)).fetchone()["busy_until"] is None   # kunci dilepas setelah selesai


def test_kunci_kedaluwarsa_tidak_membuat_sesi_macet(client, conn, fake_llm):
    uid = login(client, "api_stale")
    s = start(client, uid, fake_llm)
    # Simulasi server mati di tengah proses: kunci tertinggal tetapi sudah lewat waktunya
    conn.execute("UPDATE sessions SET busy_until = now() - interval '1 second' WHERE id = %s", (s["session_id"],))
    assert say(client, uid, s["session_id"], "hi").status_code == 200


# --- Keamanan & batas ---------------------------------------------------------------------

def test_sesi_orang_lain_403_dan_sesi_hilang_404(client, conn, fake_llm):
    uid = login(client, "api_owner")
    s = start(client, uid, fake_llm)
    assert say(client, uid + 999, s["session_id"], "hi").status_code == 403
    assert say(client, uid, 987654, "hi").status_code == 404


def test_batas_3_sesi_per_hari(client, conn, fake_llm):
    uid = login(client, "api_limit")
    for _ in range(3):
        db.create_session(conn, uid, None, "interview magang", [])
    r = client.post("/api/sessions", json={"user_id": uid})
    assert r.status_code == 429


def test_pesan_kosong_atau_terlalu_panjang_ditolak(client, conn, fake_llm):
    uid = login(client, "api_len")
    s = start(client, uid, fake_llm)
    assert say(client, uid, s["session_id"], "").status_code == 422
    assert say(client, uid, s["session_id"], "a" * 1001).status_code == 422
