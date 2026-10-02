from django.urls import path

from .views import (
    HunterEeoView,
    HunterEvidenceView,
    HunterLetterView,
    HunterScopeView,
    HunterStatusView,
)

urlpatterns = [
    path("", HunterStatusView.as_view(), name="hunter-status"),
    path("eeo/", HunterEeoView.as_view(), name="hunter-eeo"),
    path("letter/", HunterLetterView.as_view(), name="hunter-letter"),
    path("scope/", HunterScopeView.as_view(), name="hunter-scope"),
    path(
        "evidence/<str:key>/<str:name>",
        HunterEvidenceView.as_view(),
        name="hunter-evidence",
    ),
]
