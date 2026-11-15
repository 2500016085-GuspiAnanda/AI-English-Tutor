"""Fixture bersama untuk semua tes.

Tes database dan API memakai PostgreSQL sungguhan (DATABASE_URL di .env). Semua pengguna
buatan tes diberi awalan "pytest_" dan dihapus otomatis setelah tes selesai.
"""

import json
from types import SimpleNamespace as NS

import pytest

import db  # noqa: F401  (import db menyiapkan Django sebelum model dipakai)
from tutor.models import Pelajar

PREFIX = "pytest_"


class JsonClient:
    """Pembungkus django.test.Client agar tes memanggil API seperti sebelumnya: client.post(url, json={...}).

    Request diproses lengkap oleh Django (urls -> view -> database) tanpa menyalakan server sungguhan.
    """

    def __init__(self):
        from django.test import Client
        self._client = Client(HTTP_HOST="localhost")   # host harus ada di ALLOWED_HOSTS

    def get(self, url):
        return self._client.get(url)

    def post(self, url, json=None):
        return self._client.post(url, data={} if json is None else json, content_type="application/json")


@pytest.fixture(scope="module")
def client():
    return JsonClient()


@pytest.fixture
def bersihkan():
    """Hapus semua pengguna buatan tes setelah tes selesai (sesi, pesan, kesalahan ikut terhapus: DB_CASCADE)."""
    yield
    Pelajar.objects.filter(username__startswith=PREFIX).delete()


# --- LLM tiruan ---------------------------------------------------------------------------
# Jawaban DeepSeek asli berbeda-beda, lambat, dan berbayar. Di tes, call_llm diganti fungsi
# yang jawabannya sudah diskrip, sehingga yang diuji adalah KODE KITA: loop agen, eksekusi
# tool, penyimpanan ke DB, mood, dan data koreksi.

def llm_text(content: str):
    """Balasan LLM berupa teks biasa (tanpa tool call)."""
    msg = NS(content=content, tool_calls=None)
    return NS(model="fake-llm", usage=NS(prompt_tokens=100, completion_tokens=20), choices=[NS(message=msg)])


def llm_tools(*calls: tuple[str, dict]):
    """Balasan LLM yang meminta satu atau lebih tool: llm_tools(("save_mistake", {...}), ...)."""
    tool_calls = [
        NS(id=f"call_{i}", type="function", function=NS(name=name, arguments=json.dumps(args)))
        for i, (name, args) in enumerate(calls)
    ]
    msg = NS(content="", tool_calls=tool_calls)
    return NS(model="fake-llm", usage=NS(prompt_tokens=100, completion_tokens=20), choices=[NS(message=msg)])


class FakeLLM:
    """Antrean jawaban: tiap panggilan call_llm mengambil satu jawaban dari depan antrean."""

    def __init__(self):
        self.queue: list = []
        self.plan = {"topic_urutan": 1, "skenario": None, "fokus_pola": ["to be"], "alasan": "tes"}
        self.calls: list[list[dict]] = []   # salinan messages tiap panggilan, untuk diperiksa tes

    def __call__(self, messages, tools=None, json_mode=False):
        self.calls.append([dict(m) for m in messages])
        if json_mode:   # planner
            content = self.plan if isinstance(self.plan, str) else json.dumps(self.plan)
            return llm_text(content)
        return self.queue.pop(0) if self.queue else llm_text("Okay. Tell me more.")


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("agent.call_llm", fake)
    monkeypatch.setattr("planner.call_llm", fake)
    return fake
