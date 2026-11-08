"""API web (M4). Logika agen sama dengan CLI; file ini hanya menerjemahkan HTTP <-> fungsi agen.

Jalankan  : uv run uvicorn app:app --reload
Coba API  : buka http://127.0.0.1:8000/docs
"""

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import APIError
from pydantic import BaseModel, Field

import db
from agent import (DEFAULT_PERSONA, MAX_TURNS, STATIC_PROMPT, ChatState, build_dynamic_prompt, finish_chat,
                   send_user_message, start_chat)
from main import MAX_SESSIONS_PER_DAY
from placement import LETTERS, QUESTIONS, grade
from planner import plan_session
from tools import SessionContext

STATIC_DIR = Path(__file__).parent / "static"
pool = db.make_pool()

# Sesi yang sedang berjalan, disimpan di memori server: session_id -> ChatState.
# Konsekuensi: jika server restart, sesi yang sedang berjalan hilang (data di DB tetap aman).
CHATS: dict[int, ChatState] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open(wait=True)   # buka koneksi DB saat server menyala
    yield
    pool.close()           # tutup saat server dimatikan


app = FastAPI(title="AI English Tutor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")   # style.css, app.js


@app.exception_handler(APIError)
def llm_error(request: Request, exc: APIError):
    return JSONResponse(status_code=502, content={"detail": "Layanan AI sedang bermasalah, coba lagi sebentar."})


# --- Bentuk data request (divalidasi otomatis oleh FastAPI lewat Pydantic) ---------------

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")


class UserIn(BaseModel):
    user_id: int


class PlacementIn(UserIn):
    answers: Annotated[list[Literal["a", "b", "c", "d"]], Field(min_length=5, max_length=5)] | None = Field(
        default=None, description="5 huruf jawaban; null = mulai dari nol sebagai pemula")


class PersonaIn(UserIn):
    persona: Literal["galak", "lembut"]


class MessageIn(UserIn):
    text: str = Field(min_length=1, max_length=1000)


# --- Helper ------------------------------------------------------------------------------

def _user_or_404(conn, user_id: int) -> dict:
    user = db.get_user(conn, user_id)
    if user is None:
        raise HTTPException(404, "pengguna tidak ditemukan")
    return user


def _chat_or_error(session_id: int, user_id: int) -> ChatState:
    state = CHATS.get(session_id)
    if state is None:
        raise HTTPException(404, "sesi tidak ditemukan atau sudah berakhir")
    if state.ctx.user_id != user_id:
        raise HTTPException(403, "sesi ini milik pengguna lain")
    return state


def _run(state: ChatState, fn, *args) -> tuple[str, int]:
    """Pinjam koneksi DB selama agen bekerja, dan tolak pesan kedua selagi pesan pertama diproses.

    Kembalikan (balasan, lama_proses_ms).
    """
    if not state.lock.acquire(blocking=False):
        raise HTTPException(409, "pesan sebelumnya masih diproses")
    try:
        with pool.connection() as conn:
            state.ctx.conn = conn
            state.ctx.new_turn()
            t0 = time.perf_counter()
            try:
                return fn(state, *args), _ms_since(t0)
            finally:
                state.ctx.conn = None  # koneksi kembali ke pool
    finally:
        state.lock.release()


