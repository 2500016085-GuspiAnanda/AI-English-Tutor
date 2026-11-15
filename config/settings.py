"""Pengaturan Django untuk AI English Tutor.

Satu file ini dibaca Django saat start: aplikasi apa saja yang aktif, database mana,
middleware apa yang dilewati tiap request, zona waktu, dll.
Nilai rahasia (kunci, alamat database) dibaca dari .env, tidak pernah ditulis di sini.
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent   # folder proyek (tempat manage.py)
load_dotenv(BASE_DIR / ".env")

# Vercel mengisi env VERCEL=1 di build & runtime: dipakai untuk menyalakan pengaturan produksi otomatis.
ON_VERCEL = os.environ.get("VERCEL") == "1"

# Kunci untuk menandatangani cookie/token (mis. login admin). Di produksi WAJIB diisi lewat env DJANGO_SECRET_KEY:
# lebih baik aplikasi menolak jalan daripada berjalan dengan kunci yang tertulis di kode publik.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ("" if ON_VERCEL else "dev-only-tidak-untuk-produksi")
if not SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("DJANGO_SECRET_KEY wajib diisi di Environment Variables Vercel")

# DEBUG menampilkan detail error ke pengunjung: nyala di lokal, mati di Vercel (kecuali dinyalakan sengaja)
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if ON_VERCEL else "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
# Domain deployment Vercel (preview, cabang, produksi) diizinkan otomatis dari env bawaan Vercel
ALLOWED_HOSTS += [h for h in (os.environ.get(k) for k in
                              ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL")) if h]
if ON_VERCEL:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")   # HTTPS diputus di proxy Vercel
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True                # cookie login admin hanya lewat HTTPS
    CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]

# "App" = satu paket fitur. Enam yang pertama bawaan Django; "tutor" adalah app kita.
INSTALLED_APPS = [
    "django.contrib.admin",          # panel admin
    "django.contrib.auth",           # akun admin (bukan akun pelajar)
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",       # fitur khusus PostgreSQL (ArrayField untuk fokus_pola)
    "tutor",
]

# Lapisan yang dilewati setiap request secara berurutan (masuk dari atas, keluar dari bawah)
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"     # daftar URL utama

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database yang sama dengan versi FastAPI: PostgreSQL dari DATABASE_URL di .env.
# conn_max_age: koneksi dipakai ulang antar-request (mirip pool di db.py);
# conn_health_checks: koneksi diuji dulu, karena database serverless bisa memutus koneksi diam.
DATABASES = {
    "default": dj_database_url.config(env="DATABASE_URL", conn_max_age=60, conn_health_checks=True),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"   # "hari ini" untuk batas 3 sesi/hari dihitung dalam WIB
USE_I18N = True
USE_TZ = True                # waktu disimpan UTC di database, ditampilkan dalam TIME_ZONE

# File statis frontend (style.css, app.js) ada di public/static; saat DEBUG, `runserver` menyajikannya
# di /static/... . Di produksi file ini disajikan CDN (Tahap 5).
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "public" / "static"]
# Tujuan `collectstatic`: Vercel menjalankannya otomatis saat build bila STATIC_ROOT diisi,
# lalu menyajikan isinya (CSS/JS aplikasi + tampilan admin) dari CDN.
STATIC_ROOT = BASE_DIR / "staticfiles"
