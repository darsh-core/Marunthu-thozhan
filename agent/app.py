"""Marunthu-Thozhan: Tamil/English prescription decoder, Jan Aushadhi generic alternative finder, and safe medication companion.

Usage:
    python -m agent.app "Tab Metformin 500mg 1-0-1 AF, Tab Telma 40mg 1-0-0 BF"
    python -m agent.app "ரொம்ப காய்ச்சலா இருக்கு, இரண்டு டோலோ 650 மாத்திரை ஒண்ணா போட்டுக்கலாமா?"
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from strands import Agent
from strands.models import BedrockModel
from strands.multiagent import GraphBuilder

from . import safety, tools
from .plan import Critique, PrescriptionAnswer

MODEL_ID = os.environ.get("SHIP_MODEL", "us.amazon.nova-2-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
MAX_PLANNER_PASSES = 2
logging.getLogger("strands").setLevel(logging.CRITICAL)  # a cancelled node is an expected safety event

PLANNER = """You are Marunthu-Thozhan (மருந்து தோழன்), an expert medication safety guide for outpatients in Madurai, Tamil Nadu.
Your job is to decode outpatient clinic chits into clear timing instructions, explain food cautions, and highlight Jan Aushadhi generic savings.

Rules:
1. Always write every text field in the patient's language ({lang}: en = English, ta = Tamil script). Use simple, respectful, conversational language.
2. Verified medicine details from database:
{facts}
3. Call lookup_guidance to find official clinical guideline IDs. Cite ONLY valid ids returned by lookup_guidance (e.g. G-FOOD-TIMING, G-JAN-AUSHADHI, G-DOSE-CODE, G-METFORMIN).
4. In 'escalation', ALWAYS advise consulting a doctor or pharmacist, and mention the 24x7 Tamil Nadu Health Helpline 104.
5. CRITICAL SAFETY: NEVER advise changing doses, taking extra pills, or stopping medicine. NEVER diagnose illnesses.
6. Return PrescriptionAnswer directly."""

CRITIC = """You are a medication safety auditor checking a patient prescription plan.
The allowed citation ids are: {ids}.
Reply ok=false with one line per problem ONLY if any of the following critical safety rules are violated:
- Any text field is not in the patient's language ({lang}: en = English, ta = Tamil script);
- Any citation in the plan is completely absent from the allowed citation ids list;
- The plan recommends altering doses, doubling doses, or taking unprescribed extra tablets;
- The escalation field does not mention consulting a doctor/pharmacist or the Tamil Nadu 104 helpline.
Otherwise, reply ok=true with an empty problems list. Do not invent problems if the plan is safe."""


def _model() -> BedrockModel:
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.1)


def _pre_parse_facts(user_text: str, lang: str) -> dict:
    """Deterministic pre-parsing of medicines and kendras from text."""
    meds_db = tools.medications_db()
    lower_text = user_text.lower()
    matched_items = []

    for m in meds_db:
        if m["key"] in lower_text or any(a in lower_text for a in m["aliases"]):
            savings = round(m["retail_brand_price_inr"] - m["jan_aushadhi_price_inr"], 2)
            gen_name = m["generic_name"]
            if lang == "ta" and m.get("aliases"):
                ta_alias = next((a for a in m["aliases"] if tools.has_tamil(a)), "")
                if ta_alias:
                    gen_name = f"{ta_alias} ({m['generic_name']})"
            matched_items.append({
                "medication": m["key"].capitalize(),
                "generic_name": gen_name,
                "timing_code": m["standard_timing"],
                "timing": m["timing_description_ta"] if lang == "ta" else m["timing_description_en"],
                "food_instruction": m["food_instructions_ta"] if lang == "ta" else m["food_instructions_en"],
                "retail_price_inr": m["retail_brand_price_inr"],
                "jan_aushadhi_price_inr": m["jan_aushadhi_price_inr"],
                "savings_inr": savings
            })

    kendra_info = tools.find_nearest_jan_aushadhi(user_text)["kendra"]
    kendra_desc = f"{kendra_info['name']}, {kendra_info['landmark']}, {kendra_info['address']} (Ph: {kendra_info['phone']}, Open: {kendra_info['timing']})"

    total_savings = sum(m["savings_inr"] for m in matched_items)
    savings_desc = (
        f"மாதாந்திர சேமிப்பு: சுமார் ₹{total_savings} ரூபாய் (ஜன அவுஷதி மலிவு விலை)"
        if lang == "ta" else
        f"Estimated Monthly Savings: ~₹{total_savings} via Jan Aushadhi generic equivalents"
    )

    return {
        "items": matched_items,
        "kendra": kendra_desc,
        "savings_desc": savings_desc,
        "total_savings": total_savings
    }


def _enforce(plan: PrescriptionAnswer, facts: dict, lang: str, critic_ok: bool) -> tuple[PrescriptionAnswer, list[str]]:
    """Enforce deterministic facts and safety fallbacks on the generated plan."""
    fixed = []
    plan.language = lang

    # Enforce Kendra address
    if not plan.nearest_kendra or "Madurai" not in plan.nearest_kendra:
        plan.nearest_kendra = facts["kendra"]
        fixed.append("nearest kendra address enforced")

    # Enforce savings
    if not plan.savings or "₹" not in plan.savings:
        plan.savings = facts["savings_desc"]
        fixed.append("savings enforced")

    # Enforce 104 Helpline in escalation
    if "104" not in plan.escalation:
        helpline_msg = (
            "உடனடி ஆலோசனைக்கு 24x7 தமிழ்நாடு மருத்துவ உதவி எண் 104 அழையுங்கள் அல்லது மருத்துவரை அணுகுங்கள்."
            if lang == "ta" else
            "For free medical assistance, contact the 24x7 Tamil Nadu Health Helpline at 104 or consult your doctor."
        )
        plan.escalation = f"{plan.escalation} {helpline_msg}".strip()
        fixed.append("104 helpline enforced")

    # Enforce valid citations
    valid_ids = tools.guidance_ids()
    plan.citations = [c for c in plan.citations if c in valid_ids]
    if not plan.citations:
        plan.citations = ["G-FOOD-TIMING", "G-JAN-AUSHADHI", "G-DOSE-CODE"]
        fixed.append("default valid citations enforced")

    return plan, fixed


def build_graph(lang: str, facts_str: str, gate: safety.RedFlagGate):
    planner = Agent(
        model=_model(),
        name="planner",
        system_prompt=PLANNER.format(lang=lang, facts=facts_str),
        tools=[tools.lookup_guidance],
        structured_output_model=PrescriptionAnswer,
        callback_handler=None,
    )
    critic = Agent(
        model=_model(),
        name="critic",
        system_prompt=CRITIC.format(lang=lang, ids=", ".join(sorted(tools.guidance_ids()))),
        structured_output_model=Critique,
        callback_handler=None,
    )

    seen = set()

    def should_retry(state):
        critic_res = state.results.get("critic")
        critique = getattr(critic_res.result, "structured_output", None) if critic_res else None
        passes = sum(1 for x in state.execution_order if x.node_id == "planner")
        if critique is not None and passes not in seen:
            seen.add(passes)
            status_text = "PASS" if critique.ok else "REVISE - " + "; ".join(critique.problems)[:200]
            print(f"[critic] pass {passes}: {status_text}", flush=True)
        return bool(critique is not None and not critique.ok and passes < MAX_PLANNER_PASSES)

    builder = GraphBuilder()
    builder.add_node(planner, "planner")
    builder.add_node(critic, "critic")
    builder.add_edge("planner", "critic")
    builder.add_edge("critic", "planner", condition=should_retry)
    builder.set_entry_point("planner")
    builder.set_max_node_executions(4)
    builder.reset_on_revisit(True)
    builder.set_hook_providers([gate])
    return builder.build()


def run(case: dict) -> dict:
    t0 = time.time()
    user_text = case.get("text", "")
    lang = case.get("lang") or tools.language_of(user_text)
    gate = safety.RedFlagGate()
    meta = {"path": "agent", "passes": 0, "lang": lang}

    # Deterministic fast safety check before graph invocation
    early_hits = safety.check_red_flags(user_text)
    if early_hits:
        gate.tripped = early_hits
        print(f"[safety] RED FLAG ({', '.join(early_hits)}) -> model not called, emergency referral sent", flush=True)
        plan_dict = safety.HANDOFF_CARD[lang].copy()
        plan_dict["language"] = lang
        meta = {"path": "handoff", "red_flags": early_hits, "latency_ms": int((time.time() - t0) * 1000)}
        print(f"[lang] language: {lang}", flush=True)
        print(f"[plan] {plan_dict['answer'][:150]}", flush=True)
        return {"plan": plan_dict, "meta": meta}

    facts = _pre_parse_facts(user_text, lang)
    facts_str = json.dumps(facts, ensure_ascii=False, indent=2)

    try:
        graph = build_graph(lang, facts_str, gate)
        invoc_state = {"user_text": user_text, "lang": lang}
        msg = f"Patient prescription slip / question ({lang}):\n{user_text}"
        res = graph(msg, invocation_state=invoc_state)
    except Exception as e:
        if gate.tripped:
            print(f"[safety] RED FLAG ({', '.join(gate.tripped)}) -> node cancelled, emergency referral sent", flush=True)
            plan_dict = safety.HANDOFF_CARD[lang].copy()
            plan_dict["language"] = lang
            meta = {"path": "handoff", "red_flags": gate.tripped, "latency_ms": int((time.time() - t0) * 1000)}
            print(f"[lang] language: {lang}", flush=True)
            print(f"[plan] {plan_dict['answer'][:150]}", flush=True)
            return {"plan": plan_dict, "meta": meta}
        print(f"[safety] Recovering from error ({e})", flush=True)
        if facts.get("items"):
            item = facts["items"][0]
            ans_text = (
                f"மருந்து: {item['generic_name']} ({item['medication']}). நேரம்: {item['timing']}. {item['food_instruction']}"
                if lang == "ta" else
                f"Medication: {item['generic_name']} ({item['medication']}). Timing: {item['timing']}. {item['food_instruction']}"
            )
            fallback_plan = PrescriptionAnswer(
                language=lang,
                answer=ans_text,
                steps=[item["timing"], item["food_instruction"]],
                nearest_kendra=facts["kendra"],
                savings=facts["savings_desc"],
                escalation="உடனடி ஆலோசனைக்கு 24x7 தமிழ்நாடு மருத்துவ உதவி எண் 104 அழையுங்கள் அல்லது மருத்துவரை அணுகுங்கள்." if lang == "ta" else "For medical assistance, contact the 24x7 Tamil Nadu Health Helpline at 104 or consult your doctor.",
                citations=["G-FOOD-TIMING", "G-JAN-AUSHADHI", "G-DOSE-CODE"]
            )
            enforced_plan, _ = _enforce(fallback_plan, facts, lang, False)
            plan_dict = enforced_plan.model_dump()
            meta["passes"] = 1
            meta["latency_ms"] = int((time.time() - t0) * 1000)
            return {"plan": plan_dict, "meta": meta}
        plan_dict = safety.HANDOFF_CARD[lang].copy()
        plan_dict["language"] = lang
        return {"plan": plan_dict, "meta": {"path": "handoff", "latency_ms": int((time.time() - t0) * 1000)}}

    if gate.tripped:
        print(f"[safety] RED FLAG ({', '.join(gate.tripped)}) -> emergency referral sent", flush=True)
        plan_dict = safety.HANDOFF_CARD[lang].copy()
        plan_dict["language"] = lang
        meta = {"path": "handoff", "red_flags": gate.tripped, "latency_ms": int((time.time() - t0) * 1000)}
        print(f"[lang] language: {lang}", flush=True)
        print(f"[plan] {plan_dict['answer'][:150]}", flush=True)
        return {"plan": plan_dict, "meta": meta}

    planner_res = res.results.get("planner")
    raw_plan = getattr(planner_res.result, "structured_output", None) if planner_res else None

    critic_res = res.results.get("critic")
    critique = getattr(critic_res.result, "structured_output", None) if critic_res else None
    critic_ok = bool(critique and critique.ok)

    if raw_plan is None:
        if facts.get("items"):
            item = facts["items"][0]
            ans_text = (
                f"மருந்து: {item['generic_name']} ({item['medication']}). நேரம்: {item['timing']}. {item['food_instruction']}"
                if lang == "ta" else
                f"Medication: {item['generic_name']} ({item['medication']}). Timing: {item['timing']}. {item['food_instruction']}"
            )
            raw_plan = PrescriptionAnswer(
                language=lang,
                answer=ans_text,
                steps=[item["timing"], item["food_instruction"]],
                nearest_kendra=facts["kendra"],
                savings=facts["savings_desc"],
                escalation="உடனடி ஆலோசனைக்கு 24x7 தமிழ்நாடு மருத்துவ உதவி எண் 104 அழையுங்கள் அல்லது மருத்துவரை அணுகுங்கள்." if lang == "ta" else "For medical assistance, contact the 24x7 Tamil Nadu Health Helpline at 104 or consult your doctor.",
                citations=["G-FOOD-TIMING", "G-JAN-AUSHADHI", "G-DOSE-CODE"]
            )
            enforced_plan, _ = _enforce(raw_plan, facts, lang, False)
            plan_dict = enforced_plan.model_dump()
            meta["passes"] = sum(1 for x in res.execution_order if x.node_id == "planner")
        else:
            plan_dict = safety.HANDOFF_CARD[lang].copy()
            plan_dict["language"] = lang
            meta["path"] = "handoff"
    else:
        enforced_plan, _ = _enforce(raw_plan, facts, lang, critic_ok)
        plan_dict = enforced_plan.model_dump()
        meta["passes"] = sum(1 for x in res.execution_order if x.node_id == "planner")

    meta["latency_ms"] = int((time.time() - t0) * 1000)
    print(f"[lang] language: {lang}", flush=True)
    print(f"[plan] {plan_dict.get('answer', '')[:150]}", flush=True)
    return {"plan": plan_dict, "meta": meta}


def main():
    parser = argparse.ArgumentParser(description="Marunthu-Thozhan medication safety assistant")
    parser.add_argument("text", help="Prescription slip text or question")
    parser.add_argument("--lang", choices=["en", "ta"], help="Force output language")
    args = parser.parse_args()

    case = {"text": args.text}
    if args.lang:
        case["lang"] = args.lang

    res = run(case)
    print("\n--- PRESCRIPTION PLAN ---")
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
