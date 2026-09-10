from django.db import models


class Application(models.Model):
    url = models.URLField(max_length=2048)
    site = models.CharField(max_length=255, blank=True, default="")
    form_snapshot = models.JSONField()
    field_mapping = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "applications"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Application {self.id}: {self.site or self.url}"
