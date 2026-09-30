from django.urls import path

from .views import HunterEeoView, HunterEvidenceView, HunterStatusView

urlpatterns = [
    path("", HunterStatusView.as_view(), name="hunter-status"),
    path("eeo/", HunterEeoView.as_view(), name="hunter-eeo"),
    path(
        "evidence/<str:key>/<str:name>",
        HunterEvidenceView.as_view(),
        name="hunter-evidence",
    ),
]
