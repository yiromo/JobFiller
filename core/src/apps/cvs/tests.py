import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from pypdf import PdfReader, PdfWriter

from apps.cvs.container import CvsContainer
from apps.cvs.models import Cv
from apps.cvs.services.cv_service import _pdf_filename, _role


def blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with tempfile.TemporaryFile() as buffer:
        writer.write(buffer)
        buffer.seek(0)
        return buffer.read()


class GeneratedCvNameTests(TestCase):
    def test_the_name_is_cv_plus_the_headline_role(self):
        self.assertEqual(
            _pdf_filename(f"CV {_role('Senior Full-Stack Developer (Node.js/React/Next.js)')}"),
            "CV_Senior_Full_Stack_Developer.pdf",
        )
        self.assertEqual(_pdf_filename(f"CV {_role('')}"), "CV.pdf")

    def test_a_generated_cv_keeps_a_clean_name_and_carries_its_id(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            source = Cv.objects.create(
                file=ContentFile(b"x", name="base.txt"), original_filename="base.txt"
            )
            data = {"title": "AI Engineer (LLM)", "added_skills": [], "warnings": []}
            with (
                patch("agent.cv_writer.rewrite", return_value=data),
                patch("agent.cv_writer.render_pdf", return_value=(blank_pdf(), [])),
            ):
                service = CvsContainer.cv_service()
                first, _, _ = service.generate_from(source.id, "")
                second, _, _ = service.generate_from(source.id, "")
            self.assertEqual(Path(first.file_path).name, "CV_AI_Engineer.pdf")
            self.assertEqual(Path(second.file_path).name, "CV_AI_Engineer.pdf")
            self.assertNotEqual(first.file_path, second.file_path)
            self.assertEqual(PdfReader(first.file_path).metadata["/CvId"], str(first.id))
            folder = Path(first.file_path).parent
            service.delete(first.id)
            self.assertFalse(folder.exists())
