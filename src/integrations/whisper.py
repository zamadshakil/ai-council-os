"""
whisper.py — Voice-to-Text Integration

Converts audio files (from Plaud.ai recordings, dictation, etc.)
into text using OpenAI's Whisper API.

Cost: $0.006 per minute of audio.
A 1-hour sales call = $0.36 to transcribe.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def get_openai_client() -> OpenAI:
    """Get configured OpenAI client."""
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def transcribe_audio(
    file_path: str,
    language: str = "en",
    response_format: str = "text",
) -> dict:
    """
    Transcribe an audio file using Whisper API.

    Args:
        file_path: Path to audio file (mp3, mp4, wav, m4a, webm)
        language: ISO language code (default: English)
        response_format: "text", "json", "verbose_json", "srt", "vtt"

    Returns:
        dict with 'text' (transcript) and 'duration_minutes' (for cost tracking)
    """
    client = get_openai_client()
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    with open(path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=language,
            response_format=response_format,
        )

    # Estimate duration from file size (rough: ~1MB per minute for mp3)
    file_size_mb = path.stat().st_size / (1024 * 1024)
    est_duration_min = max(file_size_mb, 0.5)  # At least 0.5 min

    return {
        "text": transcript if isinstance(transcript, str) else transcript.text,
        "duration_minutes": round(est_duration_min, 2),
        "estimated_cost_usd": round(est_duration_min * 0.006, 4),
        "source_file": str(path.name),
    }


async def transcribe_and_store(
    file_path: str,
    collection_name: str = "transcripts",
    metadata: dict | None = None,
) -> dict:
    """
    Transcribe audio AND store it in the knowledge base.

    This is the main entry point for ingesting voice data.
    The transcript becomes searchable by all councils.
    """
    from src.core.memory import store_document

    # Transcribe
    result = await transcribe_audio(file_path)

    # Store in knowledge base
    meta = metadata or {}
    meta.update({
        "source": "whisper_transcription",
        "source_file": result["source_file"],
        "duration_minutes": result["duration_minutes"],
        "cost_usd": result["estimated_cost_usd"],
    })

    doc_id = await store_document(
        collection_name=collection_name,
        document=result["text"],
        metadata=meta,
    )

    result["doc_id"] = doc_id
    result["collection"] = collection_name

    return result
