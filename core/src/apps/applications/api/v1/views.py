from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.container import ApplicationsContainer
from apps.applications.dto import ScanRequestDTO

from .serializers import ScanRequestSerializer, ScanResultSerializer


class ApplicationScanView(APIView):
    def post(self, request) -> Response:
        serializer = ScanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = ScanRequestDTO(
            url=serializer.validated_data["url"],
            form_snapshot=[dict(f) for f in serializer.validated_data["form_snapshot"]],
            cv_id=serializer.validated_data["cv_id"],
            page_text=serializer.validated_data["page_text"],
            eeo_answers=[dict(row) for row in serializer.validated_data["eeo_answers"]],
        )
        service = ApplicationsContainer.application_service()
        result = service.scan(payload)
        return Response(ScanResultSerializer(result).data, status=status.HTTP_201_CREATED)
