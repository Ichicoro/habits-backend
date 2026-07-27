from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from habits.models import User, Board, BoardUser, Habit, Expense, ExpenseSplit, ExpenseCategory
from habits.serializers import UserSerializer, BoardSerializer, HabitSerializer, ExpenseSerializer
from uuid import uuid4
import random


class UserModelTests(TestCase):
    """Tests for the User model."""

    def create_random_user(self):
        uuid = uuid4().__str__()
        return User.objects.create_user(
            username=uuid,
            email=f"{uuid}@example.com",
            password="testpassword123",
        )

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpassword123"
        )

    def test_user_creation(self):
        """Test user creation and attributes."""
        assert self.user.username == "testuser"
        assert self.user.email == "test@example.com"
        assert self.user.is_active is True
        assert self.user.is_staff is False
        assert self.user.is_superuser is False

    def test_user_has_no_default_board(self):
        """Test that no board is created automatically for a new user."""
        board = Board.objects.filter(created_by=self.user).first()
        assert board is None, "A board was unexpectedly created for the user"

    def test_user_string_representation(self):
        """Test the string representation of a user."""
        self.assertEqual(str(self.user.username), "testuser")

    def test_simple_equal_expense(self):
        """Test creating an expense and its splits."""
        board = Board.objects.create(
            name="Test Board", description="A board for testing", created_by=self.user
        )
        BoardUser.objects.create(user=self.user, board=board)
        user2 = self.create_random_user()
        BoardUser.objects.create(user=user2, board=board)

        expense = Expense.objects.create(
            payer=self.user,
            board=board,
            amount=Decimal("100.00"),
            description="Test Expense",
            split_type="equal",
        )

        (expensesplit1, _) = ExpenseSplit.objects.get_or_create(
            expense=expense, user=self.user, share_amount=Decimal("50.00")
        )
        (expensesplit2, _) = ExpenseSplit.objects.get_or_create(
            expense=expense, user=user2, share_amount=Decimal("50.00")
        )

        assert expensesplit1 is not None, "ExpenseSplit for user1 was not created"
        assert expensesplit2 is not None, "ExpenseSplit for user2 was not created"
        assert expensesplit1.share_amount == Decimal("50.00"), "Incorrect share amount for user1"
        assert expensesplit2.share_amount == Decimal("50.00"), "Incorrect share amount for user2"

        assert expense.amount == Decimal("100.00")
        assert expense.splits.count() == 2  # type: ignore

        assert self.user.balance_in_board(board) == Decimal("50.00")
        assert user2.balance_in_board(board) == Decimal("-50.00")

    def test_amount_split_expense(self):
        """Test creating an expense with amount splits."""
        board = Board.objects.create(
            name="Amount Split Board",
            description="Board for amount split testing",
            created_by=self.user,
        )
        BoardUser.objects.create(user=self.user, board=board)
        user2 = self.create_random_user()
        BoardUser.objects.create(user=user2, board=board)

        expense = Expense.objects.create(
            payer=self.user,
            board=board,
            amount=Decimal("120.00"),
            description="Amount Split Expense",
            split_type="amount",
        )

        ExpenseSplit.objects.create(expense=expense, user=self.user, share_amount=Decimal("70.00"))
        ExpenseSplit.objects.create(expense=expense, user=user2, share_amount=Decimal("50.00"))

        expensesplit1 = ExpenseSplit.objects.get(expense=expense, user=self.user)
        expensesplit2 = ExpenseSplit.objects.get(expense=expense, user=user2)

        assert expensesplit1.share_amount == Decimal("70.00"), "Incorrect share amount for user1"
        assert expensesplit2.share_amount == Decimal("50.00"), "Incorrect share amount for user2"

        assert expense.amount == Decimal("120.00")
        assert expense.splits.count() == 2  # type: ignore

        assert self.user.balance_in_board(board) == Decimal("50.00")
        assert user2.balance_in_board(board) == Decimal("-50.00")


