"""Panel admin Django: melihat dan mengelola data tutor lewat browser di /admin/.

Django membangun halaman daftar, pencarian, filter, dan form edit otomatis dari model.
Di sini kita hanya mengatur APA yang tampil: kolom daftar (list_display), filter samping (list_filter),
kotak cari (search_fields), dan data terkait yang ditampilkan di halaman induknya (inline).

Data buatan agen (pesan, kesalahan) dibuat hanya-baca di inline, supaya riwayat tidak ikut tersunting.
"""
from django.contrib import admin
from django.db.models import Count

from .models import Kesalahan, Pelajar, Pesan, ProgresPola, Sesi, Topik

admin.site.site_header = "AI English Tutor · Admin"
admin.site.site_title = "AI English Tutor"
admin.site.index_title = "Data tutor"


class ReadOnlyInline(admin.TabularInline):
    """Inline hanya-baca: tampil di halaman induk, tidak bisa ditambah, diubah, atau dihapus dari sana."""
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ProgresInline(ReadOnlyInline):
    model = ProgresPola
    fields = ("pola", "jumlah_salah", "streak_benar", "sudah_dikuasai", "terakhir_muncul")
    ordering = ("sudah_dikuasai", "-terakhir_muncul")


class PesanInline(ReadOnlyInline):
    model = Pesan
    fields = ("role", "content", "model", "tokens", "created_at")
    ordering = ("id",)


class KesalahanInline(ReadOnlyInline):
    model = Kesalahan
    fk_name = "session"
    fields = ("kalimat_asli", "kalimat_benar", "kategori", "pola")


@admin.register(Pelajar)
class PelajarAdmin(admin.ModelAdmin):
    list_display = ("username", "level", "persona_default", "sudah_tes", "jumlah_sesi", "jumlah_kesalahan", "created_at")
    list_filter = ("level", "persona_default", "sudah_tes")
    search_fields = ("username",)
    readonly_fields = ("created_at",)
    inlines = [ProgresInline]

    def get_queryset(self, request):
        # Hitung sesi & kesalahan dalam SATU query (annotate), bukan satu query per baris daftar
        return super().get_queryset(request).annotate(
            n_sesi=Count("sesi", distinct=True), n_salah=Count("kesalahan", distinct=True))

    @admin.display(description="sesi", ordering="n_sesi")
    def jumlah_sesi(self, obj):
        return obj.n_sesi

    @admin.display(description="kesalahan", ordering="n_salah")
    def jumlah_kesalahan(self, obj):
        return obj.n_salah


@admin.register(Topik)
class TopikAdmin(admin.ModelAdmin):
    list_display = ("level", "urutan", "judul", "tujuan")
    list_display_links = ("judul",)
    list_filter = ("level",)


@admin.register(Sesi)
class SesiAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "materi", "fokus", "jumlah_pesan", "selesai", "created_at")
    list_filter = ("created_at", "topic")
    search_fields = ("user__username", "skenario", "ringkasan")
    list_select_related = ("user", "topic")      # ambil pelajar & topik sekaligus (JOIN), bukan per baris
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "busy_until", "state")
    fieldsets = [
        (None, {"fields": ("user", "topic", "skenario", "fokus_pola", "ringkasan", "created_at")}),
        ("Teknis", {"fields": ("busy_until", "state"), "classes": ("collapse",),
                    "description": "state = percakapan tersimpan di antara request; busy_until = kunci sesi."}),
    ]
    inlines = [KesalahanInline, PesanInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n_pesan=Count("pesan"))

    @admin.display(description="materi")
    def materi(self, obj):
        return obj.topic.judul if obj.topic else obj.skenario

    @admin.display(description="fokus")
    def fokus(self, obj):
        return ", ".join(obj.fokus_pola)

    @admin.display(description="pesan", ordering="n_pesan")
    def jumlah_pesan(self, obj):
        return obj.n_pesan

    @admin.display(description="selesai", boolean=True)
    def selesai(self, obj):
        return bool(obj.ringkasan)


@admin.register(Kesalahan)
class KesalahanAdmin(admin.ModelAdmin):
    list_display = ("kalimat_asli", "kalimat_benar", "kategori", "pola", "user", "created_at")
    list_filter = ("kategori", "pola")
    search_fields = ("kalimat_asli", "kalimat_benar", "pola", "user__username")
    list_select_related = ("user",)
    date_hierarchy = "created_at"


@admin.register(ProgresPola)
class ProgresPolaAdmin(admin.ModelAdmin):
    list_display = ("user", "pola", "jumlah_salah", "streak_benar", "sudah_dikuasai", "terakhir_muncul")
    list_filter = ("sudah_dikuasai",)
    search_fields = ("pola", "user__username")
    list_select_related = ("user",)


@admin.register(Pesan)
class PesanAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "ringkas", "model", "tokens", "created_at")
    list_filter = ("role",)
    search_fields = ("content",)
    list_select_related = ("session__user",)

    @admin.display(description="isi")
    def ringkas(self, obj):
        return obj.content[:80] + ("…" if len(obj.content) > 80 else "")
