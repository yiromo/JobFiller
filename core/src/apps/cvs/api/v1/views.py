from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.cv_writer import CvGenerationError, ToolchainMissing
from apps.cvs.container import CvsContainer

from .serializers import CvGenerateSerializer, CvSerializer, CvUploadSerializer


class CvListCreateView(APIView):
    def get(self, request) -> Response:
        service = CvsContainer.cv_service()
        cvs = service.list_cvs()
        return Response(CvSerializer(cvs, many=True).data)

    def post(self, request) -> Response:
        serializer = CvUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]

        service = CvsContainer.cv_service()
        cv = service.upload(uploaded, uploaded.name)
        return Response(CvSerializer(cv).data, status=status.HTTP_201_CREATED)


class CvFileDownloadView(APIView):
    def get(self, request, cv_id: int) -> FileResponse:
        service = CvsContainer.cv_service()
        cv = service.get(cv_id)
        if cv is None:
            raise Http404
        return FileResponse(open(cv.file_path, "rb"), filename=cv.original_filename)


class CvGenerateView(APIView):
    def post(self, request, cv_id: int) -> Response:
        serializer = CvGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = CvsContainer.cv_service()
        try:
            result = service.generate_from(
                cv_id,
                serializer.validated_data["instructions"],
                serializer.validated_data["position_text"],
                serializer.validated_data["filename"],
            )
        except ToolchainMissing as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except CvGenerationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        if result is None:
            raise Http404
        cv, added_skills = result
        return Response(
            {**CvSerializer(cv).data, "added_skills": added_skills},
            status=status.HTTP_201_CREATED,
        )


class CvDetailView(APIView):
    def delete(self, request, cv_id: int) -> Response:
        service = CvsContainer.cv_service()
        if not service.delete(cv_id):
            raise Http404
        return Response(status=status.HTTP_204_NO_CONTENT)
