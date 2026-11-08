"""CLI: login username -> tes penempatan (sekali) -> cek batas harian -> planner -> sesi -> rekap.

Jalankan: uv run main.py [--debug]
"""

import sys

import db
from agent import DEFAULT_PERSONA, STATIC_PROMPT, build_dynamic_prompt, run_session
from placement import run_placement
from planner import plan_session
from tools import SessionContext

MAX_SESSIONS_PER_DAY = 3


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # terminal Windows default cp1252
    debug = "--debug" in sys.argv

    username = ""
    while not username:
        username = input("Username: ").strip().lower()

    with db.connect() as conn:
        user = db.get_or_create_user(conn, username)
        if not user["sudah_tes"]:
            _, level = run_placement()
            db.set_placement(conn, user["id"], level)
            user["level"], user["sudah_tes"] = level, True

        used = db.count_sessions_today(conn, user["id"])
        if used >= MAX_SESSIONS_PER_DAY:
            print(f"Batas {MAX_SESSIONS_PER_DAY} sesi per hari sudah tercapai. Coba lagi besok.")
            return 1

        plan, topic, progress, errors = plan_session(conn, user, debug)
        if user["level"] == "pemula" and topic is None:
            print("Kurikulum pemula kosong. Jalankan seed.sql terlebih dahulu.")
            return 1
        session_id = db.create_session(conn, user["id"], topic["id"] if topic else None, plan.skenario, plan.fokus_pola)

        print(f"\nSesi {used + 1}/{MAX_SESSIONS_PER_DAY} hari ini | level: {user['level']} | "
              f"{'topik: ' + topic['judul'] if topic else 'skenario: ' + plan.skenario} | "
              f"fokus: {', '.join(plan.fokus_pola)}")
        print("Ketik /selesai untuk mengakhiri sesi.\n")

        persona = user["persona_default"] or DEFAULT_PERSONA
        system_prompt = STATIC_PROMPT + "\n" + build_dynamic_prompt(
            user, topic, plan.skenario, plan.fokus_pola, progress, errors, persona=persona)
        ctx = SessionContext(conn=conn, user_id=user["id"], session_id=session_id, persona=persona)
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
