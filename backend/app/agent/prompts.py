"""Everything the Agent says: fixed replies and the LLM system prompt (edit wording here)."""
from __future__ import annotations

from typing import List, Optional

from app.models import Persona
from app.rag.text import has_arabic

NO_SOLUTION = "[[NO_SOLUTION]]"

CLARIFY_AR = "ممكن توضّح مشكلتك أكتر؟ اكتب تفاصيل زي نوع الخدمة أو المنتج وإيه اللي بيحصل بالظبط."
CLARIFY_EN = "Could you tell me a bit more? Please describe the product or service and what exactly is happening."
ESCALATE_AR = "لم أجد حلًا مؤكدًا لمشكلتك، فسجّلتها لفريق الدعم وسيتواصلون معك."
ESCALATE_EN = "I couldn't find a confirmed solution, so I've passed your problem to our support team. They will contact you."


def clarify_text(problem_text: str) -> str:
    return CLARIFY_AR if has_arabic(problem_text) else CLARIFY_EN


def escalate_text(problem_text: str) -> str:
    return ESCALATE_AR if has_arabic(problem_text) else ESCALATE_EN


def persona_block(persona: Optional[Persona]) -> str:
    if persona is None:
        return "أسلوب ودود ومحترف وواضح."
    parts = [persona.tone_instructions_ar.strip() or "أسلوب ودود ومحترف وواضح."]
    if persona.max_words:
        parts.append(f"لا تتجاوز {persona.max_words} كلمة تقريبًا.")
    return " ".join(parts)


def system_prompt(persona: Optional[Persona], context: str, web: bool) -> str:
    source_rule = (
        "اعتمد فقط على نتائج البحث في الإنترنت التالية." if web
        else "اعتمد فقط على مقالات قاعدة المعرفة التالية."
    )
    return (
        "أنت موظف خدمة عملاء في مركز اتصال. " + source_rule + " لا تخترع معلومات أو أرقامًا غير موجودة في المصدر.\n"
        f"إذا لم يحتوِ المصدر على حل لمشكلة العميل، أجب بالضبط بهذه العبارة وحدها: {NO_SOLUTION}\n"
        "أجب بنفس لغة العميل (العربية افتراضيًا) بخطوات واضحة ومختصرة، ولا تذكر أنك تعتمد على مصدر أو قاعدة بيانات.\n"
        f"الأسلوب المطلوب: {persona_block(persona)}\n\n"
        f"المصدر:\n{context}"
    )


def kb_context(articles: dict, ids: List[int]) -> str:
    blocks = []
    for n, article_id in enumerate(ids, start=1):
        a = articles[article_id]
        problem = f"المشكلة: {a['description']}\n" if a["description"] else ""  # document chunks have none
        blocks.append(
            f"[{n}] المنتج: {a['product']} | النوع: {a['ticket_type']} | الموضوع: {a['subject']}\n"
            f"{problem}الحل: {a['resolution']}"
        )
    return "\n\n".join(blocks)


def web_context(results: List[dict]) -> str:
    return "\n\n".join(f"[{i}] {r['title']} ({r['url']})\n{r['content']}" for i, r in enumerate(results, start=1))


def trim_to_words(text: str, max_words: int) -> str:
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words]) + "…"
