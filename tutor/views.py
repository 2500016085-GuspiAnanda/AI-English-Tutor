"""View Django: menerjemahkan HTTP <-> fungsi agen. Pengganti app.py (FastAPI).

View = fungsi yang menerima `request` dan mengembalikan `response`. Alamat URL mana memanggil view
mana diatur di tutor/urls.py. Logika agen sama persis dengan CLI; file ini hanya "penerjemah".

Server tetap STATELESS: state percakapan disimpan di sessions.state (PostgreSQL), bukan di memori,
karena di serverless request berikutnya bisa ditangani instance yang berbeda.
"""

import itertools
import logging
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path

from django.http import FileResponse, HttpResponseBase, JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from openai import APIError
from pydantic import ValidationError

import db
import tts
from agent import (DEFAULT_PERSONA, MAX_TURNS, STATIC_PROMPT, ChatState, build_dynamic_prompt, finish_chat,
                   send_user_message, start_chat)
from main import MAX_SESSIONS_PER_DAY
from placement import LETTERS, QUESTIONS, grade
from planner import plan_session
from tools import SessionContext

from .schemas import LoginIn, MessageIn, PersonaIn, PlacementIn, TtsIn, UserIn

log = logging.getLogger(__name__)
TTS_SESSION_WINDOW = timedelta(hours=6)
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"   # index.html + static/


