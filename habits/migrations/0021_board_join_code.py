import secrets

from django.db import migrations, models

from habits.models import generate_join_code


def backfill_join_codes(apps, schema_editor):
    Board = apps.get_model("habits", "Board")
    existing = set(Board.objects.exclude(join_code=None).values_list("join_code", flat=True))
    for board in Board.objects.filter(join_code=None):
        while True:
            code = f"{secrets.randbelow(1_000_000_000):09d}"
            if code not in existing:
                existing.add(code)
                break
        board.join_code = code
        board.save(update_fields=["join_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("habits", "0020_alter_board_options_alter_expense_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="board",
            name="join_code",
            field=models.CharField(max_length=9, null=True, editable=False),
        ),
        migrations.RunPython(backfill_join_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="board",
            name="join_code",
            field=models.CharField(
                max_length=9,
                unique=True,
                editable=False,
                default=generate_join_code,
            ),
        ),
    ]
