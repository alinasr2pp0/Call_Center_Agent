"""
The support Agent: finds a solution through the RAG package, optionally rewrites it in the chosen
persona's tone with the LLM (OpenRouter), optionally falls back to web search, and decides whether the
problem is answered, needs clarification, or must be escalated to a human.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.agent import llm, prompts
from app.agent.errors import ExternalServiceError
from app.config import settings
from app.core.metrics import metrics
from app.models import Persona
from app.rag import knowledge
from app.rag.bm25 import meaningful_term_count

logger = logging.getLogger("call_center")

NO_SOLUTION = prompts.NO_SOLUTION
reset_cache = knowledge.reset_cache  # the admin "reset" button clears the knowledge cache through the Agent


@dataclass
class AgentResult:
    answer: str
    source: str  # kb | web | clarify | none
    confidence: float
    category: Optional[str] = None
    resolved: bool = False
    escalate: bool = False
    escalation_reason: Optional[str] = None
    used_web: bool = False
    article_ids: List[int] = field(default_factory=list)


def answer_problem(db: Session, problem_text: str, persona: Optional[Persona]) -> AgentResult:
    # A single word ("hello", "internet") is not a problem description: ask for details first.
    if meaningful_term_count(problem_text) < 2:
        return AgentResult(prompts.clarify_text(problem_text), "clarify", 0.0)

    found, articles = knowledge.search(db, problem_text)
    best, top = found.best, found.top
    best_cov = (best or top).confidence if (best or top) else 0.0
    ref = best or top
    category = articles[ref.doc_id]["ticket_type"] if ref and articles[ref.doc_id]["ticket_type"] else None

    # 1) knowledge base (keyword and/or semantic match)
    if best:
        ids = [best.doc_id] + [c.doc_id for c in found.candidates
                               if c.doc_id != best.doc_id and c.accepted][:2]
        answer: Optional[str] = None
        if settings.llm_configured:
            try:
                answer = llm.chat([
                    {"role": "system", "content": prompts.system_prompt(
                        persona, prompts.kb_context(articles, ids), web=False)},
                    {"role": "user", "content": problem_text},
                ])
            except ExternalServiceError:
                answer = None  # fall back to the stored resolution below
            if answer and NO_SOLUTION in answer:
                return AgentResult(prompts.escalate_text(problem_text), "kb", best_cov, category, escalate=True,
                                   escalation_reason="knowledge base does not cover this problem",
                                   article_ids=ids)
        if not answer:
            answer = articles[best.doc_id]["resolution"]
        if persona is not None and persona.max_words:
            answer = prompts.trim_to_words(answer, max(persona.max_words, 30))
        return AgentResult(answer, "kb", best_cov, category, resolved=True, article_ids=ids)

    # 2) web search fallback (needs both Tavily and an LLM to synthesise safely)
    if settings.TAVILY_API_KEY and settings.llm_configured:
        try:
            with metrics.timed("strategy.web_search"):
                results = llm.web_search(problem_text)
                if results:
                    answer = llm.chat([
                        {"role": "system", "content": prompts.system_prompt(
                            persona, prompts.web_context(results), web=True)},
                        {"role": "user", "content": problem_text},
                    ])
                else:
                    answer = NO_SOLUTION
            if answer and NO_SOLUTION not in answer:
                return AgentResult(answer, "web", best_cov, category, resolved=True, used_web=True)
        except ExternalServiceError:
            logger.info("web fallback unavailable; escalating")

    # 3) nothing reliable found -> hand over to a human
    return AgentResult(prompts.escalate_text(problem_text), "none", best_cov, category, escalate=True,
                       escalation_reason="no confident answer in the knowledge base")
