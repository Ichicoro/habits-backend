import re

from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand

from habits.models import User

UPLOAD_DIR = "profile_pictures"
# What habits.images produces. Anything else predates it and may still carry
# EXIF/GPS, be full-size, or not be an image at all.
PROCESSED_NAME = re.compile(rf"{UPLOAD_DIR}/[0-9a-f]{{32}}\.jpg")


class Command(BaseCommand):
    help = (
        "Re-encode profile pictures uploaded before processing existed, clear "
        "references to missing files, and delete files no user points at."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without changing it.")

    def handle(self, *args, dry_run=False, **options):
        storage = User._meta.get_field("profile_picture").storage
        counts = {"reprocessed": 0, "cleared_missing": 0, "cleared_invalid": 0, "orphans_deleted": 0}

        for user in User.objects.exclude(profile_picture="").exclude(profile_picture=None):
            name = user.profile_picture.name
            if not storage.exists(name):
                self.stdout.write(f"missing: {name} ({user.username}) - clearing")
                counts["cleared_missing"] += 1
                if not dry_run:
                    user.profile_picture = None
                    user.save(update_fields=["profile_picture"])
                continue
            if PROCESSED_NAME.fullmatch(name):
                continue
            if dry_run:
                self.stdout.write(f"would reprocess: {name} ({user.username})")
                counts["reprocessed"] += 1
                continue
            try:
                with storage.open(name) as f:
                    user.profile_picture = File(f, name=name.rsplit("/", 1)[-1])
                    user.save(update_fields=["profile_picture"])
                self.stdout.write(f"reprocessed: {name} -> {user.profile_picture.name}")
                counts["reprocessed"] += 1
            except ValidationError:
                self.stdout.write(f"invalid image: {name} ({user.username}) - clearing")
                counts["cleared_invalid"] += 1
                user.refresh_from_db(fields=["profile_picture"])
                user.profile_picture = None
                user.save(update_fields=["profile_picture"])

        if storage.exists(UPLOAD_DIR):
            referenced = set(
                User.objects.exclude(profile_picture="")
                .exclude(profile_picture=None)
                .values_list("profile_picture", flat=True)
            )
            for filename in storage.listdir(UPLOAD_DIR)[1]:
                path = f"{UPLOAD_DIR}/{filename}"
                if path not in referenced:
                    self.stdout.write(f"orphan: {path}" + ("" if dry_run else " - deleted"))
                    counts["orphans_deleted"] += 1
                    if not dry_run:
                        storage.delete(path)

        summary = ", ".join(f"{k}={v}" for k, v in counts.items())
        self.stdout.write(self.style.SUCCESS(("[dry run] " if dry_run else "") + summary))
