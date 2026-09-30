from django.urls import path

from .views import HunterEvidenceView, HunterStatusView

urlpatterns = [
    path("", HunterStatusView.as_view(), name="hunter-status"),
    path(
        "evidence/<str:key>/<str:name>",
        HunterEvidenceView.as_view(),
        name="hunter-evidence",
    ),
]
