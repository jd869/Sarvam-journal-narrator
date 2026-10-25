import base64
from datetime import date
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
import wave

from echoes import (
    Entry, SarvamGateway, cached_narration, export_journal, friendly_error,
    import_journal, make_entry, select_entries, validate_reference,
)


def wav_bytes(seconds=1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buffer.getvalue()


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            make_entry(date(2024, 2, 29), "Leap day", "A walk."),
            make_entry(date(2025, 1, 1), "Beginning", "A new page."),
            make_entry(date(2025, 2, 1), "February", "चाय और बातें।"),
            make_entry(date(2025, 12, 31), "Ending", "A quiet evening."),
            make_entry(date(2026, 1, 1), "Next", "Another year."),
        ]

    def test_month_and_year_boundaries(self):
        self.assertEqual([e.title for e in select_entries(self.entries, 2025, 1)], ["Beginning"])
        self.assertEqual(len(select_entries(self.entries, 2025)), 3)
        self.assertEqual(len(select_entries(self.entries, 2024, 2)), 1)
        self.assertEqual(select_entries(self.entries, 2023), [])

    def test_round_trip_keeps_unicode_and_ids(self):
        self.assertEqual(import_journal(export_journal(self.entries).encode()), self.entries)

    def test_bad_import_is_rejected_atomically(self):
        valid = json.loads(export_journal(self.entries))
        invalids = [b"not json", b"[]", b'{"version": true, "entries": []}',
                    b'{"version": 1, "entries": {}}']
        invalids.append(json.dumps({"version": 1, "entries": [valid["entries"][0]] * 2}).encode())
        broken = valid["entries"][0].copy()
        broken["date"] = "2025-02-30"
        invalids.append(json.dumps({"version": 1, "entries": [broken]}).encode())
        invalids.append(b"x" * 1_000_001)
        for raw in invalids:
            with self.subTest(raw_size=len(raw)), self.assertRaises(ValueError):
                import_journal(raw)

    def test_empty_entries_are_rejected(self):
        with self.assertRaises(ValueError):
            make_entry(date.today(), " ", "Some words")


