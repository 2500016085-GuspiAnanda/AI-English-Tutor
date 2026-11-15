"""Daftar alamat app tutor: URL -> view. Disertakan dari config/urls.py.

<int:session_id> = bagian URL yang diubah jadi angka dan dikirim ke view sebagai argumen.
"""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/login", views.login),
    path("api/placement/questions", views.placement_questions),
    path("api/placement", views.placement),
    path("api/persona", views.set_persona),
    path("api/sessions", views.start_session),
    path("api/sessions/<int:session_id>/messages", views.send_message),
    path("api/sessions/<int:session_id>/end", views.end_session),
    path("api/users/<int:user_id>/memory", views.memory),
    path("api/tts", views.speech),
    path("api/health", views.health),
]
