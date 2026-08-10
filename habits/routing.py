from django.urls import path

from habits.consumers import BoardConsumer

websocket_urlpatterns = [
    path("ws/boards/", BoardConsumer.as_asgi()),
]
