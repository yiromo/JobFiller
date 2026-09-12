from django.urls import path

from .views import AnalyzeApplicationView, ApplicationScanView, GenerateCoverLetterView

urlpatterns = [
    path("scan/", ApplicationScanView.as_view(), name="application-scan"),
    path(
        "generate-cover-letter/",
        GenerateCoverLetterView.as_view(),
        name="application-generate-cover-letter",
    ),
    path("analyze/", AnalyzeApplicationView.as_view(), name="application-analyze"),
]
