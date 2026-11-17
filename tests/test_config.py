from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from config import Settings


class ConfigurationTests(unittest.TestCase):
    def test_token_is_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DISCORD_TOKEN is required"):
                Settings.from_env()

    def test_model_and_numeric_limits_are_validated(self) -> None:
        with patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "test-token", "AI_MODEL": "invalid model"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "AI_MODEL"):
                Settings.from_env()

        with patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "test-token", "AI_MAX_TOKENS": "9000"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "AI_MAX_TOKENS"):
                Settings.from_env()

    def test_defaults_are_lightweight_and_bounded(self) -> None:
        with patch.dict(os.environ, {"DISCORD_TOKEN": "test-token"}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.ai_model, "openai/gpt-4o-mini")
        self.assertEqual(settings.ai_max_tokens, 500)
        self.assertEqual(settings.ai_cooldown, 10)
        self.assertEqual(settings.database_path, settings.database_fallback_path)
        self.assertEqual(settings.runtime_environment, "local")


class OwnerOnlyConfigTests(unittest.TestCase):
    def test_ai_owner_only_defaults_to_true_and_can_be_disabled(self) -> None:
        with patch.dict(os.environ, {"DISCORD_TOKEN": "t"}, clear=True):
            self.assertTrue(Settings.from_env().ai_owner_only)
        with patch.dict(os.environ, {"DISCORD_TOKEN": "t", "AI_OWNER_ONLY": "false"}, clear=True):
            self.assertFalse(Settings.from_env().ai_owner_only)
