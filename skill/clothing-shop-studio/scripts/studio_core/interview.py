from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .errors import ValidationError

GRAPH_PATH = Path("data/interview-graph.json")
ANSWER_SOURCES = ("user", "inferred", "default")
FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REQUIRED_NODE_KEYS = (
    "id",
    "phase",
    "prompt",
    "answer_type",
    "applies_when",
    "skip_if_known",
    "inferable",
    "critical",
    "visual",
    "options_source",
)

# Free-text answers for fields that drive branching are mapped to one canonical token,
# so "T-Shirt" and "tee" select the same questions. Unrecognised text is kept verbatim.
CANONICAL_VALUES = {
    "garment_category": {
        "tee": ("t_shirt", "tshirt", "tees", "short_sleeve", "short_sleeve_tee"),
        "long_sleeve": ("long_sleeve_tee", "longsleeve", "long_sleeve_shirt", "ls_tee"),
        "performance_top": ("dri_fit", "drifit", "dri_fit_tee", "performance_tee", "running_tee", "performance"),
        "hoodie": ("hooded_sweatshirt", "hoody", "zip_hoodie", "pullover_hoodie"),
        "sweatshirt": ("crewneck", "crewneck_sweatshirt", "crew_sweatshirt"),
        "polo": ("polo_shirt",),
        "tank": ("tank_top", "singlet", "muscle_tee"),
        "jacket": ("outerwear", "coat", "windbreaker", "bomber", "bomber_jacket"),
        "bottoms": ("pants", "trousers", "shorts", "joggers", "sweatpants", "leggings"),
        "headwear": ("cap", "hat", "beanie", "bucket_hat"),
        "bag": ("tote", "tote_bag", "backpack", "duffel"),
    },
    "climate": {
        "humid_tropical": ("singapore", "tropical", "hot_humid", "hot_and_humid", "humid"),
        "hot_dry": ("desert", "arid"),
        "temperate": (),
        "cold": ("winter", "cold_weather"),
    },
}
# Fallback for descriptive phrases ("dri-fit running-club tee"), checked in order after
# exact aliases. Specific garment nouns come first so "running shorts" is bottoms.
KEYWORD_RULES = {
    "garment_category": (
        ("headwear", {"any": {"cap", "hat", "beanie", "bucket", "snapback", "trucker", "visor", "headwear"}}),
        ("bag", {"any": {"bag", "tote", "backpack", "duffel", "pouch"}}),
        ("bottoms", {"any": {"pants", "trousers", "shorts", "joggers", "sweatpants", "leggings", "bottoms", "jeans"}}),
        ("jacket", {"any": {"jacket", "coat", "windbreaker", "anorak", "bomber", "parka", "puffer", "outerwear"}}),
        ("hoodie", {"any": {"hoodie", "hoody", "hooded"}}),
        ("sweatshirt", {"any": {"sweatshirt", "crewneck", "sweater", "jumper"}}),
        ("polo", {"any": {"polo"}}),
        ("tank", {"any": {"tank", "singlet", "sleeveless"}}),
        ("performance_top", {"any": {"dri", "drifit", "performance", "running", "training", "athletic", "activewear", "wicking"}}),
        ("long_sleeve", {"all": {"long", "sleeve"}}),
        ("long_sleeve", {"any": {"longsleeve"}}),
        ("tee", {"any": {"tee", "tees", "tshirt"}}),
        ("tee", {"all": {"t", "shirt"}}),
    ),
    "climate": (
        ("humid_tropical", {"any": {"singapore", "tropical", "tropics", "humid", "humidity", "equatorial"}}),
        ("hot_dry", {"any": {"desert", "arid"}}),
        ("cold", {"any": {"winter", "cold", "snow", "freezing"}}),
        ("temperate", {"any": {"temperate", "mild"}}),
    ),
}
HEAT_TRAPPING_CATEGORIES = {"long_sleeve", "hoodie", "sweatshirt"}
CJK_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")
THEME_FIELDS = ("artwork_content", "artwork_style", "typography")
JAPANESE_KEYWORDS = ("japanese", "japan", "yokai", "yōkai", "kanji", "hiragana", "katakana")
HEAVY_GSM_THRESHOLD = 240
GSM_PATTERN = re.compile(r"^\s*(\d{2,3}(?:\.\d+)?)\s*(?:gsm|g/m2|g/m²|g)?\s*$", re.IGNORECASE)

