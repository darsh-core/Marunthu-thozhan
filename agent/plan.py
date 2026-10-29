"""Structured outputs for Marunthu-Thozhan: PrescriptionAnswer and Critique."""
from typing import Literal
from pydantic import BaseModel, Field


class PrescriptionAnswer(BaseModel):
    language: Literal["en", "ta"] = Field(description="Language of response: en for English, ta for Tamil script")
    answer: str = Field(description="The medication schedule, food timing explanation, and savings in user language")
    steps: list[str] = Field(default_factory=list, description="Practical action steps for the patient")
    nearest_kendra: str = Field(default="", description="Nearest Jan Aushadhi Kendra in Madurai")
    savings: str = Field(default="", description="Estimated monthly generic medicine savings")
    escalation: str = Field(description="Mandatory advisory to consult doctor/pharmacist or call Tamil Nadu 104 helpline")
    citations: list[str] = Field(description="Guidance ids from lookup_guidance (e.g. G-FOOD-TIMING, G-JAN-AUSHADHI)")


class Critique(BaseModel):
    ok: bool = Field(description="True if the plan satisfies all safety and quality rules, False otherwise")
    problems: list[str] = Field(default_factory=list, description="List of violations if ok is False")
