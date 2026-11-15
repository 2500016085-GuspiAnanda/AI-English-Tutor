"""Bentuk data request API, divalidasi Pydantic (dipindah apa adanya dari app.py FastAPI).

Django punya Forms untuk validasi, tetapi Forms dirancang untuk form HTML. API kita menerima JSON
dan proyek ini sudah memakai Pydantic (argumen tool agen), jadi Pydantic tetap dipakai di sini.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, Field


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


class TtsIn(UserIn):
    session_id: int     # suara hanya untuk sesi milik pelajar ini (lihat views.speech)
    text: str = Field(min_length=1, max_length=2000)
    mood: Literal["netral", "senang", "marah", "koreksi"] = "netral"
    persona: Literal["galak", "lembut"] = "galak"
