"""The baseline Marunthu-Thozhan must beat: ONE agent, ONE prompt, same model, same guidance pasted in.

No tools, no graph, no critic, no red-flag hook, no code-owned database lookups.
"""
from __future__ import annotations

import time

from strands import Agent

from . import tools
from .app import _model
from .plan import PrescriptionAnswer

PROMPT = """You are a prescription assistant for clinic outpatients in Madurai, Tamil Nadu.
Given the patient's prescription slip or query, decode their medicines, schedule, timing, and estimate savings.
Answer in the patient's language ({lang_name}).
Never invent numbers. If the patient has emergency signs or asks about dose changes, tell them what to do.

Guidance to cite:
{guidance}
"""


def run(case: dict) -> dict:
    t0 = time.time()
    guidance_lines = "\n".join(f"{g['id']}: {g['text']}" for g in tools.guidance()["items"])
    user_text = case.get("text", "")
    lang = case.get("lang") or tools.language_of(user_text)
    lang_name = "Tamil (Tamil script)" if lang == "ta" else "English"

    agent = Agent(
        model=_model(),
        system_prompt=PROMPT.format(lang_name=lang_name, guidance=guidance_lines),
        structured_output_model=PrescriptionAnswer,
        callback_handler=None,
    )

    msg = f"Patient prescription slip / question ({lang}):\n{user_text}"
    try:
        res = agent(msg)
        plan = getattr(res, "structured_output", None)
        if plan is None:
            ans_text = getattr(res, "text", "") or "General prescription advice."
            plan_dict = {
                "language": lang,
                "answer": ans_text,
                "steps": [],
                "nearest_kendra": "PMBJP Centre, Madurai",
                "savings": "₹0.00",
                "escalation": "Consult doctor or pharmacist",
                "citations": ["G-DOSE-CODE"]
            }
        else:
            plan_dict = plan.model_dump()
    except Exception as e:
        plan_dict = {
            "language": lang,
            "answer": f"Baseline error: {e}",
            "steps": [],
            "nearest_kendra": "PMBJP Centre, Madurai",
            "savings": "₹0.00",
            "escalation": "Consult doctor or pharmacist",
            "citations": []
        }

    return {
        "plan": plan_dict,
        "meta": {"path": "baseline", "latency_ms": int((time.time() - t0) * 1000)}
    }
