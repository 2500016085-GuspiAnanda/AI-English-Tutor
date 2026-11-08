"""Tes unit: logika murni, tanpa database dan tanpa LLM. Cepat dan selalu hasilnya sama."""

import json

import pytest
from pydantic import ValidationError

from agent import PERSONAS, WEB_UI_NOTE, build_dynamic_prompt
from placement import QUESTIONS, grade, score_to_level
from planner import Plan, _check, _fallback
from tools import TOOLS, SaveMistake, SessionContext, execute_tool


# --- Tes penempatan -----------------------------------------------------------------------

@pytest.mark.parametrize("score, level", [(0, "pemula"), (2, "pemula"), (3, "menengah"), (4, "menengah"), (5, "lanjut")])
def test_batas_skor_ke_level(score, level):
    assert score_to_level(score) == level


def test_grade_menghitung_jawaban_benar():
    kunci = [q["jawaban"] for q in QUESTIONS]
    assert grade(kunci) == (5, "lanjut")
    assert grade(["x"] * 5) == (0, "pemula")
    assert grade(kunci[:3] + ["x", "x"]) == (3, "menengah")


# --- Validasi argumen tool (Pydantic) -------------------------------------------------------

def test_nama_pola_dinormalisasi():
    m = SaveMistake(kalimat_asli="a", kalimat_benar="b", kategori="grammar", pola="  Simple   PAST ")
    assert m.pola == "simple past"


@pytest.mark.parametrize("bad", [
    {"kategori": "spelling"},   # kategori di luar daftar
    {"pola": "   "},            # pola kosong
])
def test_argumen_tidak_valid_ditolak(bad):
    args = {"kalimat_asli": "a", "kalimat_benar": "b", "kategori": "grammar", "pola": "to be"} | bad
    with pytest.raises(ValidationError):
        SaveMistake(**args)


def test_skema_tool_lengkap():
    assert [t["function"]["name"] for t in TOOLS] == ["save_mistake", "get_error_log", "mark_progress", "end_session"]


def test_error_validasi_dikembalikan_ke_agen_bukan_crash():
    ctx = SessionContext(conn=None, user_id=1, session_id=1)
    out = json.loads(execute_tool(ctx, "save_mistake", '{"kalimat_asli": "x"}'))
    assert out["error"] == "argumen tidak valid"
    assert ctx.turn_mistakes == 0


def test_tool_tidak_dikenal():
    ctx = SessionContext(conn=None, user_id=1, session_id=1)
    assert "tidak dikenal" in json.loads(execute_tool(ctx, "hapus_semua", "{}"))["error"]


def test_get_error_log_menolak_pengguna_lain():
    ctx = SessionContext(conn=None, user_id=7, session_id=1)
    out = json.loads(execute_tool(ctx, "get_error_log", '{"user_id": 8}'))
    assert "error" in out and out["user_id"] == 7


def test_mark_progress_benar_tidak_menyentuh_db():
    ctx = SessionContext(conn=None, user_id=1, session_id=1)   # conn=None: kalau DB disentuh, tes gagal
    execute_tool(ctx, "mark_progress", '{"pola": "To Be", "benar": true}')
    assert ctx.correct == {"to be"} and ctx.turn_correct == 1


# --- Mood (ekspresi wajah) ---------------------------------------------------------------

@pytest.mark.parametrize("persona, mistakes, correct, user_turn, expected", [
    ("galak", 1, 0, True, "marah"),
    ("lembut", 1, 0, True, "koreksi"),     # mentor lembut tidak marah
    ("galak", 0, 1, False, "senang"),
    ("galak", 0, 0, True, "senang"),       # kalimat pengguna tanpa kesalahan = benar
    ("galak", 0, 0, False, "netral"),      # sapaan pembuka / penutup
])
def test_mood(persona, mistakes, correct, user_turn, expected):
    ctx = SessionContext(conn=None, user_id=1, session_id=1, persona=persona)
    ctx.turn_mistakes, ctx.turn_correct = mistakes, correct
    assert ctx.mood(user_turn) == expected


def test_new_turn_mereset_catatan_giliran():
    ctx = SessionContext(conn=None, user_id=1, session_id=1)
    ctx.turn_mistakes, ctx.turn_tools, ctx.turn_corrections = 2, ["save_mistake"], [{"x": 1}]
    ctx.new_turn()
    assert (ctx.turn_mistakes, ctx.turn_tools, ctx.turn_corrections) == (0, [], [])


# --- Planner ------------------------------------------------------------------------------

TOPICS = [{"urutan": 1, "judul": "A", "kali_dipelajari": 1}, {"urutan": 2, "judul": "B", "kali_dipelajari": 0}]
PEMULA, MENENGAH = {"level": "pemula"}, {"level": "menengah"}


def test_plan_normalisasi_dan_buang_duplikat():
    assert Plan(topic_urutan=1, fokus_pola=["To Be", "to  be"]).fokus_pola == ["to be"]


@pytest.mark.parametrize("fokus", [[], ["a", "b", "c"]])
def test_plan_jumlah_pola_harus_1_sampai_2(fokus):
    with pytest.raises(ValidationError):
        Plan(topic_urutan=1, fokus_pola=fokus)


def test_check_menolak_topik_dan_skenario_karangan():
    with pytest.raises(ValueError):
        _check(Plan(topic_urutan=99, fokus_pola=["x"]), PEMULA, TOPICS)
    with pytest.raises(ValueError):
        _check(Plan(skenario="debat politik", fokus_pola=["x"]), MENENGAH, [])


def test_check_membersihkan_field_yang_tidak_berlaku():
    plan = _check(Plan(topic_urutan=2, skenario="interview magang", fokus_pola=["x"]), PEMULA, TOPICS)
    assert plan.skenario is None and plan.topic_urutan == 2


def test_rencana_cadangan_pilih_topik_belum_dipelajari_dan_pola_terlemah():
    progress = [
        {"pola": "article", "jumlah_salah": 1, "sudah_dikuasai": False},
        {"pola": "to be", "jumlah_salah": 5, "sudah_dikuasai": False},
        {"pola": "plural", "jumlah_salah": 9, "sudah_dikuasai": True},   # sudah dikuasai: dilewati
    ]
    plan = _fallback(PEMULA, TOPICS, progress)
    assert plan.topic_urutan == 2 and plan.fokus_pola == ["to be", "article"]


def test_rencana_cadangan_tidak_crash_bila_kurikulum_kosong():
    assert _fallback(PEMULA, [], []).topic_urutan is None


# --- Prompt -------------------------------------------------------------------------------

USER = {"id": 3, "username": "budi", "level": "pemula"}


@pytest.mark.parametrize("persona", ["galak", "lembut"])
def test_prompt_memuat_gaya_mentor(persona):
    prompt = build_dynamic_prompt(USER, None, "interview magang", ["to be"], [], [], persona=persona)
    assert prompt.startswith(PERSONAS[persona])


def test_prompt_gaya_tidak_dikenal_jatuh_ke_galak():
    assert build_dynamic_prompt(USER, None, "x", ["a"], [], [], persona="aneh").startswith(PERSONAS["galak"])


def test_catatan_web_hanya_di_web_dan_tidak_menyebut_koreksi_otomatis():
    assert WEB_UI_NOTE in build_dynamic_prompt(USER, None, "x", ["a"], [], [], web=True)
    assert WEB_UI_NOTE not in build_dynamic_prompt(USER, None, "x", ["a"], [], [])
    # Regresi: kalimat "koreksi tampil otomatis" pernah membuat model berhenti memanggil save_mistake.
    assert "otomatis" not in WEB_UI_NOTE.lower()
