from django.urls import path

from .views import ApplicationScanView, GenerateCoverLetterView

urlpatterns = [
    path("scan/", ApplicationScanView.as_view(), name="application-scan"),
    path(
        "generate-cover-letter/",
        GenerateCoverLetterView.as_view(),
        name="application-generate-cover-letter",
    ),
]
