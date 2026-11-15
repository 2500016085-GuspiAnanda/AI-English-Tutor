"""Semua akses database ada di sini, lewat ORM Django (model di tutor/models.py).

Nama dan bentuk keluaran fungsi sama dengan versi SQL manual sebelumnya (dict biasa),
sehingga agent.py, tools.py, dan planner.py tidak perlu tahu bahwa di baliknya ada ORM.
Koneksi database diurus Django: tidak ada lagi parameter `conn` yang dioper ke mana-mana.

Setiap query ORM langsung di-commit (mode autocommit bawaan Django), sama seperti
autocommit=True di versi psycopg. Yang butuh beberapa query sekaligus memakai transaction.atomic().
"""

import os

import django
from django.apps import apps

# File ini juga dipakai di luar server Django (CLI main.py, tes): siapkan Django dulu bila belum.
if not apps.ready:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

from datetime import timedelta  # noqa: E402

from django.db import transaction  # noqa: E402
from django.db.models import Count, F, Max, Q  # noqa: E402
from django.db.models.functions import Now, TruncDate  # noqa: E402
from django.utils import timezone  # noqa: E402

from tutor.models import Kesalahan, Pelajar, Pesan, ProgresPola, Sesi, Topik  # noqa: E402

MASTERED_STREAK = 3  # sesi berturut-turut tanpa salah agar pola dianggap dikuasai

USER_FIELDS = ("id", "username", "level", "persona_default", "sudah_tes")


# --- users -----------------------------------------------------------------

def get_or_create_user(username: str) -> dict:
    # get_or_create: SELECT dulu; kalau tidak ada, INSERT. Aman bila dua request membuat username yang sama
    # bersamaan (yang kalah mendapat IntegrityError, lalu Django mengulang SELECT).
    user, _created = Pelajar.objects.get_or_create(username=username)
    return {f: getattr(user, f) for f in USER_FIELDS}


def get_user(user_id: int) -> dict | None:
    # .values() -> hasilnya dict, bukan objek model. .first() -> None bila tidak ada.
    return Pelajar.objects.filter(pk=user_id).values(*USER_FIELDS).first()


def set_persona(user_id: int, persona: str) -> None:
    # .update() = satu UPDATE langsung di database, tanpa mengambil barisnya dulu
    Pelajar.objects.filter(pk=user_id).update(persona_default=persona)


def set_placement(user_id: int, level: str) -> None:
    Pelajar.objects.filter(pk=user_id).update(level=level, sudah_tes=True)


def count_sessions_today(user_id: int) -> int:
    # "Hari ini" dalam WIB (TIME_ZONE di settings), mulai pukul 00.00.
    awal_hari = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return Sesi.objects.filter(user_id=user_id, created_at__gte=awal_hari).count()


# --- kurikulum & sesi ----------------------------------------------------

def list_topics_with_history(user_id: int, level: str) -> list[dict]:
    """Semua topik di level ini + berapa kali pengguna sudah mempelajarinya (bahan planner)."""
    # annotate + filter=Q(...) = LEFT JOIN sessions ... GROUP BY, hanya menghitung sesi milik pengguna ini
    milik_dia = Q(sesi__user_id=user_id)
    return list(
        Topik.objects.filter(level=level)
        .annotate(kali_dipelajari=Count("sesi", filter=milik_dia),
                  terakhir=TruncDate(Max("sesi__created_at", filter=milik_dia)))
        .order_by("urutan")
        .values("id", "urutan", "judul", "tujuan", "contoh_kalimat", "kali_dipelajari", "terakhir")
    )


def create_session(user_id: int, topic_id: int | None, skenario: str | None, fokus_pola: list[str]) -> int:
    return Sesi.objects.create(user_id=user_id, topic_id=topic_id, skenario=skenario, fokus_pola=fokus_pola).pk


def save_chat_state(session_id: int, state: dict) -> None:
    Sesi.objects.filter(pk=session_id).update(state=state)   # JSONField: dict langsung disimpan sebagai JSONB


def load_chat_state(session_id: int) -> dict | None:
    """Kembalikan {"user_id", "state"} atau None bila sesi tidak ada."""
    return Sesi.objects.filter(pk=session_id).values("user_id", "state").first()


