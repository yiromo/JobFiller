from datetime import timedelta

from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Opportunity


def payload(item):
    return {
        "id": item.id,
        "message_id": item.message_id,
        "posted_at": item.posted_at,
        "title": item.title,
        "source_links": item.source_links,
        "url": item.url,
        "cv_id": item.cv_id,
        "match_score": item.match_score,
        "match_reason": item.match_reason,
        "status": item.status,
        "attempt_note": item.attempt_note,
    }


class OpportunityListView(APIView):
    def get(self, request):
        return Response([payload(item) for item in Opportunity.objects.all()[:100]])


class OpportunityNextView(APIView):
    def post(self, request):
        Opportunity.objects.filter(
            status=Opportunity.Status.APPLYING,
            updated_at__lt=timezone.now() - timedelta(hours=2),
        ).update(
            status=Opportunity.Status.NEEDS_REVIEW,
            attempt_note="Browser stopped during application; inspect before retrying.",
            updated_at=timezone.now(),
        )
        # A conditional update prevents two extension instances from claiming
        # the same job. If the first candidate was claimed, try the next one.
        for item in Opportunity.objects.filter(status=Opportunity.Status.READY).order_by(
            "posted_at", "id"
        )[:20]:
            updated = Opportunity.objects.filter(
                pk=item.pk, status=Opportunity.Status.READY
            ).update(status=Opportunity.Status.APPLYING, attempt_note="", updated_at=timezone.now())
            if updated:
                item.status = Opportunity.Status.APPLYING
                item.attempt_note = ""
                return Response(payload(item))
        return Response(status=status.HTTP_204_NO_CONTENT)


class OpportunityDetailView(APIView):
    def post(self, request, opportunity_id):
        result = request.data.get("status")
        if result not in {Opportunity.Status.APPLIED, Opportunity.Status.NEEDS_REVIEW}:
            return Response({"detail": "status must be applied or needs_review"}, status=400)
        note = str(request.data.get("note") or "")[:2000]
        updated = Opportunity.objects.filter(
            Q(pk=opportunity_id), Q(status=Opportunity.Status.APPLYING)
        ).update(status=result, attempt_note=note, updated_at=timezone.now())
        if not updated:
            if not Opportunity.objects.filter(pk=opportunity_id).exists():
                raise Http404
            return Response({"detail": "opportunity is not being applied"}, status=409)
        return Response({"id": opportunity_id, "status": result, "attempt_note": note})
