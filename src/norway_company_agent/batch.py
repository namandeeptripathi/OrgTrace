from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .evidence import evidence, utc_now
from .http import fetch_json
from .official import BRREG_ENTITY, accounting_obligation_assessment, normalize_entity
from .sampling import iter_bulk


TERMINAL_STATES = {
    "complete",
    "not_applicable",
    "not_found",
    "blocked_policy",
    "blocked_robots",
    "source_error",
    "budget_exhausted",
    "submission_error",
    "timeout",
    "rate_limited",
    "parse_failed",
    "not_attempted",
    "unavailable",
}


def read_organisation_inputs(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    values: list[Any]
    if source.suffix == ".json":
        body = json.loads(text)
        values = body if isinstance(body, list) else body.get("organisation_numbers", [])
    elif source.suffix == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = [line.strip() for line in text.splitlines() if line.strip()]
    records = []
    for value in values:
        org = value.get("organisation_number") if isinstance(value, dict) else value
        org = "".join(character for character in str(org or "") if character.isdigit())
        if len(org) != 9:
            raise ValueError(f"Invalid Norwegian organisation number: {value!r}")
        record = {"organisation_number": org}
        if isinstance(value, dict):
            for key in ("evaluation_split", "sample_slice"):
                if value.get(key) is not None:
                    record[key] = value[key]
        records.append(record)
    orgs = [record["organisation_number"] for record in records]
    if len(orgs) != len(set(orgs)):
        raise ValueError("Organisation-number input contains duplicates")
    return records


def read_organisation_numbers(path: str | Path) -> list[str]:
    return [record["organisation_number"] for record in read_organisation_inputs(path)]


def profiles_from_bulk(
    path: str | Path | None,
    organisation_numbers: Iterable[str],
    *,
    allow_missing: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requested = list(organisation_numbers)
    wanted = set(requested)
    retrieved_at = utc_now()

    # Fallback to live API if bulk file is missing or not provided
    bulk_path = Path(path) if path else None
    if not bulk_path or not bulk_path.exists():
        snapshot_sha256 = "live_registry_api"
        found: dict[str, dict[str, Any]] = {}
        for org in requested:
            res = fetch_json(BRREG_ENTITY.format(org=org), timeout=15.0)
            if res.status == 200 and isinstance(res.body, dict):
                entity = normalize_entity(res.body)
                found[org] = {
                    "organisation_number": org,
                    "name": entity.get("name") or "",
                    "legal_form": entity.get("legal_form") or "",
                    "employees": entity.get("employees"),
                    "bankrupt": entity.get("bankrupt") or False,
                    "liquidating": entity.get("liquidating") or False,
                    "municipality": (entity.get("business_address") or {}).get("kommune"),
                    "municipality_number": (entity.get("business_address") or {}).get("kommunenummer"),
                    "industry_code": (entity.get("industry") or {}).get("kode"),
                    "industry_label": (entity.get("industry") or {}).get("beskrivelse"),
                    "website": entity.get("website") or "",
                    "latest_submitted_accounts": entity.get("latest_submitted_accounts"),
                    "evidence": {
                        "registry": evidence(
                            "registry",
                            "available",
                            "official_registry_live",
                            BRREG_ENTITY.format(org=org),
                            value=res.body,
                            retrieved_at=retrieved_at,
                            content_sha256=res.content_sha256,
                            source_row_key=org,
                        ),
                        "accounting_obligation": accounting_obligation_assessment(entity),
                    },
                }
            else:
                found[org] = {
                    "organisation_number": org,
                    "name": "",
                    "legal_form": "",
                    "evidence": {
                        "registry": evidence(
                            "registry",
                            "not_found" if res.status in {404, 410} else "unavailable",
                            "official_registry_live",
                            BRREG_ENTITY.format(org=org),
                            note=res.error or "Live entity lookup failed",
                            retrieved_at=retrieved_at,
                            source_row_key=org,
                        ),
                        "accounting_obligation": evidence(
                            "accounting_obligation",
                            "not_applicable",
                            "official_registry_live",
                            BRREG_ENTITY.format(org=org),
                            note="No registry profile available to determine accounting obligation",
                            retrieved_at=retrieved_at,
                        ),
                    },
                }
        return [found[org] for org in requested], {
            "registry_snapshot_sha256": snapshot_sha256,
            "registry_rows_scanned": 0,
            "requested": len(requested),
            "selected": sum(1 for p in found.values() if p.get("name")),
            "missing": sum(1 for p in found.values() if not p.get("name")),
        }

    snapshot_sha256 = hashlib.sha256(bulk_path.read_bytes()).hexdigest()
    found: dict[str, dict[str, Any]] = {}
    scanned = 0
    for profile in iter_bulk(bulk_path):
        scanned += 1
        org = profile["organisation_number"]
        if org not in wanted:
            continue
        raw = profile.pop("raw", {})
        profile["evidence"] = {
            "registry": evidence(
                "registry",
                "available",
                "official_registry_bulk",
                "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
                value=raw,
                retrieved_at=retrieved_at,
                content_sha256=snapshot_sha256,
                source_row_key=org,
            ),
            "accounting_obligation": accounting_obligation_assessment(profile),
        }
        found[org] = profile
        if len(found) == len(wanted):
            break
    missing = [org for org in requested if org not in found]
    if missing and not allow_missing:
        raise ValueError(f"Organisation numbers absent from registry snapshot: {missing[:10]}")
    for org in missing:
        found[org] = {
            "organisation_number": org,
            "name": "",
            "legal_form": "",
            "evidence": {
                "registry": evidence(
                    "registry",
                    "not_found",
                    "official_registry_bulk",
                    "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
                    note="Organisation number absent from registry snapshot",
                    retrieved_at=retrieved_at,
                    content_sha256=snapshot_sha256,
                    source_row_key=org,
                ),
                "accounting_obligation": evidence(
                    "accounting_obligation",
                    "not_applicable",
                    "official_registry_bulk",
                    "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
                    note="No registry profile available to determine accounting obligation",
                    retrieved_at=retrieved_at,
                ),
            },
        }
    return [found[org] for org in requested], {
        "registry_snapshot_sha256": snapshot_sha256,
        "registry_rows_scanned": scanned,
        "requested": len(requested),
        "selected": len(found),
        "missing": len(missing),
    }


def evidence_terminal_state(record: dict[str, Any] | None) -> str:
    if not record:
        return "submission_error"
    status = record.get("status")
    if status == "available":
        return "complete"
    if status == "not_applicable":
        return "not_applicable"
    if status == "not_found":
        return "not_found"
    if status == "blocked":
        note = str(record.get("note") or "").casefold()
        return "blocked_robots" if "robot" in note else "blocked_policy"
    if status == "timeout":
        return "timeout"
    if status == "rate_limited":
        return "rate_limited"
    if status == "parse_failed":
        return "parse_failed"
    if status in {"not_attempted", "budget_exhausted"}:
        return "not_attempted"
    if status == "source_error":
        return "source_error"
    if status == "unavailable":
        return "unavailable"
    return "submission_error"


def compute_profile_status(profile: dict[str, Any]) -> str:
    """Compute frontend-ready status for a company profile.

    Distinguishes actual states without conflating them:
    - 'complete': All requested evidence modules are available.
    - 'partial': Some modules available, others missing/not_found/unavailable/blocked/timeout.
    - 'not_found': All modules not found.
    - 'unavailable': Modules failed due to upstream network/service unavailability.
    - 'blocked': Disallowed by policy or robots.txt.
    - 'timeout': Upstream timeout.
    - 'failed': Execution failure or unhandled error.
    """
    if profile.get("run_metrics", {}).get("status") == "failed":
        return "failed"
    evidence_dict = profile.get("evidence", {})
    if not evidence_dict:
        return "failed"
    statuses = [rec.get("status") for rec in evidence_dict.values() if isinstance(rec, dict)]
    if not statuses:
        return "failed"
    if all(s == "available" for s in statuses):
        return "complete"
    if any(s == "available" for s in statuses):
        return "partial"
    if all(s == "not_found" for s in statuses):
        return "not_found"
    if any(s == "unavailable" for s in statuses):
        return "unavailable"
    if any(s == "blocked" for s in statuses):
        return "blocked"
    if any(s == "timeout" for s in statuses):
        return "timeout"
    return "failed"


def terminal_envelope(
    profile: dict[str, Any],
    *,
    run_id: str,
    modules: Iterable[str],
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    module_states = {}
    for module in modules:
        record = profile.get("evidence", {}).get(module)
        module_states[module] = {
            "state": evidence_terminal_state(record),
            "retry_count": int((record or {}).get("retry_count") or 0),
            "final_timestamp": (record or {}).get("retrieved_at") or completed_at,
        }
    entity_state = "submission_error" if any(item["state"] == "submission_error" for item in module_states.values()) else "complete"
    profile_status = profile.get("status") or compute_profile_status(profile)
    profile["status"] = profile_status
    return {
        "run_id": run_id,
        "organisation_number": profile["organisation_number"],
        "state": entity_state,
        "status": profile_status,
        "started_at": started_at,
        "completed_at": completed_at,
        "modules": module_states,
        "profile": profile,
    }


def validate_envelopes(envelopes: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    orgs = [item.get("organisation_number") for item in envelopes]
    invalid_states = [
        {"organisation_number": item.get("organisation_number"), "state": state.get("state")}
        for item in envelopes
        for state in item.get("modules", {}).values()
        if state.get("state") not in TERMINAL_STATES
    ]
    checks = {
        "exact_expected_count": len(envelopes) == expected_count,
        "unique_organisation_numbers": len(orgs) == len(set(orgs)),
        "all_entity_states_terminal": all(item.get("state") in TERMINAL_STATES for item in envelopes),
        "all_module_states_terminal": not invalid_states,
        "zero_silent_drops": len(envelopes) == expected_count and len(orgs) == len(set(orgs)),
    }
    return {"passed": all(checks.values()), "checks": checks, "invalid_states": invalid_states}


def profile_complete_for_modules(profile: dict[str, Any], modules: Iterable[str]) -> bool:
    records = profile.get("evidence", {})
    return all(module in records and records[module].get("status") != "not_fetched" for module in modules)
