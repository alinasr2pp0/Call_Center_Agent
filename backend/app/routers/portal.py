"""Customer portal API: personas, problem messages (text + voice), ticket status, text-to-speech."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_customer
from app.models import Customer, Persona, Ticket
from app.schemas import ProblemMessage, TtsRequest
from app.agent import speech, tickets
from app.agent.errors import ExternalServiceError

router = APIRouter()

MAX_AUDIO_BYTES = 10 * 1024 * 1024


def persona_public(p: Persona) -> dict:
    return {"id": p.id, "name": p.name, "role": p.role, "description": p.description, "is_default": p.is_default}


@router.get("/personas", tags=["Portal"])
def list_personas(db: Session = Depends(get_db)):
    rows = db.query(Persona).order_by(Persona.sort_order, Persona.name).all()
    return [persona_public(p) for p in rows]


@router.post("/tickets/message", tags=["Portal"])
def post_message(body: ProblemMessage, customer: Customer = Depends(get_current_customer),
                 db: Session = Depends(get_db)):
    return tickets.handle_customer_message(db, customer, body.problem_text, body.persona_id)


@router.post("/tickets/message/voice", tags=["Portal"])
def post_voice_message(
    audio: UploadFile = File(...),
    persona_id: Optional[str] = Form(None),
    want_audio_reply: bool = Form(False),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    if not settings.speech_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Voice messages need GROQ_API_KEY to be configured on the server")
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Empty audio recording")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Audio recording is too large (max 10 MB)")
    try:
        text = speech.transcribe(data, audio.filename or "voice-message.webm", audio.content_type)
    except ExternalServiceError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Speech recognition failed")
        
    # Check for known Whisper hallucinations or too short audio
    hallucination_triggers = ["ترجمة نانسي قنقر", "amara.org", "نانسي قنقر"]
    is_hallucination = any(trigger in text.lower() for trigger in hallucination_triggers)
    
    if len(text) < 2 or is_hallucination:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "أعد المحاولة لم أستمع جيدا")
        
    result = tickets.handle_customer_message(db, customer, text[:4000], persona_id)
    result["transcribed_text"] = text
    result["answer_audio_base64"] = None
    if want_audio_reply:
        try:
            result["answer_audio_base64"] = speech.synthesize(result["answer"])
        except ExternalServiceError:
            pass  # the text answer is still returned; the UI offers a play button
    return result


@router.get("/tickets/{ticket_id}/status", tags=["Portal"])
def ticket_status(ticket_id: str, customer: Customer = Depends(get_current_customer),
                  db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.customer_id == customer.id).first()
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    latest = ticket.calls[-1] if ticket.calls else None
    return {
        "ticket_id": ticket.id,
        "status": ticket.status,
        "latest_call": None if latest is None else {
            "status": latest.status, "outcome": latest.outcome, "duration_seconds": latest.duration_seconds},
    }


@router.post("/speech/tts", tags=["Portal"])
def text_to_speech(body: TtsRequest, customer: Customer = Depends(get_current_customer)):
    if not settings.speech_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Text-to-speech needs GROQ_API_KEY to be configured on the server")
    try:
        return {"audio_base64": speech.synthesize(body.text)}
    except ExternalServiceError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Speech synthesis failed")

