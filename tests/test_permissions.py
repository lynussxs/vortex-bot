from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.permissions import can_moderate, is_protected_role


class FakeRole:
    def __init__(self, position: int, permissions: object | None = None) -> None:
        self.position = position
        self.permissions = permissions or SimpleNamespace()

    def __ge__(self, other: "FakeRole") -> bool:
        return self.position >= other.position

    def __lt__(self, other: "FakeRole") -> bool:
        return self.position < other.position


class PermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = SimpleNamespace(owner_id=900)
        self.moderator = SimpleNamespace(id=10, guild=self.guild, top_role=FakeRole(5))
        self.target = SimpleNamespace(id=20, bot=False, top_role=FakeRole(3))
        self.bot_member = SimpleNamespace(id=99, top_role=FakeRole(10))

    def test_allows_target_below_moderator_and_bot(self) -> None:
        allowed, reason = can_moderate(self.moderator, self.target, self.bot_member)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_blocks_self_and_equal_or_higher_roles(self) -> None:
        self.target.id = self.moderator.id
        allowed, reason = can_moderate(self.moderator, self.target, self.bot_member)
        self.assertFalse(allowed)
        self.assertIn("yourself", reason)

        self.target.id = 20
        self.target.top_role = FakeRole(5)
        allowed, reason = can_moderate(self.moderator, self.target, self.bot_member)
        self.assertFalse(allowed)
        self.assertIn("equal or higher", reason)

    def test_blocks_target_above_bot(self) -> None:
        self.moderator.top_role = FakeRole(15)
        self.target.top_role = FakeRole(11)
        allowed, reason = can_moderate(self.moderator, self.target, self.bot_member)
        self.assertFalse(allowed)
        self.assertIn("Vortex", reason)

    def test_protected_role_permissions(self) -> None:
        protected = FakeRole(1, SimpleNamespace(administrator=True))
        normal = FakeRole(1, SimpleNamespace(administrator=False, manage_roles=False))
        self.assertTrue(is_protected_role(protected))
        self.assertFalse(is_protected_role(normal))
