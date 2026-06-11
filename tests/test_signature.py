from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from ews_meeting_mcp.signature import (
    append_signature,
    signature_setup_guide,
    signature_status,
)


class SignatureTests(unittest.TestCase):
    def test_append_signature_adds_configured_html_to_html_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "signature.html")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('<div class="sig">Best Regards,<br>Snoop Yu</div>')

            with patch.dict(os.environ, {"EWS_MEETING_SIGNATURE_HTML_PATH": path}, clear=True):
                rendered = append_signature("<p>Meeting agenda</p>", "html")

        self.assertIn("<p>Meeting agenda</p>", rendered)
        self.assertIn('<div class="ews-meeting-signature-separator"></div>', rendered)
        self.assertIn("Best Regards", rendered)
        self.assertIn("Snoop Yu", rendered)

    def test_append_signature_keeps_text_body_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "signature.html")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("<strong>HTML signature</strong>")

            with patch.dict(os.environ, {"EWS_MEETING_SIGNATURE_HTML_PATH": path}, clear=True):
                rendered = append_signature("Meeting agenda", "text")

        self.assertEqual(rendered, "Meeting agenda")

    def test_signature_status_reports_default_path_and_setup_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    status = signature_status()
            finally:
                os.chdir(old_cwd)

        self.assertFalse(status["configured"])
        self.assertTrue(status["enabled"])
        self.assertEqual(status["next_action"], "create_signature_file")
        self.assertTrue(str(status["path"]).endswith("ews-meeting-signature.html"))

    def test_signature_setup_guide_includes_copyable_sample_and_env(self) -> None:
        guide = signature_setup_guide()

        self.assertEqual(guide["default_enabled"], True)
        self.assertIn("EWS_MEETING_SIGNATURE_HTML_PATH", guide["env"])
        self.assertIn("ews-meeting-signature.html", guide["recommended_path"])
        self.assertIn("Best Regards", guide["sample_html"])
        self.assertIn("mailto:", guide["sample_html"])
        self.assertIn("LINE Bank", guide["sample_html"])


if __name__ == "__main__":
    unittest.main()
