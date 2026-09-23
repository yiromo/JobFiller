from django.urls import path

from .views import OpportunityDetailView, OpportunityListView, OpportunityNextView

urlpatterns = [
    path("", OpportunityListView.as_view(), name="opportunity-list"),
    path("next/", OpportunityNextView.as_view(), name="opportunity-next"),
    path("<int:opportunity_id>/", OpportunityDetailView.as_view(), name="opportunity-detail"),
]
