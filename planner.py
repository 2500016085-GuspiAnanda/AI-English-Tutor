"""Planner: 1 panggilan LLM sebelum sesi untuk memilih topik/skenario dan 1-2 pola fokus.

Output LLM divalidasi Pydantic. Jika tidak valid, dipakai rencana deterministik
(topik berikutnya + pola terlemah) agar sesi tetap bisa berjalan.
"""

import json

from pydantic import BaseModel, Field, ValidationError, field_validator

import db
from llm import call_llm

SKENARIO = ["interview magang", "presentasi kelas"]

# Bagian statis di depan (kena prompt cache), data pengguna di belakang.
STATIC_PROMPT = """\
Kamu adalah planner untuk tutor bahasa Inggris mahasiswa Indonesia. Tugasmu memilih materi
untuk SATU sesi percakapan berikutnya berdasarkan data pengguna.

Aturan:
- Level pemula: pilih satu topik kurikulum lewat "topic_urutan". Utamakan topik yang belum
  pernah dipelajari secara berurutan; boleh mengulang topik lama bila cocok untuk melatih
  pola yang masih lemah.
- Level menengah/lanjut: pilih satu "skenario" dari daftar yang diberikan.
- Pilih 1-2 "fokus_pola": utamakan pola belum dikuasai dengan kesalahan terbanyak atau yang
  baru muncul. Jangan pilih pola yang sudah dikuasai. Jika belum ada data, pilih 1-2 pola
  yang paling relevan dengan topik/skenario.
- Nama pola: bahasa Inggris, huruf kecil, singkat (mis. "to be", "simple past", "article a/an").
  Jika pola sudah ada di data progres, pakai nama yang persis sama.
- "alasan": 1 kalimat Bahasa Indonesia.

Balas HANYA dengan objek JSON:
{"topic_urutan": <int atau null>, "skenario": <string atau null>, "fokus_pola": [<string>], "alasan": <string>}
"""


class Plan(BaseModel):
    topic_urutan: int | None = None
    skenario: str | None = None
    fokus_pola: list[str] = Field(min_length=1, max_length=2)
    alasan: str = ""

    @field_validator("fokus_pola")
    @classmethod
    def _norm(cls, v: list[str]) -> list[str]:
        v = [" ".join(p.lower().split()) for p in v]
        if not all(v):
            raise ValueError("pola tidak boleh kosong")
        return list(dict.fromkeys(v))  # buang duplikat, urutan tetap


def _dynamic_prompt(user: dict, topics: list[dict], progress: list[dict], errors: list[dict]) -> str:
    data = {
        "level": user["level"],
        "topik_kurikulum": [
            {"urutan": t["urutan"], "judul": t["judul"], "kali_dipelajari": t["kali_dipelajari"]} for t in topics
        ] if user["level"] == "pemula" else None,
        "skenario_tersedia": SKENARIO if user["level"] != "pemula" else None,
        "progres_pola": [
            {"pola": p["pola"], "jumlah_salah": p["jumlah_salah"], "streak": p["streak_benar"],
             "dikuasai": p["sudah_dikuasai"]} for p in progress
        ],
        "kesalahan_terakhir": [{"pola": e["pola"], "kalimat": e["kalimat_asli"]} for e in errors[:10]],
    }
    return "Data pengguna:\n" + json.dumps(data, ensure_ascii=False, default=str)


def _fallback(user: dict, topics: list[dict], progress: list[dict]) -> Plan:
    open_ = sorted((p for p in progress if not p["sudah_dikuasai"]), key=lambda p: p["jumlah_salah"], reverse=True)
    fokus = [p["pola"] for p in open_[:2]] or ["to be"]
    if user["level"] == "pemula":
        nxt = next((t for t in topics if t["kali_dipelajari"] == 0), topics[0] if topics else None)
        return Plan(topic_urutan=nxt["urutan"] if nxt else None, fokus_pola=fokus, alasan="rencana cadangan (deterministik)")
    return Plan(skenario=SKENARIO[0], fokus_pola=fokus, alasan="rencana cadangan (deterministik)")


def _check(plan: Plan, user: dict, topics: list[dict]) -> Plan:
    """Validasi semantik di luar skema: topik/skenario harus ada di daftar yang ditawarkan."""
    if user["level"] == "pemula":
        if plan.topic_urutan not in {t["urutan"] for t in topics}:
            raise ValueError(f"topic_urutan {plan.topic_urutan} tidak ada di kurikulum")
        plan.skenario = None
    else:
        if plan.skenario not in SKENARIO:
            raise ValueError(f"skenario '{plan.skenario}' tidak tersedia")
        plan.topic_urutan = None
    return plan


def plan_session(conn, user: dict, debug: bool = False) -> tuple[Plan, dict | None, list[dict], list[dict]]:
    """Kembalikan (plan, topic_row_atau_None, progress, errors)."""
    topics = db.list_topics_with_history(conn, user["id"], user["level"]) if user["level"] == "pemula" else []
    progress = db.get_pattern_progress(conn, user["id"])
    errors = db.get_error_log(conn, user["id"], limit=10)

    messages = [
        {"role": "system", "content": STATIC_PROMPT},
        {"role": "user", "content": _dynamic_prompt(user, topics, progress, errors)},
    ]
    try:
        resp = call_llm(messages, json_mode=True)
        raw = resp.choices[0].message.content or ""
        if debug:
            print(f"   [planner] {raw}")
        plan = _check(Plan.model_validate_json(raw), user, topics)
    except (ValidationError, ValueError) as e:
        if debug:
            print(f"   [planner] output tidak valid, pakai rencana cadangan: {e}")
        plan = _fallback(user, topics, progress)

    topic = next((t for t in topics if t["urutan"] == plan.topic_urutan), None)
    return plan, topic, progress, errors
