from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from agent import cover_letter
from agent.llm_mapper import _call_llm
from apps.applications.api.v1.serializers import ScanRequestSerializer
from apps.applications.services.application_service import ApplicationService, CoverLetterOffError


class VisionScanTests(SimpleTestCase):
    def test_scan_accepts_jpeg_data_url(self):
        serializer = ScanRequestSerializer(
            data={
                "url": "https://jobs.example.com/123",
                "form_snapshot": [],
                "screenshot": "data:image/jpeg;base64,aGVsbG8=",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    @override_settings(MIMO_API_KEY="test", MIMO_VISION_MODEL="mimo-v2.6-flash")
    @patch("agent.llm_mapper.OpenAI")
    def test_vision_field_mapping_sends_image_and_text(self, openai_class):
        openai_class.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"fields": []}'))]
        )
        _call_llm(
            [{"ref": "1", "label": "Your experience", "tag": "textarea"}],
            "Python developer",
            "Backend developer",
            "data:image/jpeg;base64,aGVsbG8=",
        )
        call = openai_class.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], "mimo-v2.6-flash")
        content = call["messages"][1]["content"]
        self.assertEqual(content[1]["image_url"]["url"], "data:image/jpeg;base64,aGVsbG8=")
        self.assertIn("Python developer", content[0]["text"])


class CoverLetterSizeTests(SimpleTestCase):
    def test_prompt_carries_the_chosen_length_and_character_cap(self):
        prompt = cover_letter.system_prompt("very_short", 1000)
        self.assertIn(cover_letter.LENGTHS["very_short"], prompt)
        self.assertIn("under 1000 characters", prompt)
        self.assertNotIn("{length}", prompt)
        self.assertIn(cover_letter.LENGTHS["medium"], cover_letter.system_prompt("unknown"))

    def test_scan_defaults_to_medium_and_rejects_unknown_sizes(self):
        base = {"url": "https://jobs.example.com/1", "form_snapshot": []}
        serializer = ScanRequestSerializer(data=base)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["cover_letter_size"], "medium")
        self.assertFalse(
            ScanRequestSerializer(data={**base, "cover_letter_size": "huge"}).is_valid()
        )

    @override_settings(MIMO_API_KEY="test")
    @patch("agent.cover_letter.generate")
    def test_off_skips_letter_fields_without_calling_the_model(self, generate):
        plan = [{"ref": "1", "value": "", "action": "cover_letter_type", "confidence": 0.0}]
        resolved = ApplicationService._resolve_cover_letter(plan, MagicMock(), "", "", "off")
        self.assertEqual(resolved[0]["action"], "skip")
        generate.assert_not_called()

    @override_settings(MIMO_API_KEY="test")
    @patch("agent.cover_letter.generate", return_value="Dear Hiring Team")
    def test_size_reaches_the_generator(self, generate):
        plan = [{"ref": "1", "value": "", "action": "cover_letter_type", "confidence": 0.0}]
        resolved = ApplicationService._resolve_cover_letter(plan, MagicMock(), "", "", "short")
        self.assertEqual(resolved[0]["value"], "Dear Hiring Team")
        self.assertEqual(generate.call_args.kwargs["size"], "short")

    def test_regenerating_with_off_is_refused(self):
        service = ApplicationService(MagicMock(), MagicMock())
        with self.assertRaises(CoverLetterOffError):
            service.regenerate_cover_letter(1, "", "", "off")
