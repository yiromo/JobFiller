from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hunter', '0002_vacancy_submitted_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteLesson',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('host', models.CharField(max_length=255, unique=True)),
                ('text', models.TextField(blank=True)),
                ('successes', models.PositiveIntegerField(default=0)),
                ('failures', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'hunter_site_lessons',
            },
        ),
    ]
