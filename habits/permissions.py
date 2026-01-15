from rest_framework import permissions


class IsInBoardPermission(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.board.users.filter(user=request.user).exists()
