from django.urls import path

from .views import ApplicationScanView

urlpatterns = [
    path("scan/", ApplicationScanView.as_view(), name="application-scan"),
]