def _ms_since(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def _chat_response(session_id: int, state: ChatState, reply: str, server_ms: int, user_turn: bool = False) -> dict:
    ctx = state.ctx
    out = {
        "reply": reply, "turn": state.turn, "max_turns": MAX_TURNS, "selesai": state.closed,
        "mood": ctx.mood(user_turn and not state.closed),
        "koreksi": ctx.turn_corrections,  # kalimat asli -> benar, langsung dari tool save_mistake
        # Info kecepatan & jejak agen untuk giliran ini
        "stats": {"server_ms": server_ms, "llm_calls": ctx.turn_llm_calls, "tools": ctx.turn_tools},
    }
    if state.closed:
        CHATS.pop(session_id, None)
        with pool.connection() as conn:
            out["ringkasan"] = state.ctx.ringkasan
            out["progres"] = db.get_pattern_progress(conn, state.ctx.user_id)
    return out


# --- Endpoint ----------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/login")
def login(body: LoginIn):
    with pool.connection() as conn:
        user = db.get_or_create_user(conn, body.username.lower())
        used = db.count_sessions_today(conn, user["id"])
    return {**user, "sesi_hari_ini": used, "batas_sesi": MAX_SESSIONS_PER_DAY}


@app.get("/api/placement/questions")
def placement_questions():
    # Kunci jawaban sengaja TIDAK dikirim ke browser; penilaian hanya di server.
    return [{"no": i, "soal": q["soal"], "opsi": dict(zip(LETTERS, q["opsi"]))} for i, q in enumerate(QUESTIONS, 1)]


@app.post("/api/placement")
def placement(body: PlacementIn):
    with pool.connection() as conn:
        user = _user_or_404(conn, body.user_id)
        if user["sudah_tes"]:
            raise HTTPException(409, "tes penempatan sudah pernah dilakukan")
        score, level = (None, "pemula") if body.answers is None else grade(body.answers)
        db.set_placement(conn, user["id"], level)
    return {"skor": score, "level": level}


@app.post("/api/persona")
def set_persona(body: PersonaIn):
    """Simpan gaya mentor pilihan pengguna; berlaku mulai sesi berikutnya."""
    with pool.connection() as conn:
        _user_or_404(conn, body.user_id)
        db.set_persona(conn, body.user_id, body.persona)
    return {"persona": body.persona}


@app.post("/api/sessions")
def start_session(body: UserIn):
    with pool.connection() as conn:
        user = _user_or_404(conn, body.user_id)
        if not user["sudah_tes"]:
            raise HTTPException(409, "ikuti tes penempatan terlebih dahulu")
        if db.count_sessions_today(conn, user["id"]) >= MAX_SESSIONS_PER_DAY:
            raise HTTPException(429, f"batas {MAX_SESSIONS_PER_DAY} sesi per hari sudah tercapai")

        plan, topic, progress, errors = plan_session(conn, user)
        if user["level"] == "pemula" and topic is None:
            raise HTTPException(500, "kurikulum pemula kosong, jalankan seed.sql")
        session_id = db.create_session(conn, user["id"], topic["id"] if topic else None, plan.skenario, plan.fokus_pola)

        persona = user["persona_default"] or DEFAULT_PERSONA
        prompt = STATIC_PROMPT + "\n" + build_dynamic_prompt(
            user, topic, plan.skenario, plan.fokus_pola, progress, errors, web=True, persona=persona)
        ctx = SessionContext(conn=conn, user_id=user["id"], session_id=session_id, persona=persona)
        t0 = time.perf_counter()
        state, reply = start_chat(ctx, prompt)
        server_ms = _ms_since(t0)
        ctx.conn = None

    CHATS[session_id] = state
    return {
        "session_id": session_id,
        "level": user["level"],
        "topik": topic["judul"] if topic else None,
        "skenario": plan.skenario,
        "fokus_pola": plan.fokus_pola,
        "persona": persona,
        **_chat_response(session_id, state, reply, server_ms),
    }


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: int, body: MessageIn):
    state = _chat_or_error(session_id, body.user_id)
    reply, server_ms = _run(state, send_user_message, body.text)
    return _chat_response(session_id, state, reply, server_ms, user_turn=True)


@app.post("/api/sessions/{session_id}/end")
def end_session(session_id: int, body: UserIn):
    state = _chat_or_error(session_id, body.user_id)
    reply, server_ms = _run(state, finish_chat)
    return _chat_response(session_id, state, reply, server_ms)


@app.get("/api/users/{user_id}/memory")
def memory(user_id: int):
    """Isi panel 'Yang diingat tentang kamu': memori jangka panjang agen yang tersimpan di database."""
    with pool.connection() as conn:
        _user_or_404(conn, user_id)
        return {
            "progres": db.get_pattern_progress(conn, user_id),
            "kesalahan": db.get_error_log(conn, user_id, limit=5),
        }