class AudioTests(unittest.TestCase):
    def test_reference_duration_and_type(self):
        self.assertEqual(validate_reference(wav_bytes(10)), 10)
        self.assertEqual(validate_reference(wav_bytes(15)), 15)
        for audio in (wav_bytes(9), wav_bytes(16), b"bad audio", b"x" * 10_000_001):
            with self.assertRaises(ValueError):
                validate_reference(audio)

    def test_identical_audio_is_reused_and_settings_change_key(self):
        gateway, cache = MagicMock(), {}
        gateway.narrate.return_value = wav_bytes()
        audio, reused = cached_narration(gateway, cache, "Hello", "en-IN")
        self.assertFalse(reused)
        self.assertEqual(cached_narration(gateway, cache, " Hello ", "en-IN"), (audio, True))
        gateway.narrate.assert_called_once()
        cached_narration(gateway, cache, "Hello", "hi-IN")
        cached_narration(gateway, cache, "Hello", "en-IN", wav_bytes(10))
        self.assertEqual(gateway.narrate.call_count, 3)

    def test_failure_is_not_cached_or_retried(self):
        gateway, cache = MagicMock(), {}
        gateway.narrate.side_effect = RuntimeError("unavailable")
        with self.assertRaises(RuntimeError):
            cached_narration(gateway, cache, "Hello", "en-IN")
        gateway.narrate.assert_called_once()
        self.assertEqual(cache, {})

    def test_cache_has_memory_bound(self):
        gateway, cache = MagicMock(), {}
        gateway.narrate.return_value = wav_bytes()
        for index in range(8):
            cached_narration(gateway, cache, str(index), "en-IN")
        self.assertEqual(len(cache), 5)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = SarvamGateway.__new__(SarvamGateway)
        self.gateway.client = MagicMock()
        self.audio = wav_bytes()
        encoded = base64.b64encode(self.audio).decode()
        self.gateway.client.text_to_speech.convert.return_value = SimpleNamespace(audios=[encoded])
        self.gateway.client.voice_cloning.convert.return_value = SimpleNamespace(audio_b64=encoded)

    def test_preset_call_disables_retries_and_saves_decodable_audio(self):
        self.assertEqual(self.gateway.narrate("Hello", "en-IN"), self.audio)
        kwargs = self.gateway.client.text_to_speech.convert.call_args.kwargs
        self.assertEqual(kwargs["model"], "bulbul:v4-flash")
        self.assertEqual(kwargs["request_options"]["max_retries"], 0)
        self.gateway.client.voice_cloning.convert.assert_not_called()

    def test_limits_are_checked_before_spending(self):
        for text in (" ", "x" * 901):
            with self.assertRaises(ValueError):
                self.gateway.narrate(text, "en-IN")
        with self.assertRaises(ValueError):
            self.gateway.narrate("Hello", "en-IN", wav_bytes(9))
        self.gateway.client.text_to_speech.convert.assert_not_called()
        self.gateway.client.voice_cloning.convert.assert_not_called()

    def test_cloned_voice_uses_inline_reference_without_saved_voice(self):
        self.gateway.narrate("Hello", "hi-IN", wav_bytes(10))
        kwargs = self.gateway.client.voice_cloning.convert.call_args.kwargs
        self.assertIn("ref_audio", kwargs)
        self.assertNotIn("voice_id", kwargs)
        self.assertFalse(kwargs["enable_qc"])
        self.assertEqual(kwargs["request_options"]["max_retries"], 0)
        self.gateway.client.text_to_speech.convert.assert_not_called()

    def test_recap_uses_selected_entries_and_no_reasoning(self):
        self.gateway.client.chat.completions.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=" My memory. "))])
        entries = [make_entry(date(2026, 10, 3), "Walk", "I walked home.")]
        self.assertEqual(self.gateway.summarize(entries, "October 2026", "English"), "My memory.")
        kwargs = self.gateway.client.chat.completions.call_args.kwargs
        self.assertEqual(kwargs["model"], "sarvam-105b")
        self.assertIsNone(kwargs["reasoning_effort"])
        self.assertEqual(kwargs["request_options"]["max_retries"], 0)
        self.assertIn("I walked home.", kwargs["messages"][1]["content"])

    def test_missing_key_and_empty_recap_source(self):
        with self.assertRaises(ValueError):
            SarvamGateway("")
        with self.assertRaises(ValueError):
            self.gateway.summarize([], "2026", "English")
        self.gateway.client.chat.completions.assert_not_called()

    def test_error_messages_do_not_echo_provider_secrets(self):
        for status in (401, 402, 403, 422, 429, 500):
            exc = RuntimeError("private-provider-response")
            exc.status_code = status
            self.assertNotIn("private-provider-response", friendly_error(exc))
        exc.status_code = 403
        self.assertIn("Sarvam narrator", friendly_error(exc, cloning=True))


class SdkContractTests(unittest.TestCase):
    def test_real_sdk_serializes_both_voice_paths_and_recap(self):
        import httpx
        from sarvamai import SarvamAI

        encoded = base64.b64encode(wav_bytes()).decode()
        requests = []

        def handle(request):
            requests.append(request)
            if request.url.path == "/voices/clone":
                return httpx.Response(200, json={"audio_b64": encoded, "audio": encoded, "request_id": "offline"})
            if request.url.path == "/text-to-speech":
                return httpx.Response(200, json={"audios": [encoded], "request_id": "offline"})
            return httpx.Response(200, json={
                "id": "offline", "created": 0, "model": "sarvam-105b", "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "I walked home."}}],
            })

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            gateway = SarvamGateway.__new__(SarvamGateway)
            gateway.client = SarvamAI(api_subscription_key="offline-not-a-real-key", httpx_client=client)
            gateway.narrate("Hello", "en-IN")
            gateway.narrate("Hello", "hi-IN", wav_bytes(10))
            result = gateway.summarize([make_entry(date(2026, 10, 1), "Walk", "I walked home.")], "October 2026", "English")
        self.assertEqual(result, "I walked home.")
        self.assertEqual([request.url.path for request in requests], ["/text-to-speech", "/voices/clone", "/v1/chat/completions"])
        self.assertIn(b'reference.wav', requests[1].content)
        self.assertIsNone(json.loads(requests[2].content)["reasoning_effort"])

    def test_real_sdk_does_not_retry_service_errors(self):
        import httpx
        from sarvamai import SarvamAI

        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(503, json={"message": "temporarily unavailable"})

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            gateway = SarvamGateway.__new__(SarvamGateway)
            gateway.client = SarvamAI(api_subscription_key="offline-not-a-real-key", httpx_client=client)
            with self.assertRaises(Exception):
                gateway.narrate("Hello", "en-IN")
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
