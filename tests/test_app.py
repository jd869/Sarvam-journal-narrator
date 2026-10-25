"""Streamlit interactions with mocked Sarvam calls; never uses real credits."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from test_echoes import wav_bytes

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def button(app, label):
    return next(item for item in app.button if item.label == label)


def checkbox(app, label):
    return next(item for item in app.checkbox if item.label == label)


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "DEMO_PASSCODE": "offline-test-passcode",
            "SARVAM_API_KEY": "offline-test-not-a-real-key",
        })
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def open_app(self):
        app = AppTest.from_file(APP, default_timeout=20)
        app.session_state["authenticated"] = True
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_passcode_gate_and_missing_configuration(self):
        app = AppTest.from_file(APP, default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Public hackathon demo" in item.value for item in app.markdown))
        self.assertEqual(app.code[0].value, "offline-test-passcode")
        self.assertFalse(any(item.label == "✦ Create my recap" for item in app.button))
        app.text_input[0].set_value("incorrect")
        button(app, "Open my journal").click().run()
        self.assertEqual(len(app.error), 1)
        app.text_input[0].set_value("offline-test-passcode")
        button(app, "Open my journal").click().run()
        self.assertTrue(app.session_state["authenticated"])
        with patch.dict(os.environ, {"DEMO_PASSCODE": ""}):
            locked = AppTest.from_file(APP, default_timeout=20).run()
            self.assertEqual(len(locked.exception), 0)
            self.assertTrue(any("DEMO_PASSCODE" in warning.value for warning in locked.warning))
        with patch.dict(os.environ, {"SARVAM_API_KEY": ""}):
            journal = self.open_app()
            self.assertTrue(any("SARVAM_API_KEY" in warning.value for warning in journal.warning))
            self.assertTrue(button(journal, "▶ Narrate my memory").disabled)

    def test_full_demo_cache_and_no_paid_calls_on_rerun(self):
        with patch("echoes.SarvamGateway.summarize", return_value="I planted basil, shared chai, and showed up for my first hackathon.") as recap, \
             patch("echoes.SarvamGateway.narrate", return_value=wav_bytes()) as narrate:
            app = self.open_app()
            recap.assert_not_called()
            narrate.assert_not_called()
            button(app, "Load sample journal").click().run()
            self.assertEqual(len(app.session_state["entries"]), 3)
            button(app, "✦ Create my recap").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("planted basil", app.session_state["script_draft"])
            recap.assert_called_once()
            button(app, "▶ Narrate my memory").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("last_audio", app.session_state)
            narrate.assert_called_once()
            app.run()
            narrate.assert_called_once()
            button(app, "▶ Narrate my memory").click().run()
            narrate.assert_called_once()
            button(app, "✦ Create my recap").click().run()
            recap.assert_called_once()

    def test_failed_generation_keeps_draft_and_does_not_retry(self):
        with patch("echoes.SarvamGateway.narrate", side_effect=RuntimeError("offline")) as narrate:
            app = self.open_app()
            next(item for item in app.text_area if item.label == "Narration script").set_value("A memory worth keeping.").run()
            button(app, "▶ Narrate my memory").click().run()
            self.assertEqual(app.session_state["script_draft"], "A memory worth keeping.")
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 1)
            app.run()
            narrate.assert_called_once()

    def test_own_voice_requires_saved_reference_and_consent(self):
        with patch("echoes.SarvamGateway.narrate") as narrate:
            app = self.open_app()
            next(item for item in app.text_area if item.label == "Narration script").set_value("My memory.")
            next(item for item in app.radio if item.label == "Narrator").set_value("My own voice")
            app.run()
            self.assertTrue(button(app, "▶ Narrate my memory").disabled)
            app.session_state["reference"] = wav_bytes(10)
            app.run()
            self.assertTrue(button(app, "▶ Narrate my memory").disabled)
            checkbox(app, "This is my voice, and I consent to Sarvam processing and cloning it for this narration.").check().run()
            self.assertFalse(button(app, "▶ Narrate my memory").disabled)
            narrate.assert_not_called()
            button(app, "Forget my voice and generated audio").click().run()
            self.assertIsNone(app.session_state["reference"])
            self.assertFalse(app.session_state["voice_consent"])
            self.assertEqual(app.session_state["voice_mode"], "Sarvam narrator")

    def test_journal_edit_delete_and_script_limits(self):
        app = self.open_app()
        next(item for item in app.text_input if item.label == "Memory title").set_value("A good day")
        next(item for item in app.text_area if item.label == "Your words").set_value("I called home.")
        button(app, "Save this memory").click().run()
        self.assertEqual(len(app.session_state["entries"]), 1)
        next(item for item in app.text_area if item.label == "Entry").set_value("I called home and felt happy.")
        button(app, "Save changes").click().run()
        self.assertIn("felt happy", app.session_state["entries"][0].text)
        button(app, "Use as narration script").click().run()
        self.assertIn("felt happy", app.session_state["script_draft"])
        next(item for item in app.text_area if item.label == "Narration script").set_value("x" * 901).run()
        self.assertTrue(button(app, "▶ Narrate my memory").disabled)
        checkbox(app, "I want to delete this entry").check().run()
        button(app, "Delete memory").click().run()
        self.assertEqual(app.session_state["entries"], [])
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
