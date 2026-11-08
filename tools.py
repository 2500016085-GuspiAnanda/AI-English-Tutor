"""Definisi 4 tool agen + eksekutornya. Argumen dari LLM selalu divalidasi Pydantic."""

import json
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

import db


def _norm_pola(v: str) -> str:
    """Samakan penulisan pola agar 'Simple  Past' dan 'simple past' jadi satu baris."""
    v = " ".join(v.lower().split())
    if not v:
        raise ValueError("pola tidak boleh kosong")
    return v


class SaveMistake(BaseModel):
    kalimat_asli: str = Field(description="Kalimat pengguna persis seperti yang ditulis.")
    kalimat_benar: str = Field(description="Versi kalimat yang benar.")
    kategori: Literal["grammar", "vocabulary", "word_choice", "sentence_structure"]
    pola: str = Field(description="Nama pola singkat dalam bahasa Inggris, huruf kecil, mis. 'simple past', 'to be', 'article a/an'.")

    _v = field_validator("pola")(_norm_pola)


class GetErrorLog(BaseModel):
    user_id: int = Field(description="ID pengguna yang sedang belajar.")


class MarkProgress(BaseModel):
    pola: str = Field(description="Nama pola, sama persis dengan yang dipakai di save_mistake.")
    benar: bool = Field(description="true jika pengguna memakai pola ini dengan benar.")

    _v = field_validator("pola")(_norm_pola)


class EndSession(BaseModel):
    ringkasan: str = Field(description="Rekap sesi: 3 kesalahan utama, 1 hal yang sudah bagus, status pola fokus.")


def _tool(name: str, desc: str, model: type[BaseModel]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": model.model_json_schema()}}


# Urutan dan isi daftar ini statis -> ikut di prefix yang di-cache.
TOOLS = [
    _tool("save_mistake", "Simpan satu kesalahan bahasa Inggris pengguna. Panggil sekali per kesalahan, sebelum mengoreksi.", SaveMistake),
    _tool("get_error_log", "Ambil 20 kesalahan terakhir pengguna dari sesi-sesi sebelumnya.", GetErrorLog),
    _tool("mark_progress", "Catat bahwa pengguna memakai sebuah pola dengan benar (benar=true) atau salah (benar=false).", MarkProgress),
    _tool("end_session", "Akhiri sesi dan simpan rekap. Panggil setelah giliran terakhir atau bila pengguna minta berhenti.", EndSession),
]
MODELS = {"save_mistake": SaveMistake, "get_error_log": GetErrorLog, "mark_progress": MarkProgress, "end_session": EndSession}


@dataclass
class SessionContext:
    conn: object
    user_id: int
    session_id: int
    failed: set[str] = field(default_factory=set)   # pola yang salah di sesi ini
    correct: set[str] = field(default_factory=set)  # pola yang dipakai benar di sesi ini
    ended: bool = False
    ringkasan: str | None = None
    # Catatan per giliran (direset oleh new_turn): dipakai web untuk ekspresi wajah & info kecepatan
    turn_mistakes: int = 0
    turn_correct: int = 0
    turn_tools: list[str] = field(default_factory=list)
    turn_llm_calls: int = 0
    turn_corrections: list[dict] = field(default_factory=list)  # data save_mistake giliran ini (untuk "coretan pena merah")

    def new_turn(self) -> None:
        self.turn_mistakes = self.turn_correct = self.turn_llm_calls = 0
        self.turn_tools = []
        self.turn_corrections = []

    def mood(self, user_turn: bool = False) -> str:
        """Ekspresi tutor diambil dari keputusan agen sendiri (tool yang dipanggil), bukan ditebak dari teks.

        user_turn=True: pengguna baru saja mengirim kalimat; tanpa save_mistake berarti kalimatnya benar.
        """
        if self.turn_mistakes:
            return "marah"
        if self.turn_correct or user_turn:
            return "senang"
        return "netral"


def execute_tool(ctx: SessionContext, name: str, arguments: str) -> str:
    """Jalankan tool dan kembalikan hasil berupa string JSON untuk dikirim balik ke LLM.

    Error validasi dikembalikan sebagai pesan, bukan exception, agar agen bisa memperbaiki argumennya.
    """
    model = MODELS.get(name)
    if model is None:
        return _out(error=f"tool '{name}' tidak dikenal")
    try:
        args = model.model_validate_json(arguments or "{}")
    except ValidationError as e:
        return _out(error="argumen tidak valid", detail=e.errors(include_url=False, include_context=False))

    if isinstance(args, SaveMistake):
        mid = db.insert_mistake(ctx.conn, ctx.user_id, ctx.session_id, args.kalimat_asli, args.kalimat_benar, args.kategori, args.pola)
        db.record_pattern_failure(ctx.conn, ctx.user_id, args.pola)
        ctx.failed.add(args.pola)
        ctx.turn_mistakes += 1
        ctx.turn_corrections.append(args.model_dump())
        return _out(ok=True, mistake_id=mid)

    if isinstance(args, GetErrorLog):
        if args.user_id != ctx.user_id:
            return _out(error="hanya boleh membaca error log pengguna yang sedang aktif", user_id=ctx.user_id)
        return _out(ok=True, mistakes=db.get_error_log(ctx.conn, ctx.user_id))

    if isinstance(args, MarkProgress):
        if args.benar:
            ctx.correct.add(args.pola)  # streak baru dihitung di finalize_progress (sekali per sesi)
            ctx.turn_correct += 1
        elif args.pola not in ctx.failed:
            db.record_pattern_failure(ctx.conn, ctx.user_id, args.pola)
            ctx.failed.add(args.pola)
        return _out(ok=True)

    if isinstance(args, EndSession):
        db.end_session(ctx.conn, ctx.session_id, args.ringkasan)
        ctx.ended, ctx.ringkasan = True, args.ringkasan
        return _out(ok=True)


def finalize_progress(ctx: SessionContext) -> list[dict]:
    """Naikkan streak untuk pola yang benar dan tidak pernah salah di sesi ini."""
    return [db.record_pattern_success(ctx.conn, ctx.user_id, p) for p in sorted(ctx.correct - ctx.failed)]


def _out(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False, default=str)