class ApiError(Exception):
    """Pengganti HTTPException FastAPI: raise ApiError(404, "...") -> {"detail": "..."} berstatus 404."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def api(method: str, schema=None):
    """Decorator untuk semua endpoint JSON. Mengerjakan yang dulu otomatis di FastAPI:

    1. tolak metode HTTP yang salah (405);
    2. baca body JSON dan validasi dengan model Pydantic `schema` (gagal -> 422, bentuk sama dengan FastAPI);
    3. ubah ApiError dan error layanan LLM jadi JSON berstatus yang sesuai;
    4. ubah nilai kembalian (dict/list) jadi JsonResponse; response yang sudah jadi (mis. audio) diteruskan apa adanya.

    csrf_exempt: perlindungan CSRF Django ditujukan untuk login berbasis cookie. API ini tidak memakai
    cookie (pengguna dikenali dari user_id di body), jadi pemeriksaan token CSRF dimatikan di sini.
    """
    def decorator(fn):
        @wraps(fn)
        def view(request, *args, **kwargs):
            if request.method != method:
                return JsonResponse({"detail": "metode tidak diizinkan"}, status=405)
            try:
                if schema is not None:
                    try:
                        kwargs["body"] = schema.model_validate_json(request.body or b"{}")
                    except ValidationError as e:
                        errors = [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()]
                        return JsonResponse({"detail": errors}, status=422)
                result = fn(request, *args, **kwargs)
                if isinstance(result, HttpResponseBase):
                    return result
                return JsonResponse(result, safe=False)   # safe=False: boleh list
            except ApiError as e:
                return JsonResponse({"detail": e.detail}, status=e.status)
            except APIError:
                return JsonResponse({"detail": "Layanan AI sedang bermasalah, coba lagi sebentar."}, status=502)
        return csrf_exempt(view)
    return decorator


# --- Helper ------------------------------------------------------------------------------

def _user_or_404(user_id: int) -> dict:
    user = db.get_user(user_id)
    if user is None:
        raise ApiError(404, "pengguna tidak ditemukan")
    return user


def _load_chat(session_id: int, user_id: int) -> ChatState:
    row = db.load_chat_state(session_id)
    if row is None or row["state"] is None or row["state"]["closed"]:
        raise ApiError(404, "sesi tidak ditemukan atau sudah berakhir")
    if row["user_id"] != user_id:
        raise ApiError(403, "sesi ini milik pengguna lain")
    return ChatState.from_json(row["state"], row["user_id"], session_id)


def _run(session_id: int, user_id: int, fn, *args) -> tuple[ChatState, str, int]:
    """Muat state dari DB, jalankan satu giliran agen, simpan lagi.

    Kunci sesi di DB mencegah dua pesan diproses bersamaan, termasuk bila keduanya jatuh ke
    instance server yang berbeda. Kembalikan (state, balasan, lama_proses_ms).
    """
    _load_chat(session_id, user_id)                   # 404/403 sebelum mengunci
    if not db.try_lock_session(session_id):
        raise ApiError(409, "pesan sebelumnya masih diproses")
    try:
        state = _load_chat(session_id, user_id)       # muat ulang SETELAH terkunci: pasti versi terbaru
        state.ctx.new_turn()
        t0 = time.perf_counter()
        reply = fn(state, *args)
        server_ms = _ms_since(t0)
        db.save_chat_state(session_id, state.to_json())
        return state, reply, server_ms
    finally:
        db.unlock_session(session_id)


def _ms_since(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def _chat_response(state: ChatState, reply: str, server_ms: int, user_turn: bool = False) -> dict:
    ctx = state.ctx
    out = {
        "reply": reply, "turn": state.turn, "max_turns": MAX_TURNS, "selesai": state.closed,
        "mood": ctx.mood(user_turn and not state.closed),
        "koreksi": ctx.turn_corrections,  # kalimat asli -> benar, langsung dari tool save_mistake
        # Info kecepatan & jejak agen untuk giliran ini
        "stats": {"server_ms": server_ms, "llm_calls": ctx.turn_llm_calls, "tools": ctx.turn_tools},
    }
    if state.closed:
        out["ringkasan"] = ctx.ringkasan
        out["progres"] = db.get_pattern_progress(ctx.user_id)
    return out


# --- Endpoint ----------------------------------------------------------------------------

def home(request):
    """Halaman web (satu halaman HTML + JS). Di Vercel disajikan langsung oleh CDN."""
    return FileResponse(open(PUBLIC_DIR / "index.html", "rb"), content_type="text/html; charset=utf-8")


@api("POST", LoginIn)
def login(request, body: LoginIn):
    user = db.get_or_create_user(body.username.lower())
    used = db.count_sessions_today(user["id"])
    return {**user, "sesi_hari_ini": used, "batas_sesi": MAX_SESSIONS_PER_DAY}


@api("GET")
def placement_questions(request):
    # Kunci jawaban sengaja TIDAK dikirim ke browser; penilaian hanya di server.
    return [{"no": i, "soal": q["soal"], "opsi": dict(zip(LETTERS, q["opsi"]))} for i, q in enumerate(QUESTIONS, 1)]


@api("POST", PlacementIn)
def placement(request, body: PlacementIn):
    user = _user_or_404(body.user_id)
    if user["sudah_tes"]:
        raise ApiError(409, "tes penempatan sudah pernah dilakukan")
    score, level = (None, "pemula") if body.answers is None else grade(body.answers)
    db.set_placement(user["id"], level)
    return {"skor": score, "level": level}


@api("POST", PersonaIn)
def set_persona(request, body: PersonaIn):
    """Simpan gaya mentor pilihan pengguna; berlaku mulai sesi berikutnya."""
    _user_or_404(body.user_id)
    db.set_persona(body.user_id, body.persona)
    return {"persona": body.persona}


@api("POST", UserIn)
def start_session(request, body: UserIn):
    user = _user_or_404(body.user_id)
    if not user["sudah_tes"]:
        raise ApiError(409, "ikuti tes penempatan terlebih dahulu")
    if db.count_sessions_today(user["id"]) >= MAX_SESSIONS_PER_DAY:
        raise ApiError(429, f"batas {MAX_SESSIONS_PER_DAY} sesi per hari sudah tercapai")

    plan, topic, progress, errors = plan_session(user)
    if user["level"] == "pemula" and topic is None:
        raise ApiError(500, "kurikulum pemula kosong, jalankan seed.sql")
    session_id = db.create_session(user["id"], topic["id"] if topic else None, plan.skenario, plan.fokus_pola)

    persona = user["persona_default"] or DEFAULT_PERSONA
    prompt = STATIC_PROMPT + "\n" + build_dynamic_prompt(
        user, topic, plan.skenario, plan.fokus_pola, progress, errors, web=True, persona=persona)
    ctx = SessionContext(user_id=user["id"], session_id=session_id, persona=persona)
    t0 = time.perf_counter()
    state, reply = start_chat(ctx, prompt)
    server_ms = _ms_since(t0)
    db.save_chat_state(session_id, state.to_json())

    return {
        "session_id": session_id,
        "level": user["level"],
        "topik": topic["judul"] if topic else None,
        "skenario": plan.skenario,
        "fokus_pola": plan.fokus_pola,
        "persona": persona,
        **_chat_response(state, reply, server_ms),
    }


@api("POST", MessageIn)
def send_message(request, session_id: int, body: MessageIn):
    state, reply, server_ms = _run(session_id, body.user_id, send_user_message, body.text)
    return _chat_response(state, reply, server_ms, user_turn=True)


@api("POST", UserIn)
def end_session(request, session_id: int, body: UserIn):
    state, reply, server_ms = _run(session_id, body.user_id, finish_chat)
    return _chat_response(state, reply, server_ms)


@api("POST", TtsIn)
def speech(request, body: TtsIn):
    """Suara tutor dari Gemini TTS, dialirkan sepotong demi sepotong (PCM 16-bit mono 24 kHz).

    Potongan pertama diambil DULU sebelum response dikirim: kalau Gemini gagal, browser menerima status
    error yang jelas (lalu memakai suara browser sebagai cadangan), bukan audio kosong berstatus 200.

    Pembatasan: kuota Gemini terbatas, jadi suara hanya dilayani untuk sesi milik pelajar ini yang dibuat
    dalam TTS_SESSION_WINDOW terakhir (masih cukup untuk "Putar ulang" sesudah sesi selesai).
    """
    if not tts.available():
        raise ApiError(503, "suara Gemini belum aktif: GEMINI_API_KEY belum diisi")
    sesi = db.get_session_owner(body.session_id)
    if sesi is None:
        raise ApiError(404, "sesi tidak ditemukan")
    if sesi["user_id"] != body.user_id:
        raise ApiError(403, "sesi ini milik pengguna lain")
    if sesi["created_at"] < timezone.now() - TTS_SESSION_WINDOW:
        raise ApiError(403, "sesi sudah terlalu lama; suara Gemini hanya untuk sesi yang baru berjalan")
    chunks = tts.stream_speech(body.text, body.mood, body.persona)
    try:
        first = next(chunks)
    except StopIteration:
        raise ApiError(502, "layanan suara tidak mengembalikan audio")
    except tts.QuotaExceeded:
        raise ApiError(429, "kuota suara Gemini habis; sementara memakai suara browser")
    except Exception:
        log.exception("Gemini TTS gagal")
        raise ApiError(502, "layanan suara sedang bermasalah")
    response = StreamingHttpResponse(itertools.chain([first], chunks),
                                     content_type=f"audio/L16; rate={tts.SAMPLE_RATE}; channels=1")
    response["Cache-Control"] = "no-store"
    return response


@api("GET")
def memory(request, user_id: int):
    """Isi panel 'Catatan tutor': memori jangka panjang agen yang tersimpan di database."""
    _user_or_404(user_id)
    return {
        "progres": db.get_pattern_progress(user_id),
        "kesalahan": db.get_error_log(user_id, limit=5),
    }
