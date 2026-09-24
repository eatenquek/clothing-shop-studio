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
HEAT_TRAPPING_CATEGORIES = {"long_sleeve", "hoodie", "sweatshirt"}
HEAVY_GSM_THRESHOLD = 240
GSM_PATTERN = re.compile(r"^\s*(\d{2,3}(?:\.\d+)?)\s*(?:gsm|g/m2|g/m²|g)?\s*$", re.IGNORECASE)

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
    return value


def _is_heavy(gsm) -> bool:
    if isinstance(gsm, bool):
        return False
    if isinstance(gsm, (int, float)):
        return gsm >= HEAVY_GSM_THRESHOLD
    return isinstance(gsm, str) and "heavy" in gsm.lower()


def detect_conflicts(state: dict) -> list[dict]:
    answers = state.get("answers", {})
    conflicts = []
    if (
        answers.get("climate") == "humid_tropical"
        and answers.get("garment_category") in HEAT_TRAPPING_CATEGORIES
        and _is_heavy(answers.get("gsm"))
        and "confirm_heat_weight_tradeoff" not in answers
    ):
        conflicts.append(
            {
                "id": "confirm_heat_weight_tradeoff",
                "phase": "material",
                "prompt": "A heavy long-sleeve can trap heat in Singapore's humid climate. Keep the substantial weight, reduce the GSM, or add a breathable construction?",
                "answer_type": "choice_or_text",
                "critical": True,
                "visual": False,
                "options_source": "garments-materials.md#climate-and-weight",
            }
        )
    return conflicts


def assumption_confirmation(state: dict) -> dict | None:
    pending = [item for item in state.get("assumptions", []) if not item.get("confirmed")]
    if not pending or "confirm_assumptions" in state.get("answers", {}):
        return None
    summary = "; ".join(f"{item['field']}: {item['value']}" for item in pending)
    return {
        "id": "confirm_assumptions",
        "phase": "confirmation",
        "prompt": f"Please confirm or correct these inferred details: {summary}.",
        "answer_type": "confirmation_with_corrections",
        "critical": any(item.get("critical") for item in pending),
        "visual": False,
        "options_source": "adaptive-interview.md#assumptions",
    }


def next_question(state: dict, graph: list[dict]) -> dict | None:
    conflicts = detect_conflicts(state)
    if conflicts:
        return conflicts[0]
    for node in graph:
        if node["id"] in {"confirm_heat_weight_tradeoff", "confirm_assumptions"}:
            continue
        if applies(node, state) and not known(node, state):
            return public_question(node)
    return assumption_confirmation(state)


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
    value = canonical_value(field, value)
    updated = copy.deepcopy(state)
    answers = updated.setdefault("answers", {})
    if field == "reference_image":
        answers[field] = value
        answers["reference_status"] = "none" if value in {None, "", False, "none"} else "supplied"
    elif field == "confirm_assumptions":
        answers[field] = value
        if value not in {False, "no", "reject"}:
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
    assumptions = [item for item in updated.setdefault("assumptions", []) if item.get("field") != field]
    assumptions.append(assumption)
    updated["assumptions"] = assumptions
    return updated
