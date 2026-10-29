"""Deterministic tools for Marunthu-Thozhan: Curated CDSCO guidance, Jan Aushadhi generic mapping, and Madurai Kendras."""
import json
import re
from functools import lru_cache
from pathlib import Path

from strands import tool

DATA = Path(__file__).parent / "data"
TAMIL = re.compile(r"[\u0B80-\u0BFF]")


@lru_cache(maxsize=1)
def guidance():
    return json.loads((DATA / "guidance.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def medications_db():
    return json.loads((DATA / "medications.json").read_text(encoding="utf-8"))["medications"]


@lru_cache(maxsize=1)
def kendras_db():
    return json.loads((DATA / "kendras.json").read_text(encoding="utf-8"))["kendras"]


def guidance_ids():
    return {g["id"] for g in guidance()["items"]}


def language_of(text: str) -> str:
    return "ta" if TAMIL.search(text or "") else "en"


def has_tamil(text: str) -> bool:
    return bool(TAMIL.search(text or ""))


@tool
def lookup_guidance(topic: str) -> list[dict]:
    """Find curated clinical dispensing guidance to cite. Returns items with id and text.

    Args:
        topic: words or medicine names to match
    """
    words = [w for w in re.findall(r"\w+", (topic or "").lower()) if len(w) > 2]
    items = guidance()["items"]
    hits = [g for g in items if any(w in (g["id"] + " " + g["text"]).lower() for w in words)]
    return [{"id": g["id"], "text": g["text"]} for g in (hits or items)[:6]]


@tool
def lookup_medication(medicine_name: str) -> dict:
    """Look up a prescribed medicine to find its Jan Aushadhi generic equivalent, standard timing, food rules, and price comparison.

    Args:
        medicine_name: name of the drug or brand from prescription (e.g., Metformin, Telma, Pan 40, Dolo, Thyronorm)
    """
    clean = (medicine_name or "").lower().strip()
    meds = medications_db()

    # Match aliases
    match = None
    for m in meds:
        if clean in m["key"] or any(clean in a or a in clean for a in m["aliases"]):
            match = m
            break

    if not match:
        # Fallback partial word match
        for m in meds:
            for alias in m["aliases"]:
                if any(w in clean for w in alias.split()):
                    match = m
                    break
            if match:
                break

    if not match:
        return {
            "found": False,
            "query": medicine_name,
            "message": f"Medicine '{medicine_name}' not in verified local database. Consult pharmacist for verification."
        }

    savings = round(match["retail_brand_price_inr"] - match["jan_aushadhi_price_inr"], 2)
    return {
        "found": True,
        "matched_brand": medicine_name,
        "generic_name": match["generic_name"],
        "category": match["category"],
        "standard_timing": match["standard_timing"],
        "timing_en": match["timing_description_en"],
        "timing_ta": match["timing_description_ta"],
        "food_instruction_en": match["food_instructions_en"],
        "food_instruction_ta": match["food_instructions_ta"],
        "warnings_en": match["warnings_en"],
        "warnings_ta": match["warnings_ta"],
        "retail_price_inr": match["retail_brand_price_inr"],
        "jan_aushadhi_price_inr": match["jan_aushadhi_price_inr"],
        "monthly_savings_inr": savings
    }


@tool
def find_nearest_jan_aushadhi(area_or_landmark: str = "") -> dict:
    """Find the nearest Pradhan Mantri Bhartiya Janaushadhi Kendra in Madurai with address, timings, and contact number.

    Args:
        area_or_landmark: landmark in Madurai (e.g. Goripalayam, GRH, Anna Nagar, Simmakkal, Periyar)
    """
    kendras = kendras_db()
    query = (area_or_landmark or "").lower()

    # Search for matching kendra
    for k in kendras:
        if any(term in k["landmark"].lower() or term in k["address"].lower() for term in query.split() if len(term) > 3):
            return {"kendra": k, "note": "Direct match in Madurai"}

    # Default to the primary hub opposite GRH Goripalayam
    return {"kendra": kendras[0], "note": "Primary centre opposite Government Rajaji Hospital Gate 2"}
