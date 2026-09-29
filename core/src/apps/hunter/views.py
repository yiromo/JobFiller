from rest_framework.response import Response
from rest_framework.views import APIView

from . import state


class HunterStatusView(APIView):
    def get(self, request):
        snapshot = state.read_snapshot()
        if not snapshot:
            return Response({"up": False})
        return Response({"up": state.is_up(snapshot.get("agent")), **snapshot})
