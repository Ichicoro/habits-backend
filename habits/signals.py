from django.db import transaction
from django.db.models import signals
from django.dispatch import receiver

from habits import images, models, realtime

# Uncomment the following signal handler to enable automatic equal splits for new expenses. For now, it is disabled as it is handled in the expense creation logic.


# @receiver(signals.post_save, sender=models.Expense)
# def auto_create_equal_split(sender, instance, created, **kwargs):
#     if created and instance.split_type == "equal":
#         num_parts = instance.board.users.count()
#         share = instance.amount / num_parts
#         for boarduser in instance.board.users.all():
#             models.ExpenseSplit.objects.get_or_create(
#                 expense=instance, user=boarduser.user, defaults={"share_amount": share}
#             )


# Realtime nudges.
#
# These live on model signals rather than in the viewsets so that every write
# path is covered by construction - including the admin, and the ModelViewSet
# defaults that habits.views never overrides. The tradeoff is that signals fire
# for writes that aren't interesting to other board members, so a couple are
# filtered out explicitly below.
#
# Nothing here can fail a request: broadcasts are deferred to on_commit and
# swallowed inside habits.realtime.


def _nudge(board_id, kind):
    transaction.on_commit(lambda: realtime.broadcast_board_changed(board_id, kind))


@receiver(signals.post_save, sender=models.Expense)
@receiver(signals.post_delete, sender=models.Expense)
def expense_changed(sender, instance, **kwargs):
    _nudge(instance.board_id, "expense")


@receiver(signals.post_save, sender=models.ExpenseSplit)
@receiver(signals.post_delete, sender=models.ExpenseSplit)
def expense_split_changed(sender, instance, **kwargs):
    # Splits determine each member's balance, so they matter even when the
    # parent expense row itself is untouched.
    _nudge(instance.expense.board_id, "expense")


@receiver(signals.post_save, sender=models.ExpenseCategory)
@receiver(signals.post_delete, sender=models.ExpenseCategory)
def expense_category_changed(sender, instance, **kwargs):
    # board is nullable: the seeded global default categories (migration 0016)
    # belong to no board and have nobody to notify.
    _nudge(instance.board_id, "category")


@receiver(signals.post_save, sender=models.Board)
def board_changed(sender, instance, created, update_fields=None, **kwargs):
    if created:
        # Nobody else is in the board yet, and the creator already has the
        # response from its own POST.
        return
    _nudge(instance.id, "board")


@receiver(signals.post_save, sender=models.BoardUser)
def board_user_changed(sender, instance, created, update_fields=None, **kwargs):
    # notify_on_expense is a private per-user preference that shouldn't wake the
    # whole board. Today the notifications endpoint writes it with a bulk
    # queryset .update(), which emits no post_save at all, so this guard is
    # belt-and-braces for whenever that turns into a plain .save().
    if update_fields and set(update_fields) == {"notify_on_expense"}:
        return
    _nudge(instance.board_id, "members")
    if created:
        transaction.on_commit(lambda: realtime.broadcast_membership_refresh(instance.user_id))


@receiver(signals.post_delete, sender=models.BoardUser)
def board_user_removed(sender, instance, **kwargs):
    _nudge(instance.board_id, "members")
    transaction.on_commit(lambda: realtime.broadcast_membership_refresh(instance.user_id))


# Profile pictures.
#
# Also on signals so the admin goes through the same path as the API. Old files
# are removed on commit: deleting them inside a transaction that later rolls
# back would leave the row pointing at nothing.


def _touches_profile_picture(update_fields):
    return update_fields is None or "profile_picture" in update_fields


@receiver(signals.pre_save, sender=models.User)
def prepare_profile_picture(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw or not _touches_profile_picture(update_fields):
        return
    picture = instance.profile_picture
    if picture and not picture._committed:
        # Raises ValidationError for anything that isn't a usable image.
        instance.profile_picture = images.process_profile_picture(picture)
    instance._previous_profile_picture = (
        None
        if instance._state.adding
        else sender.objects.filter(pk=instance.pk).values_list("profile_picture", flat=True).first()
    )


@receiver(signals.post_save, sender=models.User)
def remove_replaced_profile_picture(sender, instance, **kwargs):
    previous = getattr(instance, "_previous_profile_picture", None)
    instance._previous_profile_picture = None
    if previous and previous != instance.profile_picture.name:
        _delete_file_on_commit(instance.profile_picture.storage, previous)


@receiver(signals.post_delete, sender=models.User)
def remove_deleted_users_profile_picture(sender, instance, **kwargs):
    if instance.profile_picture:
        _delete_file_on_commit(instance.profile_picture.storage, instance.profile_picture.name)


def _delete_file_on_commit(storage, name):
    transaction.on_commit(lambda: storage.delete(name))
