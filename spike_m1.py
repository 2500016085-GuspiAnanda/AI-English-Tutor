"""M1 spike: apakah DeepSeek memanggil tool dengan argumen yang lolos validasi Pydantic?"""

import os
import sys
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

sys.stdout.reconfigure(encoding="utf-8")  # terminal Windows default cp1252
load_dotenv()
client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
)
MODEL = os.environ["DEEPSEEK_MODEL"]


class SaveMistake(BaseModel):
    kalimat_asli: str
    kalimat_benar: str
    kategori: Literal["grammar", "vocabulary", "word_choice", "sentence_structure"]
    pola: str


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_mistake",
            "description": "Simpan kesalahan bahasa Inggris pengguna.",
            "parameters": SaveMistake.model_json_schema(),
        },
    }
]

resp = client.chat.completions.create(
    model=MODEL,
    tools=TOOLS,
    messages=[
        {
            "role": "system",
            "content": "Kamu tutor bahasa Inggris. Jika kalimat pengguna salah, panggil save_mistake.",
        },
        {"role": "user", "content": "Yesterday I go to campus with my friend."},
    ],
)

calls = resp.choices[0].message.tool_calls or []
valid = 0
for c in calls:
    try:
        print(SaveMistake.model_validate_json(c.function.arguments))
        valid += 1
    except ValidationError as e:
        print("Argumen tidak valid:", e)

ok = bool(calls) and valid == len(calls)
print("=== RINGKASAN ===")
print(f"model          : {resp.model}")
print(f"tool dipanggil : {len(calls)} (valid Pydantic: {valid})")
print(f"total tokens   : {resp.usage.total_tokens}")
print(f"STATUS         : {'LULUS' if ok else 'GAGAL'}")
sys.exit(0 if ok else 1)
