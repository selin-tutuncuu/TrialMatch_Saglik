from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from trialmatch.models import PatientProfile, TrialSummary

API_ROOT = "https://clinicaltrials.gov/api/v2"
NCT_PATTERN = re.compile(r"^NCT\d{8}$")
_CITY_COORDINATES = {
    "istanbul": (41.0082, 28.9784),
    "ankara": (39.9334, 32.8597),
    "izmir": (38.4237, 27.1428),
    "bursa": (40.1885, 29.0610),
    "antalya": (36.8969, 30.7133),
}
_CONDITION_GROUPS = (
    {
        "breast cancer",
        "breast carcinoma",
        "mammary cancer",
        "mammary carcinoma",
        "breast neoplasm",
        "breast neoplasms",
        "breast tumor",
        "breast tumors",
        "breast tumour",
        "breast tumours",
        "breast malignancy",
        "invasive ductal carcinoma",
        "ductal carcinoma",
        "ductal carcinoma of the breast",
        "breast ductal carcinoma",
        "invasive lobular carcinoma",
        "lobular carcinoma",
        "lobular carcinoma of the breast",
        "triple-negative breast cancer",
        "triple negative breast cancer",
        "her2-positive breast cancer",
        "her2 positive breast cancer",
    },
)


def _normalize_city(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _normalize_condition(value: str) -> str:
    return re.sub(r"\s+", " ", _normalize_city(value)).strip()


def _condition_matches(trial_conditions: list[str], query: str) -> bool:
    normalized_query = _normalize_condition(query)
    if not trial_conditions:
        return False
    for group in _CONDITION_GROUPS:
        normalized_group = {_normalize_condition(item) for item in group}
        if any(
            _contains_phrase(normalized_query, alias)
            for alias in normalized_group
        ):
            return any(
                _contains_phrase(_normalize_condition(condition), alias)
                for condition in trial_conditions
                for alias in normalized_group
            )
    return any(
        _contains_phrase(_normalize_condition(condition), normalized_query)
        or _contains_phrase(normalized_query, _normalize_condition(condition))
        for condition in trial_conditions
    )


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


def _distance_km(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1 = map(radians, origin)
    lat2, lon2 = map(radians, destination)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(value))


class TrialApiError(RuntimeError):
    """A ClinicalTrials.gov request failed or returned invalid data."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _cache_key(url: str, params: dict[str, Any] | None = None) -> str:
    canonical = json.dumps([url, params or {}], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ClinicalTrialsClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        cache_ttl: timedelta = timedelta(hours=24),
        timeout: float = 20,
        client: httpx.Client | None = None,
        min_request_interval: float = 0.5,
    ) -> None:
        self.cache_dir = cache_dir or Path("data/cache")
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self._http = client
        self._last_fetched_at: str | None = None
        self.min_request_interval = min_request_interval
        self._last_request_at: float | None = None

    def _read_cache(self, key: str) -> tuple[Any, str] | None:
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(cached["fetched_at"])
            if _now() - fetched_at <= self.cache_ttl:
                return cached["payload"], fetched_at.isoformat()
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None
        return None

    def _write_cache(self, key: str, payload: Any, fetched_at: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"fetched_at": fetched_at, "payload": payload},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 10.0))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    return max(0.0, min((retry_at - _now()).total_seconds(), 10.0))
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(1.0 * (2**attempt), 4.0)

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{API_ROOT}{path}"
        key = _cache_key(url, params)
        cached = self._read_cache(key)
        if cached is not None:
            payload, self._last_fetched_at = cached
            return payload

        owns_client = self._http is None
        http = self._http or httpx.Client(timeout=self.timeout, follow_redirects=True)
        try:
            for attempt in range(3):
                try:
                    if self._last_request_at is not None:
                        elapsed = time.monotonic() - self._last_request_at
                        if elapsed < self.min_request_interval:
                            time.sleep(self.min_request_interval - elapsed)
                    self._last_request_at = time.monotonic()
                    response = http.get(url, params=params)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < 2:
                            time.sleep(self._retry_delay(response, attempt))
                            continue
                    response.raise_for_status()
                    payload = response.json()
                    self._last_fetched_at = _now().isoformat()
                    self._write_cache(key, payload, self._last_fetched_at)
                    return payload
                except httpx.TimeoutException:
                    if attempt == 2:
                        raise TrialApiError(
                            "ClinicalTrials.gov request timed out after retries."
                        ) from None
                    time.sleep(0.25 * (2**attempt))
                except httpx.HTTPStatusError as error:
                    status_code = error.response.status_code
                    if (status_code == 429 or status_code >= 500) and attempt < 2:
                        time.sleep(self._retry_delay(error.response, attempt))
                        continue
                    raise TrialApiError(
                        f"ClinicalTrials.gov returned HTTP {status_code}.",
                        status_code=status_code,
                    ) from error
                except (httpx.RequestError, json.JSONDecodeError) as error:
                    if attempt == 2:
                        raise TrialApiError(f"ClinicalTrials.gov request failed: {error}") from error
                    time.sleep(0.25 * (2**attempt))
        finally:
            if owns_client:
                http.close()
        raise TrialApiError("ClinicalTrials.gov request failed after retries.")

    def search_trials(
        self,
        condition: str,
        status: str = "RECRUITING",
        location: str | None = None,
        age: int | None = None,
        sex: str = "unknown",
        limit: int = 20,
    ) -> list[TrialSummary]:
        if status != "RECRUITING":
            raise ValueError("This educational prototype only searches recruiting studies.")
        if not condition.strip():
            raise ValueError("A diagnosis or condition is required for a study search.")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")

        params: dict[str, Any] = {
            "query.cond": condition.strip(),
            "filter.overallStatus": status,
            "pageSize": limit,
            "countTotal": "true",
            "format": "json",
        }
        if location:
            params["query.locn"] = location.strip()
            coordinates = _CITY_COORDINATES.get(_normalize_city(location))
            if coordinates:
                lat, lon = coordinates
                params["filter.geo"] = f"distance({lat},{lon},50km)"

        payload = self._request_json("/studies", params)
        trials = [
            trial
            for item in payload.get("studies", [])
            if (
                trial := self._to_summary(
                    item,
                    self._last_fetched_at,
                    origin=_CITY_COORDINATES.get(_normalize_city(location)) if location else None,
                )
            ) is not None
        ]
        filtered = [
            trial
            for trial in trials
            if _condition_matches(trial.conditions, condition)
            and self._age_sex_match(trial, age=age, sex=sex)
        ]
        return sorted(
            filtered,
            key=lambda trial: (
                trial.distance_km is None,
                trial.distance_km if trial.distance_km is not None else float("inf"),
            ),
        )

    def get_trial(self, nct_id: str, location: str | None = None) -> TrialSummary | None:
        if not NCT_PATTERN.fullmatch(nct_id):
            raise ValueError("Invalid NCT identifier.")
        try:
            payload = self._request_json(f"/studies/{nct_id}")
        except TrialApiError as error:
            if error.status_code == 404:
                return None
            raise
        origin = _CITY_COORDINATES.get(_normalize_city(location)) if location else None
        return self._to_summary(payload, self._last_fetched_at, origin=origin)

    @staticmethod
    def _to_summary(
        item: dict[str, Any],
        fetched_at: str | None = None,
        origin: tuple[float, float] | None = None,
    ) -> TrialSummary | None:
        protocol = item.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        nct_id = identification.get("nctId")
        if not isinstance(nct_id, str) or not NCT_PATTERN.fullmatch(nct_id):
            return None

        status_module = protocol.get("statusModule", {})
        eligibility = protocol.get("eligibilityModule", {})
        description = protocol.get("descriptionModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        locations_module = protocol.get("contactsLocationsModule", {})
        inclusion = eligibility.get("inclusionCriteria", "")
        exclusion = eligibility.get("exclusionCriteria", "")
        criteria = "\n".join(
            part for part in (
                f"Inclusion Criteria:\n{inclusion}" if inclusion else "",
                f"Exclusion Criteria:\n{exclusion}" if exclusion else "",
            ) if part
        ) or eligibility.get("eligibilityCriteria")

        location_entries = locations_module.get("locations", [])
        nearest_location: str | None = None
        nearest_distance: float | None = None
        if origin:
            for entry in location_entries:
                geo = entry.get("geoPoint") or {}
                lat, lon = geo.get("lat"), geo.get("lon")
                if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                    continue
                distance = _distance_km(origin, (float(lat), float(lon)))
                if nearest_distance is None or distance < nearest_distance:
                    nearest_distance = distance
                    nearest_location = ", ".join(
                        part
                        for part in (
                            entry.get("facility"),
                            entry.get("city"),
                            entry.get("country"),
                        )
                        if part
                    )

        return TrialSummary(
            nct_id=nct_id,
            title=identification.get("briefTitle") or identification.get("officialTitle") or "Untitled study",
            status=status_module.get("overallStatus", "UNKNOWN"),
            conditions=conditions_module.get("conditions", []),
            brief_summary=description.get("briefSummary"),
            eligibility_criteria=criteria,
            sex=eligibility.get("sex"),
            minimum_age=eligibility.get("minimumAge"),
            maximum_age=eligibility.get("maximumAge"),
            locations=[
                ", ".join(
                    part for part in (entry.get("facility"), entry.get("city"), entry.get("country"))
                    if part
                )
                for entry in location_entries
            ],
            nearest_location=nearest_location,
            distance_km=round(nearest_distance, 1) if nearest_distance is not None else None,
            source_url=f"https://clinicaltrials.gov/study/{nct_id}",
            fetched_at=fetched_at or _now().isoformat(),
        )

    @staticmethod
    def _age_sex_match(trial: TrialSummary, age: int | None, sex: str) -> bool:
        study_sex = (trial.sex or "ALL").casefold()
        if sex == "female" and study_sex == "male" or sex == "male" and study_sex == "female":
            return False
        if age is None:
            return True

        def years(value: str | None) -> float | None:
            if not value:
                return None
            match = re.search(r"(\d+(?:\.\d+)?)\s*(years?|months?|weeks?|days?)", value, re.I)
            if not match:
                return None
            amount = float(match.group(1))
            unit = match.group(2).casefold()
            return amount / 12 if unit.startswith("month") else amount / 52 if unit.startswith("week") else amount / 365 if unit.startswith("day") else amount

        minimum = years(trial.minimum_age)
        maximum = years(trial.maximum_age)
        return not (minimum is not None and age < minimum or maximum is not None and age > maximum)
