"""Clinical safety rules and fail-closed Strands hooks for Marunthu-Thozhan."""
import re
from strands.hooks import BeforeNodeCallEvent, HookProvider, HookRegistry

# Regex pattern matching any dosage modification, missed dose dilemma, or critical medical emergency
RED_FLAG_PATTERN = re.compile(
    r"(இரண்டு|2|இரண்டுமே|கூடுதல்|அதிக|double|two|extra).{0,25}(மாத்திரை|பில்|டோஸ்|tablet|pill|dose)|"
    r"missed.{0,15}dose|மறந்து.*மாத்திரை|stop taking|quit taking|change.{0,15}dose|"
    r"swallowed.{0,15}\d+|overdose|பூச்சிக்கொல்லி|விஷம்|pesticide|poison|chest pain|"
    r"நெஞ்சு.*வலி|மார்பு.*வலி|மூச்சு.*திணறு|shortness of breath|unable to breathe|"
    r"vomit.{0,10}blood|ரத்த வாந்தி|unconscious|unresponsive|மயக்கம்|suicide|தற்கொலை|swelling of lips",
    re.IGNORECASE
)

HANDOFF_CARD = {
    "en": {
        "language": "en",
        "answer": "CRITICAL CLINICAL ALERT: This inquiry involves an unverified dosage alteration or acute medical emergency. To prevent severe health harm or toxicity, do not change doses without direct physician evaluation.",
        "steps": [
            "Never take extra tablets or alter prescribed doses to make up for missed doses.",
            "Do not stop chronic blood pressure, thyroid, or diabetes medication abruptly.",
            "Report immediately to Government Rajaji Hospital (GRH) Emergency Casualty, Panagal Road, Goripalayam, Madurai 625020."
        ],
        "nearest_kendra": "Government Rajaji Hospital (GRH) Emergency Casualty, Panagal Road, Goripalayam, Madurai 625020 (Open 24x7)",
        "savings": "Emergency Care: Direct government medical attention required",
        "escalation": "IMMEDIATE EMERGENCY ACTION: Call 108 for free ambulance, contact the 24x7 Tamil Nadu Health Helpline at 104, or visit GRH Madurai Casualty immediately.",
        "citations": ["G-DOSE-CODE", "G-EMERGENCY-108"]
    },
    "ta": {
        "language": "ta",
        "answer": "அவசர மருத்துவ எச்சரிக்கை: மாத்திரை அளவை மாற்றுவது அல்லது தீவிர அறிகுறிகள் உயிருக்கு ஆபத்தானது. சுயமாக அளவை மாற்றாதீர்கள்.",
        "steps": [
            "மருத்துவர் பரிந்துரைக்காமல் கூடுதல் மாத்திரை எடுக்கக்கூடாது.",
            "பிரஷர் அல்லது சர்க்கரை மாத்திரையை தன்னிச்சையாக நிறுத்தக்கூடாது.",
            "உடனே மதுரை ராஜாஜி அரசு மருத்துவமனை (GRH) அவசர சிகிச்சைப் பிரிவுக்குச் செல்லுங்கள்."
        ],
        "nearest_kendra": "அரசு ராஜாஜி மருத்துவமனை (GRH) அவசர சிகிச்சைப் பிரிவு, பனகல் ரோடு, கோரிப்பாளையம், மதுரை 625020 (24 மணி நேரமும் செயல்படுகிறது)",
        "savings": "அவசர சிகிச்சை: நேரடி அரசு மருத்துவ உதவி தேவை",
        "escalation": "உடனடி உதவி தேவை: இலவச ஆம்புலன்ஸ் சேவைக்கு 108 அல்லது தமிழ்நாடு மருத்துவ உதவிக்கு 104 அழையுங்கள்; அல்லது உடனே மதுரை ராஜாஜி அரசு மருத்துவமனைக்குச் செல்லுங்கள்.",
        "citations": ["G-DOSE-CODE", "G-EMERGENCY-108"]
    }
}


def check_red_flags(text: str) -> list[str]:
    """Check text against safety patterns. Returns matching triggers if any."""
    match = RED_FLAG_PATTERN.search(text or "")
    if match:
        return [match.group(0).strip()]
    return []


class RedFlagGate(HookProvider):
    """Strands HookProvider that cancels graph nodes when dose change or emergency red-flag patterns match."""

    def __init__(self):
        super().__init__()
        self.tripped = []

    def register_hooks(self, registry: HookRegistry, **_):
        registry.add_callback(BeforeNodeCallEvent, self._before_node_call)

    def _before_node_call(self, event: BeforeNodeCallEvent):
        state = event.invocation_state or {}
        text = str(state.get("user_text", ""))
        hits = check_red_flags(text)
        if hits:
            self.tripped = hits
            event.cancel_node = f"Clinical Red Flag: {', '.join(hits)}"
