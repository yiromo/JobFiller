from django.http import FileResponse, Http404
from rest_framework.response import Response
from rest_framework.views import APIView

from . import evidence, inbox, state


class HunterStatusView(APIView):
    def get(self, request):
        snapshot = state.read_snapshot()
        if not snapshot:
            return Response({"up": False})
        return Response({"up": state.is_up(snapshot.get("agent")), **snapshot})


class HunterEvidenceView(APIView):
    def get(self, request, key, name):
        folder = evidence.folder(key)
        if folder is None or name not in evidence.FILES or not (folder / name).is_file():
            raise Http404
        response = FileResponse((folder / name).open("rb"), content_type=evidence.FILES[name])
        response["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class HunterEeoView(APIView):
    def get(self, request):
        return Response({"answers": inbox.read_eeo()})

    def put(self, request):
        try:
            answers = inbox.write_eeo(request.data.get("answers"))
        except (TypeError, ValueError, AttributeError) as error:
            return Response({"error": str(error)}, status=400)
        except OSError as error:
            return Response({"error": f"could not save: {error}"}, status=500)
        return Response({"answers": answers})


class HunterLetterView(APIView):
    def get(self, request):
        return Response({"size": inbox.read_letter_size()})

    def put(self, request):
        try:
            size = inbox.write_letter_size(request.data.get("size"))
        except (TypeError, ValueError) as error:
            return Response({"error": str(error)}, status=400)
        except OSError as error:
            return Response({"error": f"could not save: {error}"}, status=500)
        return Response({"size": size})


class HunterScopeView(APIView):
    def get(self, request):
        return Response({"scope": inbox.read_apply_scope()})

    def put(self, request):
        try:
            scope = inbox.write_apply_scope(request.data.get("scope"))
        except (TypeError, ValueError) as error:
            return Response({"error": str(error)}, status=400)
        except OSError as error:
            return Response({"error": f"could not save: {error}"}, status=500)
        return Response({"scope": scope})
