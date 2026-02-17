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

import os
from django.urls import include, path, re_path
from django.contrib import admin
from django.urls import path
from django.views.static import serve
from rest_framework.authtoken import views

from habits.views import router

from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLUTTER_WEB_APP = os.path.join(BASE_DIR, "flutter-app")


def flutter_redirect(request, resource):
    return serve(request, resource, FLUTTER_WEB_APP)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/auth/login/", views.obtain_auth_token),
    path("api/", include(router.urls)),
    # Flutter SPA - serve for all non-API, non-admin routes
    path("", lambda r: flutter_redirect(r, "index.html")),
    re_path(r"^(?!api/)(?!admin/)(?!static/)(?P<resource>.*)$", flutter_redirect),
]
