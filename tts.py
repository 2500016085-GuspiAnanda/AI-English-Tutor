"""TTS Gemini: balasan tutor dibacakan dengan intonasi sesuai mood giliran dan gaya mentor.

Suara browser (Web Speech API) hanya bisa mengatur kecepatan dan tinggi nada secara rata, jadi terdengar datar.
Gemini TTS "berakting" mengikuti catatan sutradara, dan kalimat campuran Indonesia-Inggris dibaca dalam satu suara.

Pengaturan berasal dari uji dengar yang disetujui pengguna (2026-11-15):
- model gemini-3.8-flash-tts, suara Bodi (galak) / Fola (lembut)
- naskah berformat "## Director's notes:" + "## Transcript:" seperti di AI Studio
- API v1beta: versi bawaan library (v1) menolak speech_config dengan error 400

Keluaran: potongan audio PCM 16-bit mono 24 kHz (little-endian), dialirkan begitu tersedia.
"""

import os
import warnings

from dotenv import load_dotenv

with warnings.catch_warnings():   # google-genai memicu SyntaxWarning di Python 3.14; tidak berbahaya
    warnings.simplefilter("ignore", SyntaxWarning)
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

load_dotenv()

MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
SAMPLE_RATE = 24000
VOICES = {"galak": "Bodi", "lembut": "Fola"}

_DASAR = ("Kamu tutor bahasa Inggris dari Indonesia untuk mahasiswa. Bicara dengan logat Indonesia yang natural. "
          "Kata atau kalimat bahasa Inggris diucapkan dengan pelafalan Inggris yang jelas dan sedikit lebih pelan "
          "supaya mudah ditiru. ")

# Catatan sutradara per (gaya mentor, mood giliran). Mood berasal dari tool yang dipanggil agen (tools.py).
NOTES = {
    ("galak", "marah"): "Kamu galak tapi peduli pada muridnya. Nada kesal dan tegas seperti dosen yang menegur, "
                        "tempo agak cepat, beri tekanan pada kata yang menunjukkan kesalahan.",
    ("lembut", "koreksi"): "Kamu sabar dan hangat. Suara tersenyum dan menenangkan, tempo santai; "
                           "koreksi disampaikan dengan lembut tanpa menghakimi.",
    ("galak", "senang"): "Kamu galak, tapi kali ini puas karena muridnya menjawab benar. Nada lega dan sedikit "
                         "bangga, tetap lugas.",
    ("lembut", "senang"): "Kamu sabar dan hangat, dan senang sekali muridnya menjawab benar. Nada ceria, bangga, "
                          "dan menyemangati.",
    ("galak", "netral"): "Kamu tegas dan lugas, tidak bertele-tele, tetapi tidak sedang kesal.",
    ("lembut", "netral"): "Kamu ramah, sabar, dan hangat.",
}
# Suara nonverbal di awal transkrip (tag Gemini TTS)
TAGS = {"marah": "<sigh> ", "senang": "<chuckles> "}

_client = None


class QuotaExceeded(Exception):
    """Kuota Gemini habis (HTTP 429). Paket gratis: hanya 10 permintaan suara per hari per model."""


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                               http_options=types.HttpOptions(api_version="v1beta"))
    return _client


def script(text: str, mood: str = "netral", persona: str = "galak") -> str:
    """Naskah untuk Gemini: catatan sutradara terpisah dari teks yang diucapkan."""
    persona = persona if persona in VOICES else "galak"
    notes = NOTES.get((persona, mood)) or NOTES[(persona, "netral")]
    return f"## Director's notes:\n{_DASAR}{notes}\n\n## Transcript:\n{TAGS.get(mood, '')}{text}\n"


def stream_speech(text: str, mood: str = "netral", persona: str = "galak"):
    """Generator potongan audio PCM. Error layanan dilempar apa adanya (ditangani view)."""
    config = types.GenerateContentConfig(
        temperature=1,
        response_modalities=["audio"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICES.get(persona, VOICES["galak"])))),
    )
    try:
        for chunk in _get_client().models.generate_content_stream(model=MODEL, contents=script(text, mood, persona),
                                                                  config=config):
            if chunk.parts and chunk.parts[0].inline_data and chunk.parts[0].inline_data.data:
                yield chunk.parts[0].inline_data.data
    except genai_errors.ClientError as e:
        if e.code == 429:
            raise QuotaExceeded(str(e)) from e
        raise
