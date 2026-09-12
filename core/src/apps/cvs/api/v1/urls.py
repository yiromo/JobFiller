from django.urls import path

from .views import CvDetailView, CvFileDownloadView, CvListCreateView

urlpatterns = [
    path("", CvListCreateView.as_view(), name="cv-list-create"),
    path("<int:cv_id>/", CvDetailView.as_view(), name="cv-detail"),
    path("<int:cv_id>/file/", CvFileDownloadView.as_view(), name="cv-file"),
]