# Confirmation questions exist to be put to the user, so they need the user's own words.
CONFIRMATION_FIELDS = {"confirm_heat_weight_tradeoff", "confirm_japanese_text_and_motif", "confirm_assumptions"}
# Culturally sensitive text cannot be confirmed by a hand-off such as "you decide".
STRICT_CONFIRMATIONS = {"confirm_japanese_text_and_motif"}
ASSUMPTION_CONFIRMATIONS = {"yes", "confirm", "confirmed", "correct", "all correct"}
DELEGATION_PATTERN = re.compile(
    r"^\s*(sounds good[,;]?\s*)?(continue|go on|proceed|next|carry on|keep going|up to you|your call"
    r"|whatever( you think| works)?|(?:ok|okay)[, ]+go with your pick"
    r"|surprise me|do what you think( is best)?|you (decide|choose|pick)"
    r"|use your (recommendation|judgement|judgment|best judgement|best judgment)( and continue)?)"
    r"\s*[.!]*\s*$",
    re.IGNORECASE,
)

CRITICAL_FIELDS = {
    "garment_category",
    "intended_use",
    "size_range",
    "artwork_content",
    "placement",
    "decoration_method",
    "quantity",
}


def load_graph(bundle_dir: Path) -> list[dict]:
    """Load and structurally check the question graph shipped inside the bundle."""
    path = Path(bundle_dir) / GRAPH_PATH
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "The interview graph is missing or unreadable.",
            path=str(path),
            recovery="Reinstall the skill bundle so data/interview-graph.json is present.",
        ) from exc
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not questions:
        raise ValidationError(
            "The interview graph has no questions.",
            path=str(path),
            recovery="Reinstall the skill bundle.",
        )
    seen = set()
    for node in questions:
        missing = [key for key in REQUIRED_NODE_KEYS if key not in node]
        if missing or node["id"] in seen:
            raise ValidationError(
                f"Interview node {node.get('id', '?')!r} is malformed or duplicated.",
                path=str(path),
                recovery="Reinstall the skill bundle.",
            )
        seen.add(node["id"])
    return questions


def is_delegation(text) -> bool:
    """True for a reply that hands the decision back rather than stating one."""
    return isinstance(text, str) and bool(DELEGATION_PATTERN.match(text))


def _condition_matches(actual, condition) -> bool:
    if not isinstance(condition, dict):
        return actual == condition
    if "in" in condition and actual not in condition["in"]:
        return False
    if "equals" in condition and actual != condition["equals"]:
        return False
    if "not_in" in condition and actual in condition["not_in"]:
        return False
    if condition.get("present") is True and actual is None:
        return False
    return True


def applies(node: dict, state: dict) -> bool:
    answers = state.get("answers", {})
    return all(_condition_matches(answers.get(field), condition) for field, condition in node.get("applies_when", {}).items())


def known(node: dict, state: dict) -> bool:
    answers = state.get("answers", {})
    return any(field in answers for field in node.get("skip_if_known", [node["id"]]))


def public_question(node: dict) -> dict:
    return {
        key: node[key]
        for key in ("id", "phase", "prompt", "answer_type", "critical", "visual", "options_source")
    }


def canonical_value(field: str, value):
    """Map a free-text answer to its canonical token where the field drives branching."""
    if field == "gsm" and isinstance(value, str):
        match = GSM_PATTERN.match(value)
        if match:
            number = float(match.group(1))
            return int(number) if number.is_integer() else number
        return value
    vocabulary = CANONICAL_VALUES.get(field)
    if vocabulary is None or not isinstance(value, str):
        return value
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    for canonical, aliases in vocabulary.items():
        if key == canonical or key in aliases:
            return canonical
    words = set(key.split("_"))
    for canonical, rule in KEYWORD_RULES.get(field, ()):
        if words & rule.get("any", words) and rule.get("all", set()) <= words:
            return canonical
    return value


def _is_heavy(gsm) -> bool:
    if isinstance(gsm, bool):
        return False
    if isinstance(gsm, (int, float)):
        return gsm >= HEAVY_GSM_THRESHOLD
    return isinstance(gsm, str) and "heavy" in gsm.lower()


def _mentions_japanese(answers: dict) -> bool:
    """Japanese characters anywhere, or a Japanese theme named in the artwork answers."""
    if any(isinstance(value, str) and CJK_PATTERN.search(value) for value in answers.values()):
        return True
    theme = " ".join(str(answers.get(field, "")) for field in THEME_FIELDS).lower()
    return any(keyword in theme for keyword in JAPANESE_KEYWORDS)


def triggered_confirmations(state: dict) -> list[str]:
    """Ids of confirmation questions the current answers require, most urgent first.

    Code decides when a confirmation is needed; the graph supplies its wording.
    """
    answers = state.get("answers", {})
    triggered = []
    if (
        answers.get("climate") == "humid_tropical"
        and answers.get("garment_category") in HEAT_TRAPPING_CATEGORIES
        and _is_heavy(answers.get("gsm"))
        and "confirm_heat_weight_tradeoff" not in answers
    ):
        triggered.append("confirm_heat_weight_tradeoff")
    if (
        "artwork_content" in answers
        and "confirm_japanese_text_and_motif" not in answers
        and _mentions_japanese(answers)
    ):
        triggered.append("confirm_japanese_text_and_motif")
    return triggered


