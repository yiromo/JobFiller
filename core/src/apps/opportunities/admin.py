from django.contrib import admin

from .models import Opportunity


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "match_score", "cv", "posted_at", "url")
    list_filter = ("status",)
    search_fields = ("title", "source_text", "url")
