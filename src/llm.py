"""LLM layer: note summarization + warm bilingual messaging only.

The LLM never decides *who* is at risk — `src/risk.py` already did that
deterministically before this module runs. Its only job is turning a
decided risk level into human-ready text: a short facilitator brief and a
warm Arabic parent/student message. That keeps the one thing that must be
consistent and auditable (risk ranking) off a nondeterministic API, while
still using the LLM for what it's actually good at (natural language).

Every call — real or fallback — is appended to `outputs/llm_messages.jsonl`
so a reviewer can see exactly what was sent/received without re-running the
pipeline. API keys are never written to that log.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ValidationError

from src.config import Settings

SYSTEM_PROMPT = (
    "You are an expert Arabic-speaking EdTech intervention assistant. You help "
    "classroom facilitators support students before an upcoming exam. Be "
    "specific, warm, culturally appropriate for Saudi Arabia, non-judgmental, "
    "and concise. Do not invent facts. Use only the provided student data. "
    "Return valid JSON only."
)

def _isnan(value) -> bool:
    try:
        return bool(value != value)  # NaN is the only value that isn't equal to itself
    except TypeError:
        return False


RESPONSE_KEYS = (
    "note_summary",
    "facilitator_brief",
    "parent_message_ar",
    "student_message_ar",
    "risk_explanation",
    "next_step",
)


class LLMResponse(BaseModel):
    note_summary: str
    facilitator_brief: str
    parent_message_ar: str
    student_message_ar: str
    risk_explanation: str
    next_step: str


def build_student_context(row: dict) -> dict:
    """Minimal, privacy-conscious payload — no phone numbers, note IDs, or
    other fields the LLM doesn't need to write a brief and two messages.

    pandas leaves missing numeric/text fields as float NaN, which
    `json.dumps` would otherwise serialize as the bare token `NaN` — not
    valid JSON. We normalize those to `None` so both the OpenAI request
    body and `llm_messages.jsonl` are strict, parseable JSON.
    """
    raw = {
        "student_name": row.get("student_name"),
        "risk_level": row.get("risk_level"),
        "risk_score": row.get("risk_score"),
        "quiz1_score": row.get("quiz1_score"),
        "target_score": row.get("target_score"),
        "recent_attendance_min": row.get("recent_attendance_min"),
        "recent_practice_questions": row.get("recent_practice_questions"),
        "reason_codes": row.get("reason_codes"),
        "last_note_text": row.get("last_note_text"),
        "recommended_action": row.get("recommended_action"),
    }
    return {k: (None if _isnan(v) else v) for k, v in raw.items()}


def _fallback_response(context: dict) -> LLMResponse:
    """Deterministic templates used whenever the LLM is disabled, unavailable,
    or returns invalid JSON twice in a row. These are intentionally plain —
    good enough to hand a facilitator today, not a substitute for a human
    conversation with the family."""
    name = context.get("student_name") or "الطالب"
    risk_level = context.get("risk_level") or "Medium"
    quiz = context.get("quiz1_score")
    quiz = None if quiz is None or _isnan(quiz) else quiz
    target = context.get("target_score")
    target = None if target is None or _isnan(target) else target
    last_note_text = context.get("last_note_text")
    has_note = isinstance(last_note_text, str) and last_note_text.strip() != ""

    note_summary = (
        f"Last facilitator note on file: {last_note_text[:160]}"
        if has_note
        else "No facilitator notes on file since Quiz 1."
    )

    if quiz is not None and target is not None:
        gap_txt = f"scored {quiz:g} against a target of {target:g}"
    else:
        gap_txt = "has no recorded Quiz 1 score"

    action = context.get("recommended_action") or "follow_up"
    action_brief = {
        "parent_call_plus_tutoring": "call the parent today and book a 1:1 tutoring slot before Quiz 2",
        "parent_call_or_voice_note": "call the parent (or send a voice note) within 24 hours to identify the barrier",
        "student_checkin_plus_practice_plan": "send a quick WhatsApp check-in and share a short practice plan",
        "automated_motivation_message": "no facilitator action needed — an automated encouragement message is queued",
    }.get(action, "follow up with the student")

    facilitator_brief = f"{name} is {risk_level} risk ({gap_txt}). Next step: {action_brief}."

    if risk_level in ("Critical", "High"):
        parent_message_ar = (
            f"السلام عليكم، معك فريق متابعة {name} من أكاديمية بون. لاحظنا ان {name} "
            f"يحتاج بعض الدعم الإضافي قبل الاختبار القادم، ونود نتواصل معكم لنشوف "
            f"كيف نقدر نساعده سوا قبل الاختبار."
        )
    elif risk_level == "Medium":
        parent_message_ar = (
            f"السلام عليكم، تحية طيبة. نطمئن عليكم ونود نشارككم اننا راح نتابع مع "
            f"{name} عن قرب هالاسبوع قبل الاختبار القادم بخطة تدريب بسيطة يومية."
        )
    else:
        parent_message_ar = (
            f"السلام عليكم، نود اطمئنانكم ان {name} مستمر بشكل جيد. راح نرسل له "
            f"رسائل تحفيزية بسيطة قبل الاختبار القادم لدعمه بالاستمرار."
        )

    if risk_level in ("Critical", "High"):
        student_message_ar = (
            f"مرحباً {name}! لاحظنا انك تحتاج بعض الدعم الإضافي قبل الاختبار القادم. "
            f"احنا معاك خطوة بخطوة، خلك مستمر بالحضور والتدريب اليومي وراح نشوف تحسن ان شاء الله."
        )
    else:
        student_message_ar = (
            f"يا بطل {name}! استمر على نفس المستوى، كل سؤال تحله يقربك اكثر من هدفك. "
            f"احنا فخورين فيك، كمل بنفس الحماس للاختبار القادم!"
        )

    risk_explanation = (
        f"Risk level {risk_level} driven by: {', '.join(context.get('reason_codes') or []) or 'insufficient recent engagement data'}."
    )
    next_step = action_brief.capitalize()

    return LLMResponse(
        note_summary=note_summary,
        facilitator_brief=facilitator_brief,
        parent_message_ar=parent_message_ar,
        student_message_ar=student_message_ar,
        risk_explanation=risk_explanation,
        next_step=next_step,
    )


def _parse_response(raw_text: str) -> LLMResponse:
    data = json.loads(raw_text)
    return LLMResponse(**{k: data.get(k) for k in RESPONSE_KEYS})


def _call_openai_once(client, model: str, context: dict) -> str:
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Student data (JSON):\n"
                    f"{json.dumps(context, ensure_ascii=False)}\n\n"
                    "Return ONLY a JSON object with exactly these keys: "
                    f"{list(RESPONSE_KEYS)}."
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return completion.choices[0].message.content


def _log(log_path: Path, entry: dict) -> None:
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_llm_response(
    context: dict, settings: Settings, log_path: Path, client=None
) -> LLMResponse:
    """Get facilitator/parent/student text for one student.

    Falls back to deterministic templates when the LLM is disabled, no key
    is configured, or the model returns invalid JSON twice in a row (one
    retry, per the case brief). Every attempt is logged to `log_path`.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    if not settings.llm_available:
        response = _fallback_response(context)
        _log(
            log_path,
            {
                "timestamp": timestamp,
                "student_name": context.get("student_name"),
                "fallback_used": True,
                "fallback_reason": "llm_disabled_or_no_api_key",
                "request": context,
                "response": response.model_dump(),
            },
        )
        return response

    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)

    last_error: str | None = None
    for attempt in (1, 2):
        try:
            raw_text = _call_openai_once(client, settings.openai_model, context)
            response = _parse_response(raw_text)
            _log(
                log_path,
                {
                    "timestamp": timestamp,
                    "student_name": context.get("student_name"),
                    "fallback_used": False,
                    "attempt": attempt,
                    "request": context,
                    "response": response.model_dump(),
                },
            )
            return response
        except (json.JSONDecodeError, ValidationError, Exception) as exc:  # noqa: BLE001
            # Broad catch is deliberate: network errors, rate limits, and
            # malformed JSON must all fall through to the same safe fallback
            # rather than crashing the whole roster generation.
            last_error = f"{type(exc).__name__}: {exc}"

    response = _fallback_response(context)
    _log(
        log_path,
        {
            "timestamp": timestamp,
            "student_name": context.get("student_name"),
            "fallback_used": True,
            "fallback_reason": f"llm_failed_after_retry: {last_error}",
            "request": context,
            "response": response.model_dump(),
        },
    )
    return response
