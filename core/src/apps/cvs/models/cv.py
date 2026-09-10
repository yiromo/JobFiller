from django.db import models


class Cv(models.Model):
    file = models.FileField(upload_to="cvs/")
    original_filename = models.CharField(max_length=255)
    raw_text = models.TextField(blank=True, default="")
    full_name = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "cvs"
        ordering = ("-uploaded_at",)

    def __str__(self) -> str:
        return self.original_filename
