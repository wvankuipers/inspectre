from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # /admin/ — Django Admin, single shared is_staff login
    path("admin/", admin.site.urls),
    # /api/ — SPA-internal endpoints
    path("api/", include("core.urls.spa")),
    # Un-prefixed legacy endpoints — frozen for Client API compatibility
    # (decisions.md #7). Order matters: legacy routes must not shadow /api/.
    path("", include("core.urls.legacy")),
]
