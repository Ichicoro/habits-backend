from rest_framework import permissions
from habits import models


class IsInBoardPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        board_pk = view.kwargs.get("board_pk")
        if not board_pk:
            return True
        return models.BoardUser.objects.filter(board_id=board_pk, user=request.user).exists()

    def has_object_permission(self, request, view, obj):
        return obj.board.users.filter(user=request.user).exists()
