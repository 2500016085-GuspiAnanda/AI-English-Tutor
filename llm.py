"""Satu-satunya pintu ke LLM. Retry 2x, tanpa fallback model."""

import os
import time

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

load_dotenv()
MODEL = os.environ["DEEPSEEK_MODEL"]
_client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    max_retries=0,  # retry diatur manual di bawah agar jumlahnya pasti
)

MAX_RETRY = 2


def call_llm(messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False):
    """Kirim percakapan ke DeepSeek, kembalikan objek ChatCompletion.

    json_mode=True memaksa balasan berupa objek JSON (dipakai planner).
    Gagal setelah 1 percobaan + 2 retry -> exception diteruskan ke pemanggil.
    """
    kwargs = {"model": MODEL, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    for attempt in range(MAX_RETRY + 1):
        try:
            return _client.chat.completions.create(**kwargs)
        except (APIConnectionError, RateLimitError) as e:
            err = e
        except APIStatusError as e:
            if e.status_code < 500:
                raise  # 4xx (kecuali 429) tidak akan berhasil walau diulang
            err = e
        if attempt < MAX_RETRY:
            time.sleep(2**attempt)
    raise err
