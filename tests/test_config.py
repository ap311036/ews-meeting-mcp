from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ews_meeting_agent.config import EwsConfig, keychain_status, setup_check


class ConfigTests(unittest.TestCase):
    def test_from_env_uses_keychain_when_password_is_not_in_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "EWS_ENDPOINT": "https://example.test/EWS/Exchange.asmx",
                        "EWS_EMAIL": "snoop.yu@example.test",
                        "EWS_USERNAME": "LINEBANK\\snoop.yu",
                        "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
                        "EWS_PASSWORD_KEYCHAIN_ACCOUNT": "LINEBANK\\snoop.yu",
                    },
                    clear=True,
                ):
                    with patch("subprocess.run") as run:
                        run.return_value = subprocess.CompletedProcess(
                            args=[],
                            returncode=0,
                            stdout="secret-from-keychain\n",
                            stderr="",
                        )

                        config = EwsConfig.from_env()

                self.assertEqual(config.password, "secret-from-keychain")
                run.assert_called_once_with(
                    [
                        "security",
                        "find-generic-password",
                        "-s",
                        "ews-meeting-mcp",
                        "-a",
                        "LINEBANK\\snoop.yu",
                        "-w",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            finally:
                os.chdir(old_cwd)

    def test_from_env_prefers_environment_password_over_keychain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "EWS_ENDPOINT": "https://example.test/EWS/Exchange.asmx",
                        "EWS_EMAIL": "snoop.yu@example.test",
                        "EWS_USERNAME": "LINEBANK\\snoop.yu",
                        "EWS_PASSWORD": "secret-from-env",
                        "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
                    },
                    clear=True,
                ):
                    with patch("subprocess.run") as run:
                        config = EwsConfig.from_env()

                self.assertEqual(config.password, "secret-from-env")
                run.assert_not_called()
            finally:
                os.chdir(old_cwd)

    def test_keychain_status_reports_environment_password_without_exposing_it(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EWS_USERNAME": "bk00325",
                "EWS_PASSWORD": "secret-from-env",
                "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
            },
            clear=True,
        ):
            with patch("subprocess.run") as run:
                status = keychain_status()

        self.assertTrue(status["configured"])
        self.assertEqual(status["source"], "environment")
        self.assertNotIn("secret-from-env", str(status))
        run.assert_not_called()

    def test_keychain_status_loads_dotenv_before_checking_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with open(".env", "w", encoding="utf-8") as env_file:
                    env_file.write("EWS_USERNAME=bk00325\nEWS_PASSWORD=secret-from-dotenv\n")

                with patch.dict(os.environ, {}, clear=True):
                    with patch("subprocess.run") as run:
                        status = keychain_status()
            finally:
                os.chdir(old_cwd)

        self.assertTrue(status["configured"])
        self.assertEqual(status["source"], "environment")
        self.assertEqual(status["account"], "bk00325")
        self.assertNotIn("secret-from-dotenv", str(status))
        run.assert_not_called()

    def test_keychain_status_reports_missing_item_with_setup_command(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EWS_USERNAME": "bk00325",
                "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
            },
            clear=True,
        ):
            with patch("subprocess.run") as run:
                run.side_effect = subprocess.CalledProcessError(44, ["security"])

                status = keychain_status()

        self.assertFalse(status["configured"])
        self.assertEqual(status["source"], "missing")
        self.assertEqual(status["service"], "ews-meeting-mcp")
        self.assertEqual(status["account"], "bk00325")
        self.assertIn("security add-generic-password", status["setup_command"])
        self.assertIn("-a bk00325", status["setup_command"])
        self.assertEqual(status["error_code"], "credentials_missing")
        self.assertEqual(status["required_action"], "show_setup_command")
        self.assertIn("顯示並執行", status["user_message"])
        self.assertIn(status["setup_command"], status["user_message"])

    def test_setup_check_reports_missing_credentials_without_live_ews(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "EWS_ENDPOINT": "https://example.test/EWS/Exchange.asmx",
                        "EWS_EMAIL": "snoop.yu@example.test",
                        "EWS_USERNAME": "bk00325",
                        "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
                    },
                    clear=True,
                ):
                    with patch("subprocess.run") as run:
                        run.side_effect = subprocess.CalledProcessError(44, ["security"])

                        status = setup_check()
            finally:
                os.chdir(old_cwd)

        self.assertFalse(status["ready"])
        self.assertEqual(status["next_action"], "show_setup_command")
        self.assertEqual(status["error_code"], "credentials_missing")
        self.assertIn("setup_command", status)
        self.assertIn("user_message", status)
        checks = {check["name"]: check for check in status["checks"]}
        self.assertTrue(checks["env:EWS_ENDPOINT"]["ok"])
        self.assertTrue(checks["env:EWS_EMAIL"]["ok"])
        self.assertTrue(checks["env:EWS_USERNAME"]["ok"])
        self.assertFalse(checks["keychain_or_password"]["ok"])
        self.assertEqual(checks["keychain_or_password"]["error_code"], "credentials_missing")

    def test_setup_check_reports_env_password_ready_when_other_env_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "EWS_PASSWORD": "secret-from-env",
                    },
                    clear=True,
                ):
                    with patch("subprocess.run") as run:
                        status = setup_check()
            finally:
                os.chdir(old_cwd)

        self.assertFalse(status["ready"])
        self.assertEqual(status["next_action"], "fix_mcp_env")
        checks = {check["name"]: check for check in status["checks"]}
        self.assertTrue(checks["keychain_or_password"]["ok"])
        self.assertEqual(checks["keychain_or_password"]["source"], "environment")
        self.assertNotIn("secret-from-env", str(status))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
