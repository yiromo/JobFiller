import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('cvs', '0002_cv_git_url_cv_linkedin_url'),
    ]

    operations = [
        migrations.CreateModel(
            name='ResumeLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(default='hh', max_length=16)),
                ('resume_id', models.CharField(max_length=64)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('cv', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='hh_resume', to='cvs.cv')),
            ],
            options={
                'db_table': 'hunter_resume_links',
            },
        ),
        migrations.CreateModel(
            name='Vacancy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=16)),
                ('external_id', models.CharField(max_length=64)),
                ('url', models.URLField(max_length=2048)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('employer', models.CharField(blank=True, max_length=255)),
                ('text', models.TextField(blank=True)),
                ('resume_id', models.CharField(blank=True, max_length=64)),
                ('match_score', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('match_reason', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('below_threshold', 'Below Threshold'), ('ready', 'Ready'), ('applying', 'Applying'), ('applied', 'Applied'), ('needs_review', 'Needs Review'), ('skipped', 'Skipped')], max_length=24)),
                ('note', models.TextField(blank=True)),
                ('cover_letter', models.TextField(blank=True)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('cv', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='cvs.cv')),
            ],
            options={
                'db_table': 'hunter_vacancies',
                'ordering': ('-created_at', '-id'),
                'constraints': [models.UniqueConstraint(fields=('source', 'external_id'), name='unique_source_vacancy')],
            },
        ),
    ]
