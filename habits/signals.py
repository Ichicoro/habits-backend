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
