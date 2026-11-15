"""Daftar URL utama situs. Setiap app punya urls.py sendiri yang disertakan di sini."""
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),     # panel admin (Tahap 4)
    path("", include("tutor.urls")),     # halaman web + API tutor
]

# /static/... (style.css, app.js) dari STATICFILES_DIRS. Hanya aktif saat DEBUG=True (lokal & tes);
# di produksi file statis disajikan CDN, bukan Django.
urlpatterns += staticfiles_urlpatterns()
