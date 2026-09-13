from django.urls import path

from .views import (
    AnalyzeApplicationView,
    ApplicationScanView,
    GenerateAnswerView,
    GenerateCoverLetterView,
    ResolveOptionsView,
)

urlpatterns = [
    path("scan/", ApplicationScanView.as_view(), name="application-scan"),
    path(
        "generate-cover-letter/",
        GenerateCoverLetterView.as_view(),
        name="application-generate-cover-letter",
    ),
    path("analyze/", AnalyzeApplicationView.as_view(), name="application-analyze"),
    path("generate-answer/", GenerateAnswerView.as_view(), name="application-generate-answer"),
    path("resolve-options/", ResolveOptionsView.as_view(), name="application-resolve-options"),
]
