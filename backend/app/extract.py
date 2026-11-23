import json, re
from pathlib import Path
import fitz
from google import genai
from google.genai import types
from .config import settings
from .schemas import PolicyFacts

PROMPT = '''You extract facts from Indian motor insurance policy PDFs for a commission-rating workflow.
Return ONLY JSON matching this schema:
{
 "insurer": string|null, "previous_insurer": string|null, "business_type": string|null,
 "make_model": string|null, "fuel": string|null, "rto": string|null,
 "engine_cc": integer|null, "manufacture_year": integer|null, "policy_type": string|null,
 "ncb_percent": number|null, "od_premium": number|null, "tp_premium": number|null,
 "other_premium": number|null, "source_pages": {"field": page_number},
 "missing_or_uncertain": [string]
}
Rules: never guess; distinguish manufacture year from registration year; premium values must be net component premiums when clearly labelled; policy type should distinguish comprehensive/package, standalone TP and standalone OD. Use page numbers starting at 1. If insurer is both current and previous insurer, business_type is renewal; otherwise state only if evidence supports it. Include uncertain or missing rating facts.'''

def pdf_text(path: str) -> tuple[str, int]:
    doc=fitz.open(path)
    chunks=[]
    for i,page in enumerate(doc):
        txt=page.get_text("text")
        if txt.strip(): chunks.append(f"\n[PAGE {i+1}]\n{txt}")
    return "\n".join(chunks), len(doc)

def extract_policy(path: str) -> tuple[PolicyFacts, dict]:
    text, pages=pdf_text(path)
    if not text.strip():
        raise ValueError("No selectable text found in this PDF. OCR is required for this document.")
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    client=genai.Client(api_key=settings.gemini_api_key)
    response=client.models.generate_content(
        model=settings.gemini_model,
        contents=[PROMPT, text[:180000]],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
    )
    raw=json.loads(response.text)
    facts=PolicyFacts.model_validate(raw)
    # Business type is a deterministic derivation when both names are explicit.
    if facts.insurer and facts.previous_insurer:
        norm=lambda x: re.sub(r'[^a-z0-9]','',x.lower())
        if norm(facts.insurer)==norm(facts.previous_insurer):
            facts.business_type="renewal"
    return facts, {"page_count":pages,"model":settings.gemini_model,"text_chars":len(text)}