class APITests(APITestCase):
    """Tests for the API endpoints."""

    def create_random_user(self):
        uuid = uuid4().__str__()
        return User.objects.create_user(
            username=uuid,
            email=f"{uuid}@example.com",
            password="testpassword123",
        )

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="apiuser", email="api@example.com", password="apipassword123"
        )
        self.client.force_authenticate(user=self.user)

    def test_new_user_has_no_boards(self):
        """Test that a newly registered user has no boards until they create/join one."""
        url = reverse("board-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        boards = response.json()["results"]
        self.assertEqual(len(boards), 0)

    def test_check_username_available(self):
        url = reverse("user-check-username")
        response = self.client.get(url, {"username": "someone-new"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["available"])

    def test_check_username_taken(self):
        # Checked from another user's perspective, since a user's own
        # username should never count as "taken" against themselves.
        client = APIClient()
        client.force_authenticate(user=self.create_random_user())
        url = reverse("user-check-username")
        response = client.get(url, {"username": "apiuser"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["available"])

    def test_check_username_case_insensitive(self):
        client = APIClient()
        client.force_authenticate(user=self.create_random_user())
        url = reverse("user-check-username")
        response = client.get(url, {"username": "APIUSER"})
        self.assertFalse(response.json()["available"])

    def test_check_username_excludes_self(self):
        # The current user's own username should count as available to them.
        self.client.force_authenticate(user=self.user)
        url = reverse("user-check-username")
        response = self.client.get(url, {"username": "apiuser"})
        self.assertTrue(response.json()["available"])

    def test_check_username_unauthenticated_allowed(self):
        client = APIClient()
        url = reverse("user-check-username")
        response = client.get(url, {"username": "apiuser"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["available"])

    def test_update_username_collision_rejected(self):
        other = self.create_random_user()
        url = reverse("user-detail", args=[self.user.id])
        response = self.client.patch(url, {"username": other.username}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_username_to_own_current_value_allowed(self):
        url = reverse("user-detail", args=[self.user.id])
        response = self.client.patch(url, {"username": "apiuser"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_check_email_taken(self):
        client = APIClient()
        client.force_authenticate(user=self.create_random_user())
        url = reverse("user-check-email")
        response = client.get(url, {"email": "api@example.com"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["available"])

    def test_check_email_available(self):
        url = reverse("user-check-email")
        response = self.client.get(url, {"email": "nobody@example.com"})
        self.assertTrue(response.json()["available"])

    def test_check_email_excludes_self(self):
        url = reverse("user-check-email")
        response = self.client.get(url, {"email": "api@example.com"})
        self.assertTrue(response.json()["available"])

    def test_update_email_collision_rejected(self):
        other = self.create_random_user()
        url = reverse("user-detail", args=[self.user.id])
        response = self.client.patch(url, {"email": other.email}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_email_collision_rejected(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "brandnewuser",
                "email": "api@example.com",
                "password": "somepassword123",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_and_get_board(self):
        """Test creating a board via the API and retrieving it."""
        url = reverse("board-list")
        response = self.client.post(
            url, {"name": "My Board", "description": "A board"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        created = response.json()

        url = reverse("board-detail", args=[created["id"]])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        board = response.json()
        self.assertEqual(board["name"], "My Board")
        self.assertEqual(board["description"], "A board")
        self.assertEqual(board["created_by"], str(self.user.id))

    def test_user_create_expense(self):
        """Test creating an expense via API."""
        board = Board.objects.create(name="Test Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)
        user2 = self.create_random_user()
        BoardUser.objects.create(user=user2, board=board)
        url = reverse("board-expenses-list", kwargs={"board_pk": str(board.id)})
        data = {
            "payer_id": str(self.user.id),
            "amount": "200.00",
            "description": "API Created Expense",
            "split_type": "equal",
        }
        response = self.client.post(url, data, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        expense = response.json()
        assert expense["amount"] == 200.00
        assert expense["description"] == "API Created Expense"
        assert expense["split_type"] == "equal"
        assert len(expense["splits"]) == 2

        # Test creating an expense only for two out of three users
        user3 = self.create_random_user()
        BoardUser.objects.create(user=user3, board=board)
        data = {
            "payer_id": str(self.user.id),
            "amount": "200.00",
            "description": "API Created Expense 2",
            "split_type": "equal",
            "splits": [
                {"user": str(self.user.id)},
                {"user": str(user2.id)},
            ],
        }
        response = self.client.post(url, data, format="json")
        assert response.status_code == status.HTTP_201_CREATED, f"Error: {response.content}"
        expense = response.json()
        assert expense["amount"] == 200.00
        assert expense["description"] == "API Created Expense 2"
        assert expense["split_type"] == "equal"
        assert len(expense["splits"]) == 2

    def test_user_various_expenses(self):
        """Test creating and updating various types of expenses via API."""
        board = Board.objects.create(name="Test Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)
        user2 = self.create_random_user()
        user3 = self.create_random_user()
        BoardUser.objects.create(user=user2, board=board)
        BoardUser.objects.create(user=user3, board=board)

        # 1. Equal split among three users
        url = reverse("board-expenses-list", kwargs={"board_pk": str(board.id)})
        data_equal = {
            "payer_id": str(self.user.id),
            "amount": "90.00",
            "description": "Equal Split Expense",
            "split_type": "equal",
        }
        response = self.client.post(url, data_equal, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        expense_equal = response.json()
        assert expense_equal["split_type"] == "equal"
        assert len(expense_equal["splits"]) == 3
        assert all(s["share_amount"] == 30.00 for s in expense_equal["splits"]) == True

        # 2. Amount split among three users
        data_amount = {
            "payer_id": str(user2.id),
            "amount": "120.00",
            "description": "Amount Split Expense",
            "split_type": "amount",
            "splits": [
                {"user": str(self.user.id), "share_amount": "40.00"},
                {"user": str(user2.id), "share_amount": "50.00"},
                {"user": str(user3.id), "share_amount": "30.00"},
            ],
        }
        response = self.client.post(url, data_amount, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        expense_amount = response.json()
        assert expense_amount["split_type"] == "amount"
        assert len(expense_amount["splits"]) == 3
        assert sorted([Decimal(s["share_amount"]) for s in expense_amount["splits"]]) == [
            Decimal("30.00"),
            Decimal("40.00"),
            Decimal("50.00"),
        ]

        # 3. Update the amount split expense to change shares
        expense_id = expense_amount["id"]
        url_detail = reverse("expense-detail", kwargs={"id": expense_id})
        update_data = {
            "splits": [
                {"user": str(self.user.id), "share_amount": "60.00"},
                {"user": str(user2.id), "share_amount": "30.00"},
                {"user": str(user3.id), "share_amount": "30.00"},
            ]
        }
        response = self.client.patch(url_detail, update_data, format="json")
        assert response.status_code == status.HTTP_200_OK, f"Error: {response.content}"
        updated_expense = response.json()
        self.assertEqual(
            sorted([Decimal(s["share_amount"]) for s in updated_expense["splits"]]),
            [Decimal("30.00"), Decimal("30.00"), Decimal("60.00")],
        )

        # 4. Create an expense with only two users (custom splits)
        data_custom = {
            "payer_id": str(user3.id),
            "amount": "50.00",
            "description": "Custom Split Expense",
            "split_type": "amount",
            "splits": [
                {"user": str(self.user.id), "share_amount": "20.00"},
                {"user": str(user3.id), "share_amount": "30.00"},
            ],
        }
        response = self.client.post(url, data_custom, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        expense_custom = response.json()
        self.assertEqual(expense_custom["split_type"], "amount")
        self.assertEqual(len(expense_custom["splits"]), 2)
        self.assertEqual(
            sorted([Decimal(s["share_amount"]) for s in expense_custom["splits"]]),
            [Decimal("20.00"), Decimal("30.00")],
        )

    def test_create_expense_category(self):
        """Test creating a board-scoped expense category via the API."""
        board = Board.objects.create(name="Test Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)
        url = reverse("board-expense-categories-list", kwargs={"board_pk": str(board.id)})
        response = self.client.post(url, {"name": "Groceries", "emoji": "🛒"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        category = response.json()
        self.assertEqual(category["name"], "Groceries")
        self.assertEqual(category["emoji"], "🛒")
        self.assertEqual(ExpenseCategory.objects.get(id=category["id"]).board_id, board.id)

    def test_create_expense_category_requires_board_membership(self):
        board = Board.objects.create(name="Test Board", created_by=self.user)
        url = reverse("board-expense-categories-list", kwargs={"board_pk": str(board.id)})
        response = self.client.post(url, {"name": "Groceries", "emoji": "🛒"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_nested_board_expenses_list(self):
        """Test retrieving expenses for a specific board via nested route."""
        board = Board.objects.create(name="Test Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)
        user2 = self.create_random_user()
        BoardUser.objects.create(user=user2, board=board)

        # Create a second board with different expenses
        board2 = Board.objects.create(
            name="Second Board", description="Another board", created_by=self.user
        )
        BoardUser.objects.create(user=self.user, board=board2)

        # Create expenses in the first board
        url_nested = reverse("board-expenses-list", kwargs={"board_pk": str(board.id)})
        expense1_data = {
            "payer_id": str(self.user.id),
            "board": str(board.id),
            "amount": 100.00,
            "description": "Board 1 Expense 1",
            "split_type": "equal",
        }
        response = self.client.post(url_nested, expense1_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        expense2_data = {
            "payer_id": str(user2.id),
            "board": str(board.id),
            "amount": 50.00,
            "description": "Board 1 Expense 2",
            "split_type": "equal",
        }
        response = self.client.post(url_nested, expense2_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Create an expense in the second board
        url_nested2 = reverse("board-expenses-list", kwargs={"board_pk": str(board2.id)})
        expense3_data = {
            "payer_id": str(self.user.id),
            "board": str(board2.id),
            "amount": 75.00,
            "description": "Board 2 Expense 1",
            "split_type": "equal",
        }
        response = self.client.post(url_nested2, expense3_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Test retrieving expenses for board 1
        response = self.client.get(url_nested)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expenses = response.json()["results"]
        self.assertEqual(len(expenses), 2)
        descriptions = [e["description"] for e in expenses]
        self.assertIn("Board 1 Expense 1", descriptions)
        self.assertIn("Board 1 Expense 2", descriptions)
        self.assertNotIn("Board 2 Expense 1", descriptions)

        # Test retrieving expenses for board 2
        response = self.client.get(url_nested2)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expenses = response.json()["results"]
        self.assertEqual(len(expenses), 1)
        self.assertEqual(expenses[0]["description"], "Board 2 Expense 1")

    def test_nested_board_expenses_detail(self):
        """Test retrieving a specific expense via nested route."""
        board = Board.objects.create(name="Test Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)

        # Create an expense
        expense = Expense.objects.create(
            payer=self.user,
            board=board,
            amount=Decimal("200.00"),
            description="Detail Test Expense",
            split_type="equal",
        )
        ExpenseSplit.objects.create(expense=expense, user=self.user, share_amount=Decimal("200.00"))

        # Test retrieving via nested route
        url = reverse(
            "board-expenses-detail", kwargs={"board_pk": str(board.id), "id": str(expense.id)}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expense_data = response.json()
        self.assertEqual(expense_data["description"], "Detail Test Expense")
        self.assertEqual(expense_data["amount"], 200.00)
        self.assertEqual(expense_data["board"], str(board.id))

    def test_nested_board_expenses_update(self):
        """Test updating an expense via nested route."""
        board = Board.objects.create(name="Test Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)
        user2 = self.create_random_user()
        BoardUser.objects.create(user=user2, board=board)

        # Create an expense
        expense = Expense.objects.create(
            payer=self.user,
            board=board,
            amount=Decimal("150.00"),
            description="Update Test Expense",
            split_type="amount",
        )
        ExpenseSplit.objects.create(expense=expense, user=self.user, share_amount=Decimal("100.00"))
        ExpenseSplit.objects.create(expense=expense, user=user2, share_amount=Decimal("50.00"))

        # Update splits via nested route
        url = reverse(
            "board-expenses-detail", kwargs={"board_pk": str(board.id), "id": str(expense.id)}
        )
        update_data = {
            "splits": [
                {"user": str(self.user.id), "share_amount": 75.00},
                {"user": str(user2.id), "share_amount": 75.00},
            ]
        }
        response = self.client.patch(url, update_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, f"Error: {response.content}")
        updated_expense = response.json()
        self.assertEqual(
            sorted([Decimal(s["share_amount"]) for s in updated_expense["splits"]]),
            [Decimal("75.00"), Decimal("75.00")],
        )

    def test_nested_board_expenses_permission(self):
        """Test that users can't access expenses from boards they're not members of."""
        # Create another user with their own board
        other_user = self.create_random_user()
        other_board = Board.objects.create(
            name="Other User Board", description="Not accessible", created_by=other_user
        )
        BoardUser.objects.create(user=other_user, board=other_board)

        # Create an expense in the other user's board
        other_expense = Expense.objects.create(
            payer=other_user,
            board=other_board,
            amount=Decimal("100.00"),
            description="Private Expense",
            split_type="equal",
        )
        ExpenseSplit.objects.create(
            expense=other_expense, user=other_user, share_amount=Decimal("100.00")
        )

        # Try to access via nested route - should be forbidden
        url = reverse("board-expenses-list", kwargs={"board_pk": str(other_board.id)})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_leave_board_with_other_members(self):
        """A user can leave a board as long as another member remains."""
        board = Board.objects.create(name="Shared Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)
        user2 = self.create_random_user()
        BoardUser.objects.create(user=user2, board=board)

        url = reverse("board-leave", args=[str(board.id)])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BoardUser.objects.filter(board=board, user=self.user).exists())
        self.assertTrue(BoardUser.objects.filter(board=board, user=user2).exists())

    def test_cannot_leave_board_as_sole_member(self):
        """A user can't leave a board they're the only member of."""
        board = Board.objects.create(name="Solo Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)

        url = reverse("board-leave", args=[str(board.id)])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(BoardUser.objects.filter(board=board, user=self.user).exists())

    def test_delete_only_board(self):
        """Deleting a user's only board should succeed and cascade to its expenses."""
        board = Board.objects.create(name="Solo Board", created_by=self.user)
        BoardUser.objects.create(user=self.user, board=board)
        expense = Expense.objects.create(
            payer=self.user,
            board=board,
            amount=Decimal("10.00"),
            description="Soon deleted",
            split_type="equal",
        )
        ExpenseSplit.objects.create(expense=expense, user=self.user, share_amount=Decimal("10.00"))

        url = reverse("board-detail", args=[str(board.id)])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Board.objects.filter(id=board.id).exists())
        self.assertFalse(Expense.objects.filter(board_id=board.id).exists())

        response = self.client.get(reverse("board-list"))
        self.assertEqual(response.json()["results"], [])
