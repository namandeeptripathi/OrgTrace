"""Stage 18: Deterministic Competition Evaluation Dataset Loader.

Provides reproducible loading, deterministic random sampling with seed support,
and dataset fingerprinting for competition evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Iterable


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "evaluation" / "default_companies.json"


@dataclass
class EvaluationDatasetCase:
    """A single deterministic evaluation benchmark case."""
    case_id: str
    query: str
    expected_org_number: str | None
    expected_name: str | None
    expected_website: str | None = None
    category: str = "general"
    description: str = ""
    baseline_profile: dict[str, Any] | None = None
    expected_changes: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "case_id": self.case_id,
            "query": self.query,
            "expected_org_number": self.expected_org_number,
            "expected_name": self.expected_name,
            "expected_website": self.expected_website,
            "category": self.category,
            "description": self.description,
        }
        if self.baseline_profile:
            data["baseline_profile"] = self.baseline_profile
        if self.expected_changes:
            data["expected_changes"] = self.expected_changes
        if self.metadata:
            data["metadata"] = self.metadata
        return data


def compute_dataset_hash(cases: Iterable[EvaluationDatasetCase]) -> str:
    """Compute a deterministic SHA-256 hash of the evaluation dataset contents."""
    serialized = [c.to_dict() for c in cases]
    serialized.sort(key=lambda x: str(x.get("case_id") or ""))
    raw = json.dumps(serialized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_dataset_json(data: list[dict[str, Any]]) -> list[EvaluationDatasetCase]:
    """Parse raw dictionary items into EvaluationDatasetCase records."""
    cases: list[EvaluationDatasetCase] = []
    seen_ids: set[str] = set()

    for item in data:
        cid = str(item.get("case_id") or f"eval-{len(cases) + 1:03d}")
        if cid in seen_ids:
            # Guarantee uniqueness
            cid = f"{cid}-{len(cases) + 1}"
        seen_ids.add(cid)

        case = EvaluationDatasetCase(
            case_id=cid,
            query=str(item.get("query") or item.get("name") or item.get("organisation_number") or ""),
            expected_org_number=item.get("expected_org_number") or item.get("organisation_number"),
            expected_name=item.get("expected_name") or item.get("name"),
            expected_website=item.get("expected_website") or item.get("website"),
            category=str(item.get("category") or "general"),
            description=str(item.get("description") or ""),
            baseline_profile=item.get("baseline_profile"),
            expected_changes=list(item.get("expected_changes") or []),
            metadata=dict(item.get("metadata") or {}),
        )
        cases.append(case)
    return cases


def load_evaluation_dataset(dataset_path: str | Path | None = None) -> tuple[list[EvaluationDatasetCase], str]:
    """Load the evaluation dataset from a JSON / JSONL file or built-in defaults.

    Returns:
        tuple of (cases, dataset_hash)
    """
    path = Path(dataset_path) if dataset_path else DEFAULT_DATASET_PATH
    if not path.exists():
        raise FileNotFoundError(f"Evaluation dataset file not found at: {path}")

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        raw_items = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        raw_items = json.loads(text)
        if not isinstance(raw_items, list):
            raw_items = raw_items.get("cases", [])

    cases = parse_dataset_json(raw_items)
    d_hash = compute_dataset_hash(cases)
    return cases, d_hash


def select_evaluation_cases(
    cases: list[EvaluationDatasetCase],
    *,
    count: int | None = None,
    seed: int | None = None,
    target_company: str | None = None,
) -> list[EvaluationDatasetCase]:
    """Deterministically select evaluation cases based on CLI parameters.

    Supports:
    - Target company query match (--company)
    - Deterministic random sampling (--random N --seed S)
    - Full dataset selection
    """
    if target_company:
        target_norm = target_company.strip().lower()
        matched = [
            c for c in cases
            if target_norm == c.query.lower()
            or (c.expected_name and target_norm in c.expected_name.lower())
            or (c.expected_org_number and target_norm == c.expected_org_number)
            or (target_norm in c.case_id.lower())
        ]
        if matched:
            return matched
        # If not present in dataset, construct an ad-hoc case on the fly
        is_digit_org = target_company.strip().isdigit() and len(target_company.strip()) == 9
        return [
            EvaluationDatasetCase(
                case_id="eval-custom-001",
                query=target_company.strip(),
                expected_org_number=target_company.strip() if is_digit_org else None,
                expected_name=None if is_digit_org else target_company.strip(),
                category="targeted_debug",
                description=f"Ad-hoc targeted evaluation for: {target_company}",
            )
        ]

    if count is not None and count > 0:
        if count >= len(cases):
            return list(cases)
        rng = random.Random(seed)
        # Sample without replacement to ensure no duplicates
        return rng.sample(cases, count)

    return list(cases)
