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

# Produksi = backend berjalan di Render (Render mengisi env RENDER=true). Frontend ada di Netlify.
ON_RENDER = os.environ.get("RENDER") == "true"

# Kunci untuk menandatangani cookie/token (mis. login admin). Di produksi WAJIB diisi lewat env DJANGO_SECRET_KEY:
# lebih baik aplikasi menolak jalan daripada berjalan dengan kunci yang tertulis di kode publik.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ("" if ON_RENDER else "dev-only-tidak-untuk-produksi")
if not SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("DJANGO_SECRET_KEY wajib diisi di Environment Variables Render")

# DEBUG menampilkan detail error ke pengunjung: nyala di lokal, mati di Render (kecuali dinyalakan sengaja)
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if ON_RENDER else "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):          # mis. ai-english-tutor-api.onrender.com, diisi Render
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
if ON_RENDER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")   # HTTPS diputus di proxy Render
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True                # cookie login admin hanya lewat HTTPS
    CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]

# CORS: halaman web di Netlify (domain lain) boleh memanggil /api/... di Render.
# FRONTEND_ORIGINS = alamat situs Netlify, mis. https://ai-english-tutor.netlify.app (pisahkan dengan koma).
# Di lokal halaman & API satu alamat, jadi CORS tidak dibutuhkan.
CORS_ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("FRONTEND_ORIGINS", "").split(",") if o.strip()]
CORS_URLS_REGEX = r"^/api/.*$"     # hanya API; panel admin tetap hanya dari domain Render sendiri

# "App" = satu paket fitur. Enam yang pertama bawaan Django; "tutor" adalah app kita.
INSTALLED_APPS = [
    "django.contrib.admin",          # panel admin
    "django.contrib.auth",           # akun admin (bukan akun pelajar)
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",       # fitur khusus PostgreSQL (ArrayField untuk fokus_pola)
    "corsheaders",                   # izin panggilan lintas domain (Netlify -> Render)
    "tutor",
]

# Lapisan yang dilewati setiap request secara berurutan (masuk dari atas, keluar dari bawah)
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",    # sajikan /static/ (CSS admin) dari STATIC_ROOT di produksi
    "corsheaders.middleware.CorsMiddleware",         # harus sebelum CommonMiddleware
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
# di /static/... . Di produksi halaman web disajikan Netlify langsung dari public/.
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "public" / "static"]
# Tujuan `collectstatic` (dijalankan saat build di Render); WhiteNoise menyajikannya, terutama CSS panel admin.
STATIC_ROOT = BASE_DIR / "staticfiles"
