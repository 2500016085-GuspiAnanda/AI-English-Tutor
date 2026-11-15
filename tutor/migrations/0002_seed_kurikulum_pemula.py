"""Data migration: isi 6 topik kurikulum pemula (pengganti `psql -f seed.sql`).

Migration biasanya mengubah STRUKTUR tabel; data migration mengisi DATA. Keuntungannya: database baru
(mis. Neon di produksi) langsung punya kurikulum hanya dengan `manage.py migrate`, tanpa psql.

update_or_create berdasarkan (level, urutan): aman untuk database lama yang sudah berisi seed.sql,
tidak membuat baris ganda. apps.get_model dipakai (bukan import langsung) agar migration memakai
bentuk model pada titik sejarah ini, bukan bentuk model hari ini.
"""
from django.db import migrations

TOPIK_PEMULA = [
    (1, "Perkenalan diri",
     "Menyebut nama, asal, umur, dan status sebagai mahasiswa dengan to be (am/is/are).",
     "Hi, my name is Rina. I am from Bandung. I am a first-year student."),
    (2, "Kampus & jurusan",
     "Menjelaskan nama kampus, jurusan, dan alasan memilih jurusan dengan simple present.",
     "I study Informatics at Universitas Indonesia. I like it because I enjoy coding."),
    (3, "Rutinitas harian",
     "Menceritakan kegiatan sehari-hari dengan simple present dan keterangan waktu (always, usually, at 7 a.m.).",
     "I usually wake up at 5 a.m. Then I take a shower and go to campus by motorcycle."),
    (4, "Hobi",
     "Membicarakan hobi dan frekuensinya dengan like/enjoy + verb-ing.",
     "I like playing badminton. I play it every Sunday with my friends."),
    (5, "Arah & tempat",
     "Bertanya dan menjelaskan lokasi dengan preposisi tempat dan kalimat perintah sederhana.",
     "Excuse me, where is the library? Go straight and turn left. It is next to the canteen."),
    (6, "Minta tolong",
     "Meminta bantuan dengan sopan memakai can/could you dan menanggapi permintaan.",
     "Could you help me, please? Can you lend me your pen? Sure, here you are."),
]


def isi_kurikulum(apps, schema_editor):
    Topik = apps.get_model("tutor", "Topik")
    for urutan, judul, tujuan, contoh in TOPIK_PEMULA:
        Topik.objects.update_or_create(level="pemula", urutan=urutan,
                                       defaults={"judul": judul, "tujuan": tujuan, "contoh_kalimat": contoh})


class Migration(migrations.Migration):
    dependencies = [("tutor", "0001_initial")]
    # reverse_code noop: membatalkan migration ini tidak menghapus kurikulum (topik bisa sudah dipakai sesi)
    operations = [migrations.RunPython(isi_kurikulum, reverse_code=migrations.RunPython.noop)]
