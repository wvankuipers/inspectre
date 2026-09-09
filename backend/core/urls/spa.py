"""SPA-internal API. Free to evolve in lockstep with the frontend."""

from django.urls import path

from core.views import api as v

urlpatterns = [
    path("projects/", v.projects_list),
    path("projects/<slug:project>/", v.project_detail),
    path("projects/<slug:project>/validate/", v.project_validate),
    path("projects/<slug:project>/suites/<slug:suite>/", v.suite_detail),
    path(
        "projects/<slug:project>/suites/<slug:suite>/runs/<int:seq>/",
        v.run_detail,
    ),
    path(
        "projects/<slug:project>/suites/<slug:suite>/runs/<int:seq>/validate/",
        v.run_validate,
    ),
    path(
        "projects/<slug:project>/suites/<slug:suite>/tests/<str:key>/",
        v.test_history,
    ),
    path("tests/bulk/", v.tests_bulk),
    path("tests/<int:pk>/set-baseline/", v.set_baseline),
    path("baselines/<str:key>/", v.baseline_detail),
]
