from __future__ import annotations

import io
import zipfile

import fitz

from src.integrations.docx_export import (
    build_task_docx,
    build_task_docx_filename,
    build_task_pdf,
    build_task_pdf_filename,
)


SAMPLE_GRANT_TASK = {
    "task_id": "grant/../../unsafe-123",
    "council": "grant",
    "task_description": "Draft the impact and methodology sections.",
    "confidence_score": 91,
    "final_output": (
        "# Methodology\n"
        "The programme will deliver **three verified work packages**.\n\n"
        "- Stakeholder discovery\n"
        "- Pilot delivery\n"
        "- Independent evaluation\n"
    ),
}


def test_docx_export_is_valid_and_filename_is_safe():
    payload = build_task_docx(SAMPLE_GRANT_TASK)

    assert payload.startswith(b"PK")
    assert zipfile.is_zipfile(io.BytesIO(payload))
    assert build_task_docx_filename(SAMPLE_GRANT_TASK) == "grant-grantunsafe-123.docx"


def test_pdf_export_is_valid_searchable_and_filename_is_safe():
    payload = build_task_pdf(SAMPLE_GRANT_TASK)
    document = fitz.open(stream=payload, filetype="pdf")
    extracted = "\n".join(page.get_text() for page in document)

    assert payload.startswith(b"%PDF")
    assert "Methodology" in extracted
    assert "Stakeholder discovery" in extracted
    assert build_task_pdf_filename(SAMPLE_GRANT_TASK) == "grant-grantunsafe-123.pdf"
