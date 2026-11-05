from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hunter', '0006_outreach'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacancy',
            name='coverage',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