def assumption_confirmation(state: dict, node: dict | None = None) -> dict | None:
    """One grouped question listing every pending inferred or default value."""
    pending = [item for item in state.get("assumptions", []) if not item.get("confirmed")]
    if not pending:
        return None
    summary = "; ".join(f"{item['field']}: {item['value']}" for item in pending)
    question = public_question(node) if node else {
        "id": "confirm_assumptions",
        "phase": "confirmation",
        "prompt": "Please confirm or correct these inferred details:",
        "answer_type": "confirmation_with_corrections",
        "critical": False,
        "visual": False,
        "options_source": "adaptive-interview.md#assumptions",
    }
    question["prompt"] = f"{question['prompt']} {summary}."
    question["critical"] = any(item.get("critical") for item in pending)
    return question


def next_question(state: dict, graph: list[dict]) -> dict | None:
    by_id = {node["id"]: node for node in graph}
    for question_id in triggered_confirmations(state):
        if question_id in by_id:
            return public_question(by_id[question_id])
    for node in graph:
        # Confirmation nodes are only asked when triggered above or by pending assumptions.
        if node["phase"] == "confirmation":
            continue
        if applies(node, state) and not known(node, state):
            return public_question(node)
    return assumption_confirmation(state, by_id.get("confirm_assumptions"))


def is_critical(field: str, state: dict) -> bool:
    answers = state.get("answers", {})
    production_requested = answers.get("physical_production") is True or answers.get("deliverables") in {
        "production_pack",
        "physical_production",
        "factory_handoff",
    }
    return field in CRITICAL_FIELDS and production_requested


def record_answer(
    state: dict,
    field: str,
    value,
    source: str,
    evidence: str | None = None,
    confirmed: bool = True,
    user_quote: str | None = None,
) -> dict:
    if not isinstance(field, str) or not FIELD_PATTERN.match(field):
        raise ValidationError(
            "Answer field must be a lowercase snake_case identifier.",
            field="field",
            recovery="Use a field id from the interview graph, such as `fit` or `gsm`.",
        )
    if source not in ANSWER_SOURCES:
        raise ValidationError(
            f"Answer source must be one of: {', '.join(ANSWER_SOURCES)}.",
            field="source",
            recovery="Record who supplied the value: the user, an inference, or a default.",
        )
    if not isinstance(confirmed, bool):
        raise ValidationError(
            "`confirmed` must be true or false.",
            field="confirmed",
            recovery="Send a JSON boolean.",
        )
    if field in CONFIRMATION_FIELDS:
        if source != "user" or not isinstance(user_quote, str) or not user_quote.strip():
            raise ValidationError(
                "Only the user can answer a confirmation question; record their reply in `user_quote`.",
                field="user_quote",
                recovery="Show the confirmation question to the user and record their actual words.",
            )
        if field in STRICT_CONFIRMATIONS and is_delegation(user_quote):
            raise ValidationError(
                "A hand-off such as 'you decide' does not confirm cultural or printed text.",
                field="user_quote",
                recovery="Show the exact text and motif and ask the user to confirm or correct them.",
            )
        if field == "confirm_assumptions":
            reply = re.sub(r"\s+", " ", user_quote.strip().lower()).rstrip(".!?")
            if reply not in ASSUMPTION_CONFIRMATIONS:
                raise ValidationError(
                    "Assumptions can only be confirmed with an explicit, unqualified confirmation.",
                    field="user_quote",
                    recovery="Record each correction first, show the revised assumption list, then ask for confirmation again.",
                )
    concept_ids = {
        item.get("id")
        for item in state.get("files", [])
        if item.get("origin") in {"generated_concept", "approved_design"}
    }
    if isinstance(value, str) and value.strip() in concept_ids:
        raise ValidationError(
            "Record the chosen option in words, not as a concept id.",
            field="value",
            recovery="Send the option's description as `value` and put the concept id in `evidence`.",
        )
    value = canonical_value(field, value)
    updated = copy.deepcopy(state)
    answers = updated.setdefault("answers", {})
    if field == "reference_image":
        answers[field] = value
        answers["reference_status"] = "none" if value in {None, "", False, "none"} else "supplied"
    elif field == "confirm_assumptions":
        answers[field] = value
        for item in updated.setdefault("assumptions", []):
            item["confirmed"] = True
    else:
        answers[field] = value
    assumption = {
        "field": field,
        "value": value,
        "source": source,
        "evidence": evidence,
        "confirmed": confirmed,
        "critical": is_critical(field, updated),
    }
    if user_quote is not None:
        assumption["user_quote"] = user_quote
    assumptions = [item for item in updated.setdefault("assumptions", []) if item.get("field") != field]
    assumptions.append(assumption)
    updated["assumptions"] = assumptions
    return updated
