import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hunter", "0005_mail_position"),
    ]

    operations = [
        migrations.AddField(
            model_name="vacancy",
            name="posted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="Outreach",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("posting", "Posting"), ("signal", "Signal")], max_length=16
                    ),
                ),
                ("employer", models.CharField(max_length=255)),
                ("role", models.CharField(blank=True, max_length=255)),
                ("signal", models.TextField(blank=True)),
                ("signal_url", models.URLField(blank=True, max_length=2048)),
                ("contact_name", models.CharField(blank=True, max_length=255)),
                ("contact_title", models.CharField(blank=True, max_length=255)),
                ("contact_url", models.URLField(blank=True, max_length=2048)),
                ("contact_quote", models.TextField(blank=True)),
                ("message", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("sent", "Sent"),
                            ("replied", "Replied"),
                            ("skipped", "Skipped"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("note", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "vacancy",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="outreach",
                        to="hunter.vacancy",
                    ),
                ),
            ],
            options={
                "db_table": "hunter_outreach",
                "ordering": ("-created_at", "-id"),
            },
        ),
    ]
