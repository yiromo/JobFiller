import logging

from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.container import ApplicationsContainer
from apps.applications.dto import ScanRequestDTO
from apps.applications.services.application_service import (
    ApplicationNotFoundError,
    MimoNotConfiguredError,
    NoCvOnApplicationError,
    SearchNotConfiguredError,
)

from .serializers import (
    AnalysisResponseSerializer,
    AnalyzeRequestSerializer,
    GenerateCoverLetterRequestSerializer,
    GenerateCoverLetterResponseSerializer,
    ScanRequestSerializer,
    ScanResultSerializer,
)

logger = logging.getLogger(__name__)


class ApplicationScanView(APIView):
    def post(self, request) -> Response:
        serializer = ScanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = ScanRequestDTO(
            url=serializer.validated_data["url"],
            form_snapshot=[dict(f) for f in serializer.validated_data["form_snapshot"]],
            cv_id=serializer.validated_data["cv_id"],
            page_text=serializer.validated_data["page_text"],
            about_text=serializer.validated_data["about_text"],
            eeo_answers=[dict(row) for row in serializer.validated_data["eeo_answers"]],
        )
        service = ApplicationsContainer.application_service()
        result = service.scan(payload)
        return Response(ScanResultSerializer(result).data, status=status.HTTP_201_CREATED)


class GenerateCoverLetterView(APIView):
    def post(self, request) -> Response:
        serializer = GenerateCoverLetterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ApplicationsContainer.application_service()
        try:
            result = service.regenerate_cover_letter(
                application_id=serializer.validated_data["application_id"],
                page_text=serializer.validated_data["page_text"],
                about_text=serializer.validated_data["about_text"],
            )
        except ApplicationNotFoundError:
            raise Http404
        except NoCvOnApplicationError:
            return Response(
                {"detail": "select a CV and re-scan before generating a cover letter"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MimoNotConfiguredError:
            return Response(
                {"detail": "MiMo is not configured on this server"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception("Cover letter generation failed")
            return Response(
                {"detail": "cover letter generation failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(GenerateCoverLetterResponseSerializer(result).data)


class AnalyzeApplicationView(APIView):
    def post(self, request) -> Response:
        serializer = AnalyzeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ApplicationsContainer.application_service()
        try:
            result = service.analyze_application(
                application_id=serializer.validated_data["application_id"],
                page_text=serializer.validated_data["page_text"],
                about_text=serializer.validated_data["about_text"],
            )
        except ApplicationNotFoundError:
            raise Http404
        except NoCvOnApplicationError:
            return Response(
                {"detail": "select a CV and re-scan before analyzing"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MimoNotConfiguredError:
            return Response(
                {"detail": "MiMo is not configured on this server"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except SearchNotConfiguredError:
            return Response(
                {"detail": "web search is not configured on this server"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception("Application analysis failed")
            return Response(
                {"detail": "application analysis failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(AnalysisResponseSerializer(result).data)
