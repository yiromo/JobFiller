from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from agent.llm_mapper import _call_llm
from apps.applications.api.v1.serializers import ScanRequestSerializer


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
