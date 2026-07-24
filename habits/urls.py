"""
URL configuration for habits project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.urls import include, path, re_path
from django.contrib import admin
from django.views.static import serve

from habits.views import (
    RegisterView,
    ThrottledObtainAuthToken,
    android_asset_links,
    apple_app_site_association,
    join_page,
    router,
)

from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/auth/login/", ThrottledObtainAuthToken.as_view()),
    path("api/auth/register/", RegisterView.as_view()),
    path("api/", include(router.urls)),
    # Serve user-uploaded media (e.g. profile pictures) unconditionally -
    # django.conf.urls.static.static() is a DEBUG-only no-op, which would
    # silently 404 all media in production.
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    # App store listings need a stable, non-static-versioned URL for these.
    path(
        "privacy",
        serve,
        {"document_root": settings.BASE_DIR / "static", "path": "privacy.html"},
    ),
    path(
        "data-deletion",
        serve,
        {"document_root": settings.BASE_DIR / "static", "path": "data-deletion.html"},
    ),
    path("join", join_page),
    # Universal Links / App Links verification files - must be served at
    # exactly these paths, unredirected, for iOS/Android to trust /join.
    path(".well-known/apple-app-site-association", apple_app_site_association),
    path(".well-known/assetlinks.json", android_asset_links),
]

if settings.DEBUG:
    # Hit this to confirm Sentry is receiving events. Not routed in production.
    urlpatterns.append(path("sentry-debug/", lambda request: 1 / 0))
