from __future__ import annotations

import json
import re
from pathlib import Path

from trialmatch.agents import DISCLAIMER
from trialmatch.models import PrescreenReport


def save_report(report: PrescreenReport, approved: bool, output_dir: Path | None = None) -> Path:
    """Persist a report only after an explicit coordinator confirmation."""
    if not approved:
        raise PermissionError("Coordinator approval is required before saving or sharing a report.")
    if report.rejected:
        raise ValueError("A refused request cannot be saved as a prescreen report.")
    if report.disclaimer != DISCLAIMER or report.closing_disclaimer != DISCLAIMER:
        raise ValueError("The required medical decision-support disclaimer is missing.")

    destination = output_dir or Path("reports")
    destination.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-f0-9]", "", report.audit_id.casefold())
    if len(safe_id) < 8:
        raise ValueError("The report audit identifier is invalid.")
    path = destination / f"prescreen-{safe_id}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path
