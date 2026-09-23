from django.db import models


class Opportunity(models.Model):
    class Status(models.TextChoices):
        UNACTIONABLE = "unactionable"
        BELOW_THRESHOLD = "below_threshold"
        READY = "ready"
        APPLYING = "applying"
        APPLIED = "applied"
        NEEDS_REVIEW = "needs_review"

    message_id = models.PositiveBigIntegerField()
    posted_at = models.DateTimeField()
    source_text = models.TextField()
    source_links = models.JSONField(default=list)
    title = models.CharField(max_length=255, blank=True)
    url = models.URLField(max_length=2048, blank=True)
    cv = models.ForeignKey("cvs.Cv", null=True, blank=True, on_delete=models.SET_NULL)
    match_score = models.PositiveSmallIntegerField(null=True, blank=True)
    match_reason = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=Status.choices)
    attempt_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opportunities"
        constraints = (
            models.UniqueConstraint(fields=["message_id", "url"], name="unique_post_url"),
        )
        ordering = ("-posted_at", "-id")

    def __str__(self):
        return f"{self.title or 'Channel post'} ({self.message_id})"
