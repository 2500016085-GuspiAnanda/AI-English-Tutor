"""CLI M2: login username -> cek batas harian -> sesi percakapan dengan agen -> rekap.

Jalankan: uv run main.py [--debug]
"""

import random
import sys

import db
from agent import STATIC_PROMPT, build_dynamic_prompt, run_session
from tools import SessionContext

MAX_SESSIONS_PER_DAY = 3
SKENARIO = ["interview magang", "presentasi kelas"]


def pick_focus(progress: list[dict]) -> list[str]:
    """Sementara (sebelum planner M3): 2 pola belum dikuasai dengan kesalahan terbanyak."""
    open_ = [p for p in progress if not p["sudah_dikuasai"]]
    open_.sort(key=lambda p: p["jumlah_salah"], reverse=True)
    return [p["pola"] for p in open_[:2]]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # terminal Windows default cp1252
    debug = "--debug" in sys.argv

    username = ""
    while not username:
        username = input("Username: ").strip().lower()

    with db.connect() as conn:
        user = db.get_or_create_user(conn, username)
        used = db.count_sessions_today(conn, user["id"])
        if used >= MAX_SESSIONS_PER_DAY:
            print(f"Batas {MAX_SESSIONS_PER_DAY} sesi per hari sudah tercapai. Coba lagi besok.")
            return 1

        topic, skenario = None, None
        if user["level"] == "pemula":
            topic = db.next_topic(conn, user["id"], "pemula")
            if topic is None:
                print("Kurikulum pemula kosong. Jalankan seed.sql terlebih dahulu.")
                return 1
        else:
            skenario = random.choice(SKENARIO)

        progress = db.get_pattern_progress(conn, user["id"])
        fokus = pick_focus(progress)
        errors = db.get_error_log(conn, user["id"], limit=10)
        session_id = db.create_session(conn, user["id"], topic["id"] if topic else None, skenario, fokus)

        print(f"\nSesi {used + 1}/{MAX_SESSIONS_PER_DAY} hari ini | level: {user['level']} | "
              f"{'topik: ' + topic['judul'] if topic else 'skenario: ' + skenario}"
              f"{' | fokus: ' + ', '.join(fokus) if fokus else ''}")
        print("Ketik /selesai untuk mengakhiri sesi.\n")

        system_prompt = STATIC_PROMPT + "\n" + build_dynamic_prompt(user, topic, skenario, fokus, progress, errors)
        ctx = SessionContext(conn=conn, user_id=user["id"], session_id=session_id)
        try:
            run_session(ctx, system_prompt, debug)
        except KeyboardInterrupt:
            print("\n(Sesi dihentikan.)")

        print("=== Status pola ===")
        for p in db.get_pattern_progress(conn, user["id"]):
            status = "dikuasai" if p["sudah_dikuasai"] else f"streak {p['streak_benar']}/{db.MASTERED_STREAK}"
            print(f"- {p['pola']}: salah {p['jumlah_salah']}x, {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
