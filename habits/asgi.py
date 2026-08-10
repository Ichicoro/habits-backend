"""
ASGI config for habits project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "habits.settings")

# Must run before anything imports models - habits.routing pulls in consumers,
# which pull in the app registry.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.conf import settings  # noqa: E402

routes = {"http": django_asgi_app}

if settings.REALTIME_ENABLED:
    from habits.routing import websocket_urlpatterns  # noqa: E402

    # No OriginValidator: the clients are native apps, which send no Origin
    # header, and auth is per-token on the socket itself rather than by cookie -
    # so there is no ambient authority for a cross-origin page to borrow.
    routes["websocket"] = URLRouter(websocket_urlpatterns)

application = ProtocolTypeRouter(routes)
