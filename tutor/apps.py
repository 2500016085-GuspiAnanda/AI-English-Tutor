from django.apps import AppConfig


class TutorConfig(AppConfig):
    name = "tutor"
    verbose_name = "Tutor"
    # id bertipe INTEGER (bukan BIGINT), sama dengan tabel lama yang memakai INTEGER GENERATED ALWAYS AS IDENTITY
    default_auto_field = "django.db.models.AutoField"
