"""Health check endpoints for Kubernetes liveness/readiness probes."""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def healthz(request):
    """Minimal health check endpoint for Kubernetes probes.

    Returns 200 OK with no DB or S3 dependencies. Designed to be used by
    Kubernetes liveness and readiness probes.
    """
    return Response({"status": "ok"}, status=200)
