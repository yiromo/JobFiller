import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hunter", "0003_site_lesson"),
    ]

    operations = [
        migrations.CreateModel(
            name="MailMessage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("account", models.CharField(max_length=255)),
                ("uidvalidity", models.BigIntegerField()),
                ("uid", models.BigIntegerField()),
                ("message_id", models.CharField(blank=True, max_length=998)),
                ("received_at", models.DateTimeField(blank=True, null=True)),
                ("sender", models.CharField(blank=True, max_length=255)),
                ("subject", models.CharField(blank=True, max_length=500)),
                ("kind", models.CharField(max_length=24)),
                ("employer", models.CharField(blank=True, max_length=255)),
                ("summary", models.CharField(blank=True, max_length=500)),
                ("dismissed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "vacancy",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mail",
                        to="hunter.vacancy",
                    ),
                ),
            ],
            options={
                "db_table": "hunter_mail",
                "ordering": ("-received_at", "-id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("account", "uidvalidity", "uid"), name="unique_mail_message"
                    )
                ],
            },
        ),
    ]
