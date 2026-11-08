"""API web. Logika agen sama dengan CLI; file ini hanya menerjemahkan HTTP <-> fungsi agen.

Jalankan  : uv run uvicorn app:app --reload
Coba API  : buka http://127.0.0.1:8000/docs
Deploy    : Vercel (FastAPI berjalan sebagai Vercel Function; file di public/ disajikan CDN)

Server ini STATELESS: state percakapan disimpan di sessions.state (PostgreSQL), bukan di memori,
karena di Vercel request berikutnya bisa ditangani instance yang berbeda. Bonus: sesi tetap utuh
walau server restart.
"""

import threading
import time
from contextlib import asynccontextmanager, contextmanager
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

PUBLIC_DIR = Path(__file__).parent / "public"   # index.html + static/ (di Vercel disajikan langsung oleh CDN)
pool = db.make_pool()
_pool_lock = threading.Lock()


@contextmanager
def db_conn():
    """Pinjam satu koneksi dari pool. Pool dibuka saat pertama dibutuhkan, karena di lingkungan
    serverless lifespan belum tentu dijalankan sebelum request pertama."""
    if pool.closed:
        with _pool_lock:
            if pool.closed:
                pool.open(wait=True)
    with pool.connection() as conn:
        yield conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if not pool.closed:
        pool.close()


app = FastAPI(title="AI English Tutor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PUBLIC_DIR / "static"), name="static")   # untuk lokal


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


def _load_chat(conn, session_id: int, user_id: int) -> ChatState:
    row = db.load_chat_state(conn, session_id)
    if row is None or row["state"] is None or row["state"]["closed"]:
        raise HTTPException(404, "sesi tidak ditemukan atau sudah berakhir")
    if row["user_id"] != user_id:
        raise HTTPException(403, "sesi ini milik pengguna lain")
    return ChatState.from_json(row["state"], row["user_id"], session_id)


def _run(session_id: int, user_id: int, fn, *args) -> tuple[ChatState, str, int]:
    """Muat state dari DB, jalankan satu giliran agen, simpan lagi.

    Kunci sesi di DB mencegah dua pesan diproses bersamaan, termasuk bila keduanya jatuh ke
    instance server yang berbeda. Kembalikan (state, balasan, lama_proses_ms).
    """
    with db_conn() as conn:
        _load_chat(conn, session_id, user_id)                 # 404/403 sebelum mengunci
        if not db.try_lock_session(conn, session_id):
            raise HTTPException(409, "pesan sebelumnya masih diproses")
        try:
            state = _load_chat(conn, session_id, user_id)     # muat ulang SETELAH terkunci: pasti versi terbaru
            state.ctx.conn = conn
            state.ctx.new_turn()
            t0 = time.perf_counter()
            reply = fn(state, *args)
            server_ms = _ms_since(t0)
            db.save_chat_state(conn, session_id, state.to_json())
            state.ctx.conn = None
            return state, reply, server_ms
        finally:
            db.unlock_session(conn, session_id)


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
        with db_conn() as conn:
            out["ringkasan"] = ctx.ringkasan
            out["progres"] = db.get_pattern_progress(conn, ctx.user_id)
    return out


# --- Endpoint ----------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(PUBLIC_DIR / "index.html")


@app.post("/api/login")
def login(body: LoginIn):
    with db_conn() as conn:
        user = db.get_or_create_user(conn, body.username.lower())
        used = db.count_sessions_today(conn, user["id"])
    return {**user, "sesi_hari_ini": used, "batas_sesi": MAX_SESSIONS_PER_DAY}


@app.get("/api/placement/questions")
def placement_questions():
    # Kunci jawaban sengaja TIDAK dikirim ke browser; penilaian hanya di server.
    return [{"no": i, "soal": q["soal"], "opsi": dict(zip(LETTERS, q["opsi"]))} for i, q in enumerate(QUESTIONS, 1)]


@app.post("/api/placement")
def placement(body: PlacementIn):
    with db_conn() as conn:
        user = _user_or_404(conn, body.user_id)
        if user["sudah_tes"]:
            raise HTTPException(409, "tes penempatan sudah pernah dilakukan")
        score, level = (None, "pemula") if body.answers is None else grade(body.answers)
        db.set_placement(conn, user["id"], level)
    return {"skor": score, "level": level}


@app.post("/api/persona")
def set_persona(body: PersonaIn):
    """Simpan gaya mentor pilihan pengguna; berlaku mulai sesi berikutnya."""
    with db_conn() as conn:
        _user_or_404(conn, body.user_id)
        db.set_persona(conn, body.user_id, body.persona)
    return {"persona": body.persona}


@app.post("/api/sessions")
def start_session(body: UserIn):
    with db_conn() as conn:
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
        db.save_chat_state(conn, session_id, state.to_json())
        ctx.conn = None

    return {
        "session_id": session_id,
        "level": user["level"],
        "topik": topic["judul"] if topic else None,
        "skenario": plan.skenario,
        "fokus_pola": plan.fokus_pola,
        "persona": persona,
        **_chat_response(state, reply, server_ms),
    }


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: int, body: MessageIn):
    state, reply, server_ms = _run(session_id, body.user_id, send_user_message, body.text)
    return _chat_response(state, reply, server_ms, user_turn=True)


@app.post("/api/sessions/{session_id}/end")
def end_session(session_id: int, body: UserIn):
    state, reply, server_ms = _run(session_id, body.user_id, finish_chat)
    return _chat_response(state, reply, server_ms)


@app.get("/api/users/{user_id}/memory")
def memory(user_id: int):
    """Isi panel 'Yang diingat tentang kamu': memori jangka panjang agen yang tersimpan di database."""
    with db_conn() as conn:
        _user_or_404(conn, user_id)
        return {
            "progres": db.get_pattern_progress(conn, user_id),
            "kesalahan": db.get_error_log(conn, user_id, limit=5),
        }
