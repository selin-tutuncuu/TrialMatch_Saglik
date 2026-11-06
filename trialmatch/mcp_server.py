from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from trialmatch.clinicaltrials import ClinicalTrialsClient

mcp = FastMCP("TrialMatch ClinicalTrials.gov tools")
_TRIALS_CLIENT: ClinicalTrialsClient | None = None


def _client() -> ClinicalTrialsClient:
    global _TRIALS_CLIENT
    if _TRIALS_CLIENT is None:
        _TRIALS_CLIENT = ClinicalTrialsClient(
            cache_dir=Path(os.getenv("TRIALMATCH_CACHE_DIR", "data/cache"))
        )
    return _TRIALS_CLIENT


@mcp.tool()
def search_trials(
    condition: str,
    status: str = "RECRUITING",
    location: str | None = None,
    age: int | None = None,
    sex: str = "unknown",
    limit: int = 20,
) -> str:
    """Search ClinicalTrials.gov for recruiting trials and return verified study summaries."""
    trials = _client().search_trials(condition, status, location, age, sex, limit)
    return json.dumps([trial.model_dump(mode="json") for trial in trials], ensure_ascii=False)


@mcp.tool()
def get_trial(nct_id: str, location: str | None = None) -> str:
    """Fetch and verify one study by its NCT identifier; returns NOT_FOUND if absent."""
    trial = _client().get_trial(nct_id, location=location)
    return "NOT_FOUND" if trial is None else trial.model_dump_json()


if __name__ == "__main__":
    mcp.run(transport="stdio")
