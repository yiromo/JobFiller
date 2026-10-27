import apps.cvs.models.cv
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cvs', '0002_cv_git_url_cv_linkedin_url'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cv',
            name='file',
            field=models.FileField(upload_to=apps.cvs.models.cv.cv_upload_to),
        ),
    ]
