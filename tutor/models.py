"""Model = satu class Python untuk satu tabel database.

Enam model di bawah dibuat PERSIS sama dengan tabel di schema.sql (nama tabel, kolom,
default, CHECK, UNIQUE, index), karena tabelnya sudah ada dan sudah berisi data.
Mulai sekarang perubahan skema ditulis di sini, lalu `makemigrations` membuat file migration-nya.

Catatan penamaan: nama model berbahasa Indonesia agar senada dengan nama kolom (kalimat_asli, pola, ...);
nama tabel lama tetap dipakai lewat `db_table`.
"""
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


# --- Pilihan nilai (dipakai di field `choices` dan di CHECK constraint) -----------------
class Level(models.TextChoices):
    PEMULA = "pemula"
    MENENGAH = "menengah"
    LANJUT = "lanjut"


class Persona(models.TextChoices):
    GALAK = "galak"
    LEMBUT = "lembut"


class Kategori(models.TextChoices):
    GRAMMAR = "grammar"
    VOCABULARY = "vocabulary"
    WORD_CHOICE = "word_choice", "word choice"
    SENTENCE_STRUCTURE = "sentence_structure", "sentence structure"


class Role(models.TextChoices):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# --- Tabel -----------------------------------------------------------------------------
class Pelajar(models.Model):
    """Pengguna aplikasi (login cukup username). Bukan akun admin Django."""
    username = models.TextField(unique=True)
    level = models.TextField(choices=Level, db_default=Level.PEMULA)
    persona_default = models.TextField(choices=Persona, null=True, blank=True)   # NULL = galak
    sudah_tes = models.BooleanField(db_default=False)    # tes penempatan selesai / dilewati
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "users"
        verbose_name_plural = "pelajar"
        constraints = [
            models.CheckConstraint(condition=Q(level__in=Level.values), name="users_level_check"),
            models.CheckConstraint(condition=Q(persona_default__in=Persona.values), name="users_persona_default_check"),
        ]

    def __str__(self):
        return self.username


class Topik(models.Model):
    """Kurikulum pemula: 6 topik berurutan."""
    level = models.TextField(choices=Level)
    urutan = models.IntegerField()
    judul = models.TextField()
    tujuan = models.TextField()
    contoh_kalimat = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "curriculum_topics"
        verbose_name_plural = "topik"
        ordering = ["level", "urutan"]
        constraints = [
            models.UniqueConstraint(fields=["level", "urutan"], name="curriculum_topics_level_urutan_key"),
            models.CheckConstraint(condition=Q(level__in=Level.values), name="curriculum_topics_level_check"),
        ]

    def __str__(self):
        return f"{self.level} {self.urutan}. {self.judul}"


class Sesi(models.Model):
    user = models.ForeignKey(Pelajar, on_delete=models.DB_CASCADE, related_name="sesi")
    # diisi untuk pemula. DO_NOTHING: database sendiri yang menolak penghapusan topik yang masih dipakai sesi
    # (on_delete di satu rantai relasi harus seragam: semuanya level database seperti DB_CASCADE di bawah)
    topic = models.ForeignKey(Topik, on_delete=models.DO_NOTHING, null=True, blank=True)
    skenario = models.TextField(null=True, blank=True)                                  # diisi untuk menengah/lanjut
    fokus_pola = ArrayField(models.TextField(), default=list, blank=True)              # 1-2 pola dari planner
    ringkasan = models.TextField(null=True, blank=True)       # diisi oleh tool end_session
    state = models.JSONField(null=True, blank=True)           # state percakapan yang sedang berjalan (web)
    busy_until = models.DateTimeField(null=True, blank=True)  # kunci: pesan sedang diproses sampai waktu ini
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "sessions"
        verbose_name_plural = "sesi"
        constraints = [
            models.CheckConstraint(condition=Q(topic__isnull=False) | Q(skenario__isnull=False), name="sessions_check"),
        ]
        indexes = [models.Index(fields=["user", "-created_at"], name="idx_sessions_user")]

    def __str__(self):
        return f"Sesi {self.pk} · {self.user}"


class Pesan(models.Model):
    """Riwayat percakapan: pesan pengguna, balasan LLM, dan hasil tool."""
    session = models.ForeignKey(Sesi, on_delete=models.DB_CASCADE, related_name="pesan")
    role = models.TextField(choices=Role)
    content = models.TextField()
    model = models.TextField(null=True, blank=True)
    tokens = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "messages"
        verbose_name_plural = "pesan"
        constraints = [models.CheckConstraint(condition=Q(role__in=Role.values), name="messages_role_check")]
        indexes = [models.Index(fields=["session", "created_at"], name="idx_messages_sess")]


class Kesalahan(models.Model):
    """Dicatat agen lewat tool save_mistake."""
    user = models.ForeignKey(Pelajar, on_delete=models.DB_CASCADE, related_name="kesalahan")
    session = models.ForeignKey(Sesi, on_delete=models.DB_CASCADE, related_name="kesalahan")
    kalimat_asli = models.TextField()
    kalimat_benar = models.TextField()
    kategori = models.TextField(choices=Kategori)
    pola = models.TextField()
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "mistakes"
        verbose_name_plural = "kesalahan"
        constraints = [models.CheckConstraint(condition=Q(kategori__in=Kategori.values), name="mistakes_kategori_check")]
        indexes = [models.Index(fields=["user", "-created_at"], name="idx_mistakes_user")]

    def __str__(self):
        return f"{self.kalimat_asli} → {self.kalimat_benar}"


class ProgresPola(models.Model):
    """Satu baris per (pelajar, pola). Pola dikuasai setelah 3 sesi berturut-turut tanpa salah.

    Tabel lama tidak punya primary key (hanya UNIQUE user_id+pola), padahal Django mewajibkannya:
    kolom `id` ditambahkan, dan UNIQUE lama tetap dijaga sebagai constraint.
    """
    user = models.ForeignKey(Pelajar, on_delete=models.DB_CASCADE, related_name="progres")
    pola = models.TextField()
    jumlah_salah = models.IntegerField(db_default=0)
    streak_benar = models.IntegerField(db_default=0)       # sesi berturut-turut tanpa salah
    sudah_dikuasai = models.BooleanField(db_default=False)
    terakhir_muncul = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "pattern_progress"
        verbose_name_plural = "progres pola"
        constraints = [models.UniqueConstraint(fields=["user", "pola"], name="pattern_progress_user_id_pola_key")]

    def __str__(self):
        return f"{self.user} · {self.pola}"
