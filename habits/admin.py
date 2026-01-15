from django.contrib import admin
from . import models


class BoardUserInline(admin.TabularInline):
    model = models.BoardUser
    extra = 1
    fk_name = "user"


class ExpenseSplitInline(admin.TabularInline):
    model = models.ExpenseSplit
    extra = 1
    fk_name = "expense"


class BoardUserBoardInline(admin.TabularInline):
    model = models.BoardUser
    extra = 1
    fk_name = "board"


class UserModelAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "is_active", "is_staff", "is_superuser", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser", "date_joined")
    search_fields = ("username", "email")
    ordering = ("-date_joined",)
    inlines = [BoardUserInline]


class BoardModelAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "description", "created_by", "created_at", "updated_at")
    list_filter = ("created_by", "created_at", "updated_at")
    search_fields = ("name", "description")
    ordering = ("-created_at",)
    inlines = [BoardUserBoardInline]


class BoardUserModelAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "board", "joined_at")
    list_filter = ("joined_at", "board")
    search_fields = ("user__username", "board__name")
    ordering = ("-joined_at",)


class HabitModelAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "board",
        "name",
        "description",
        "frequency",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = ("board", "frequency", "is_active", "created_at", "updated_at")
    search_fields = ("name", "description")
    ordering = ("-created_at",)


class ExpenseModelAdmin(admin.ModelAdmin):
    list_display = ("id", "payer", "amount", "description", "created_at")
    list_filter = ("payer", "created_at")
    search_fields = ("description",)
    ordering = ("-created_at",)
    inlines = [ExpenseSplitInline]


admin.site.register(models.User, UserModelAdmin)
admin.site.register(models.Board, BoardModelAdmin)
admin.site.register(models.BoardUser, BoardUserModelAdmin)
admin.site.register(models.Habit, HabitModelAdmin)
admin.site.register(models.Expense, ExpenseModelAdmin)
