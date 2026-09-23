from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("api/v1/cvs/", include("apps.cvs.api.v1.urls")),
    path("api/v1/applications/", include("apps.applications.api.v1.urls")),
    path("api/v1/opportunities/", include("apps.opportunities.urls")),
]
