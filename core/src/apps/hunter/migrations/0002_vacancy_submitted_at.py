from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hunter', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacancy',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
