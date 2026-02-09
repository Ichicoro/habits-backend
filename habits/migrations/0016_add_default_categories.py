from django.db import migrations
import uuid

# Generated migration to add default expense categories


def add_default_categories(apps, schema_editor):
    """Add default expense categories available to all users."""
    ExpenseCategory = apps.get_model("habits", "ExpenseCategory")

    default_categories = [
        {"name": "Food", "emoji": "🍔"},
        {"name": "Transportation", "emoji": "🚗"},
        {"name": "Entertainment", "emoji": "🎬"},
        {"name": "Shopping", "emoji": "🛍️"},
        {"name": "Utilities", "emoji": "💡"},
        {"name": "Other", "emoji": "📌"},
    ]

    for category_data in default_categories:
        ExpenseCategory.objects.get_or_create(
            name=category_data["name"],
            defaults={
                "emoji": category_data["emoji"],
                "board": None,
            },
        )


def remove_default_categories(apps, schema_editor):
    """Remove default expense categories."""
    ExpenseCategory = apps.get_model("habits", "ExpenseCategory")
    ExpenseCategory.objects.filter(board__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("habits", "0015_remove_expensecategory_description_and_more"),
    ]

    operations = [
        migrations.RunPython(add_default_categories, remove_default_categories),
    ]