def get_session_owner(session_id: int) -> dict | None:
    """{"user_id", "created_at"} sebuah sesi, atau None bila tidak ada."""
    return Sesi.objects.filter(pk=session_id).values("user_id", "created_at").first()


def try_lock_session(session_id: int, seconds: int = 180) -> bool:
    """Kunci sesi selama pesan diproses. Gagal bila sedang dikunci request lain.

    Kunci berbentuk batas waktu, bukan flag biasa: bila server mati di tengah proses,
    kunci lepas sendiri setelah `seconds` detik sehingga sesi tidak macet selamanya.
    Satu UPDATE bersyarat bersifat atomik: dari dua request bersamaan, hanya satu yang mengubah baris.
    """
    belum_terkunci = Q(busy_until__isnull=True) | Q(busy_until__lt=Now())
    diubah = Sesi.objects.filter(belum_terkunci, pk=session_id).update(busy_until=Now() + timedelta(seconds=seconds))
    return diubah == 1


def unlock_session(session_id: int) -> None:
    Sesi.objects.filter(pk=session_id).update(busy_until=None)


def end_session(session_id: int, ringkasan: str) -> None:
    Sesi.objects.filter(pk=session_id).update(ringkasan=ringkasan)


def save_message(session_id: int, role: str, content: str, model: str | None = None, tokens: int | None = None) -> None:
    Pesan.objects.create(session_id=session_id, role=role, content=content, model=model, tokens=tokens)


# --- kesalahan & progres pola ---------------------------------------------

def insert_mistake(user_id: int, session_id: int, kalimat_asli: str, kalimat_benar: str, kategori: str, pola: str) -> int:
    return Kesalahan.objects.create(user_id=user_id, session_id=session_id, kalimat_asli=kalimat_asli,
                                    kalimat_benar=kalimat_benar, kategori=kategori, pola=pola).pk


def get_error_log(user_id: int, limit: int = 20) -> list[dict]:
    return list(
        Kesalahan.objects.filter(user_id=user_id)
        .order_by("-created_at")
        .values("kalimat_asli", "kalimat_benar", "kategori", "pola", tanggal=TruncDate("created_at"))[:limit]
    )


def record_pattern_failure(user_id: int, pola: str) -> None:
    # Pengganti INSERT ... ON CONFLICT DO UPDATE:
    #   create_defaults -> nilai bila barisnya baru dibuat
    #   defaults        -> nilai bila barisnya sudah ada; F("jumlah_salah") + 1 dihitung DI DATABASE,
    #                      jadi tidak ada tambahan yang hilang walau dua request berjalan bersamaan
    ProgresPola.objects.update_or_create(
        user_id=user_id, pola=pola,
        create_defaults={"jumlah_salah": 1, "streak_benar": 0, "sudah_dikuasai": False},
        defaults={"jumlah_salah": F("jumlah_salah") + 1, "streak_benar": 0, "sudah_dikuasai": False,
                  "terakhir_muncul": Now()},
    )


def record_pattern_success(user_id: int, pola: str) -> dict:
    """Dipanggil maksimal sekali per pola per sesi (dijaga di tools.py)."""
    # Status "dikuasai" bergantung pada nilai streak yang BARU, jadi baris dikunci dulu
    # (select_for_update = SELECT ... FOR UPDATE) agar tidak ada request lain yang mengubahnya di tengah jalan.
    with transaction.atomic():
        progres, baru = ProgresPola.objects.select_for_update().get_or_create(
            user_id=user_id, pola=pola,
            defaults={"jumlah_salah": 0, "streak_benar": 1, "sudah_dikuasai": 1 >= MASTERED_STREAK},
        )
        if not baru:
            progres.streak_benar += 1
            progres.sudah_dikuasai = progres.streak_benar >= MASTERED_STREAK
            progres.terakhir_muncul = timezone.now()
            progres.save(update_fields=["streak_benar", "sudah_dikuasai", "terakhir_muncul"])
    return {"pola": progres.pola, "streak_benar": progres.streak_benar, "sudah_dikuasai": progres.sudah_dikuasai}


def get_pattern_progress(user_id: int) -> list[dict]:
    return list(
        ProgresPola.objects.filter(user_id=user_id)
        .order_by("sudah_dikuasai", "-terakhir_muncul")
        .values("pola", "jumlah_salah", "streak_benar", "sudah_dikuasai")
    )
