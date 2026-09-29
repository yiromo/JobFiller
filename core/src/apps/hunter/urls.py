from django.urls import path

from .views import HunterStatusView

urlpatterns = [
    path("", HunterStatusView.as_view(), name="hunter-status"),
]
