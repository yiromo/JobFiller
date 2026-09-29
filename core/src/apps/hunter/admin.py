from django.contrib import admin

from .models import ResumeLink, Vacancy


@admin.register(Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = ("title", "employer", "match_score", "status", "updated_at")
    list_filter = ("status", "source")
    search_fields = ("title", "employer", "external_id")


admin.site.register(ResumeLink)
