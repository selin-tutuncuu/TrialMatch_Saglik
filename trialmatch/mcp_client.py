from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from trialmatch.clinicaltrials import NCT_PATTERN, TrialApiError
from trialmatch.models import TrialSummary


def _result_value(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    content = getattr(result, "content", [])
    for item in content:
        text = getattr(item, "text", None)
        if text:
            return text
    raise TrialApiError("ClinicalTrials MCP server returned an empty result.")


def _raise_tool_error(result: Any, tool_name: str) -> None:
    if not getattr(result, "isError", False):
        return
    details = [
        item.text
        for item in getattr(result, "content", [])
        if isinstance(getattr(item, "text", None), str) and item.text.strip()
    ]
    message = "; ".join(details) if details else "the server returned a tool error"
    raise TrialApiError(f"ClinicalTrials MCP {tool_name} failed: {message}")


class ClinicalTrialsMCPClient:
    """Starts the local stdio MCP server and uses its declared search/get tools."""

    def __init__(
        self,
        project_root: Path | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        self.cache_dir = cache_dir

    async def _search_and_fetch(
        self,
        condition: str,
        location: str | None,
        age: int | None,
        sex: str,
        limit: int,
    ) -> list[TrialSummary]:
        server_env = os.environ.copy()
        if self.cache_dir is not None:
            server_env["TRIALMATCH_CACHE_DIR"] = str(self.cache_dir)
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "trialmatch.mcp_server"],
            env=server_env,
            cwd=str(self.project_root),
        )
        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    available = {tool.name for tool in (await session.list_tools()).tools}
                    if not {"search_trials", "get_trial"}.issubset(available):
                        raise TrialApiError("The ClinicalTrials MCP server is missing required tools.")

                    search_result = await session.call_tool(
                        "search_trials",
                        {
                            "condition": condition,
                            "status": "RECRUITING",
                            "location": location,
                            "age": age,
                            "sex": sex,
                            "limit": limit,
                        },
                    )
                    _raise_tool_error(search_result, "search")
                    raw = _result_value(search_result)
                    try:
                        items = json.loads(raw) if isinstance(raw, str) else raw
                    except json.JSONDecodeError as error:
                        raise TrialApiError(
                            "ClinicalTrials MCP search returned invalid JSON."
                        ) from error
                    if not isinstance(items, list):
                        raise TrialApiError("The ClinicalTrials MCP search returned an invalid response.")

                    trials: list[TrialSummary] = []
                    for item in items:
                        nct_id = item.get("nct_id") if isinstance(item, dict) else None
                        if not isinstance(nct_id, str) or not NCT_PATTERN.fullmatch(nct_id):
                            continue
                        detail_result = await session.call_tool(
                            "get_trial",
                            {"nct_id": nct_id, "location": location},
                        )
                        _raise_tool_error(detail_result, f"get_trial({nct_id})")
                        detail = _result_value(detail_result)
                        if detail == "NOT_FOUND":
                            continue
                        if isinstance(detail, str):
                            try:
                                detail = json.loads(detail)
                            except json.JSONDecodeError as error:
                                raise TrialApiError(
                                    f"ClinicalTrials MCP get_trial({nct_id}) returned invalid JSON."
                                ) from error
                        trial = TrialSummary.model_validate(detail)
                        if trial.nct_id == nct_id and trial.status == "RECRUITING":
                            trials.append(trial)
                    return trials
        except TrialApiError:
            raise
        except ExceptionGroup as error:
            cause: BaseException = error
            while isinstance(cause, ExceptionGroup) and len(cause.exceptions) == 1:
                cause = cause.exceptions[0]
            if isinstance(cause, TrialApiError):
                raise cause
            raise TrialApiError(
                f"The ClinicalTrials MCP request failed: {cause}"
            ) from cause
        except (OSError, RuntimeError, ValueError) as error:
            raise TrialApiError(f"Unable to use the local ClinicalTrials MCP server: {error}") from error

    def search_and_fetch(
        self,
        condition: str,
        location: str | None = None,
        age: int | None = None,
        sex: str = "unknown",
        limit: int = 20,
    ) -> list[TrialSummary]:
        return asyncio.run(
            self._search_and_fetch(condition, location, age, sex, limit)
        )
