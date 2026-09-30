from django.db import models


class ResumeLink(models.Model):
    cv = models.OneToOneField("cvs.Cv", on_delete=models.CASCADE, related_name="hh_resume")
    source = models.CharField(max_length=16, default="hh")
    resume_id = models.CharField(max_length=64)
    title = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "hunter_resume_links"

    def __str__(self):
        return f"CV {self.cv_id} -> {self.source} {self.title or self.resume_id}"


class Vacancy(models.Model):
    class Status(models.TextChoices):
        BELOW_THRESHOLD = "below_threshold"
        READY = "ready"
        APPLYING = "applying"
        APPLIED = "applied"
        NEEDS_REVIEW = "needs_review"
        SKIPPED = "skipped"

    source = models.CharField(max_length=16)
    external_id = models.CharField(max_length=64)
    url = models.URLField(max_length=2048)
    title = models.CharField(max_length=255, blank=True)
    employer = models.CharField(max_length=255, blank=True)
    text = models.TextField(blank=True)
    cv = models.ForeignKey("cvs.Cv", null=True, blank=True, on_delete=models.SET_NULL)
    resume_id = models.CharField(max_length=64, blank=True)
    match_score = models.PositiveSmallIntegerField(null=True, blank=True)
    match_reason = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=Status.choices)
    note = models.TextField(blank=True)
    cover_letter = models.TextField(blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hunter_vacancies"
        constraints = (
            models.UniqueConstraint(fields=["source", "external_id"], name="unique_source_vacancy"),
        )
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.title or self.external_id} ({self.source})"


class SiteLesson(models.Model):
    host = models.CharField(max_length=255, unique=True)
    text = models.TextField(blank=True)
    successes = models.PositiveIntegerField(default=0)
    failures = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hunter_site_lessons"

    def __str__(self):
        return f"{self.host} ({self.successes}/{self.successes + self.failures})"
