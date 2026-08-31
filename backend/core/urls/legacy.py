"""Frozen contract for the Client API.

Adding routes here changes the Client API surface. Do not edit casually.
"""

from django.urls import path, re_path

from core.views import legacy as v
from core.views import health as h

urlpatterns = [
    path("healthz/", h.healthz),  # GET — health check for K8s probes
    path("runs", v.runs_create),  # POST
    path("tests", v.tests_create),  # POST
    path("tests/<int:pk>/status", v.tests_detail),  # GET — poll for async status
    path("tests/<int:pk>", v.tests_update),  # PATCH/PUT
    re_path(r"^baselines/(?P<key>[a-z0-9-]+)\.png$", v.baseline_png),  # GET
    re_path(r"^baselines/(?P<key>[a-z0-9-]+)\.json$", v.baseline_json),  # GET
]
