import json

import httpx
import pytest

from trialmatch.clinicaltrials import ClinicalTrialsClient, TrialApiError
from trialmatch.evaluation import hallucination_rate, ndcg_at_10, precision_at_10


def study(nct_id: str = "NCT01234567", sex: str = "FEMALE") -> dict:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": "Synthetic trial"},
            "statusModule": {"overallStatus": "RECRUITING"},
            "eligibilityModule": {
                "sex": sex,
                "minimumAge": "18 Years",
                "maximumAge": "65 Years",
                "inclusionCriteria": "- Adults with a confirmed diagnosis.",
                "exclusionCriteria": "- Active brain metastases.",
            },
            "conditionsModule": {"conditions": ["Breast Cancer"]},
            "descriptionModule": {"briefSummary": "Fictional summary for a unit test."},
            "contactsLocationsModule": {"locations": []},
        }
    }


def test_search_parses_public_api_response_and_caches(tmp_path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"studies": [study()]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = ClinicalTrialsClient(cache_dir=tmp_path, client=http)
    result = client.search_trials("breast cancer", age=54, sex="female", limit=3)
    again = client.search_trials("breast cancer", age=54, sex="female", limit=3)
    assert len(result) == len(again) == 1
    assert result[0].nct_id == "NCT01234567"
    assert "Exclusion Criteria" in result[0].eligibility_criteria
    assert len(calls) == 1
    http.close()


def test_search_filters_by_sex_and_age(tmp_path) -> None:
    all_sex = study(nct_id="NCT00000002", sex="ALL")
    all_sex["protocolSection"]["eligibilityModule"]["maximumAge"] = "No limit"
    over_age = study(nct_id="NCT00000003", sex="ALL")
    payload = {"studies": [study(sex="MALE"), all_sex, over_age]}
    http = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    result = ClinicalTrialsClient(cache_dir=tmp_path, client=http).search_trials(
        "cancer", age=70, sex="female"
    )
    assert [trial.nct_id for trial in result] == ["NCT00000002"]
    http.close()


def test_search_excludes_trials_with_unrelated_conditions(tmp_path) -> None:
    relevant = study("NCT00000011", sex="ALL")
    unrelated = study("NCT00000012", sex="ALL")
    unrelated["protocolSection"]["conditionsModule"]["conditions"] = [
        "Chemotherapy-Induced Peripheral Neuropathy"
    ]
    unrelated["protocolSection"]["identificationModule"]["briefTitle"] = (
        "Foot bath for peripheral neuropathy"
    )
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"studies": [unrelated, relevant]},
            )
        )
    )
    result = ClinicalTrialsClient(cache_dir=tmp_path, client=http).search_trials(
        "breast cancer"
    )
    assert [trial.nct_id for trial in result] == ["NCT00000011"]
    assert result[0].conditions == ["Breast Cancer"]
    http.close()


def test_invasive_ductal_carcinoma_query_matches_breast_cancer_condition(tmp_path) -> None:
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"studies": [study("NCT00000021", sex="ALL")]},
            )
        )
    )
    result = ClinicalTrialsClient(cache_dir=tmp_path, client=http).search_trials(
        "invasive ductal carcinoma"
    )
    assert [trial.nct_id for trial in result] == ["NCT00000021"]
    http.close()


def test_turkish_city_uses_geo_filter_and_orders_nearest_location_first(tmp_path) -> None:
    farther = study("NCT00000002", sex="ALL")
    farther["protocolSection"]["contactsLocationsModule"] = {
        "locations": [
            {
                "facility": "Far Hospital",
                "city": "Izmir",
                "country": "Türkiye",
                "geoPoint": {"lat": 38.4237, "lon": 27.1428},
            }
        ]
    }
    nearer = study("NCT00000003", sex="ALL")
    nearer["protocolSection"]["contactsLocationsModule"] = {
        "locations": [
            {
                "facility": "Near Hospital",
                "city": "Istanbul",
                "country": "Türkiye",
                "geoPoint": {"lat": 41.02, "lon": 28.99},
            }
        ]
    }
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"studies": [farther, nearer]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    result = ClinicalTrialsClient(cache_dir=tmp_path, client=http).search_trials(
        "breast cancer", location="İstanbul", sex="female"
    )
    assert requests[0].url.params["filter.geo"] == "distance(41.0082,28.9784,50km)"
    assert [trial.nct_id for trial in result] == ["NCT00000003", "NCT00000002"]
    assert result[0].distance_km is not None and result[0].distance_km < 2
    assert result[0].nearest_location == "Near Hospital, Istanbul, Türkiye"
    http.close()


def test_get_trial_can_restore_distance_for_mcp_detail_fetch(tmp_path) -> None:
    payload = study()
    payload["protocolSection"]["contactsLocationsModule"] = {
        "locations": [
            {
                "facility": "Fictional Istanbul Center",
                "city": "Istanbul",
                "country": "Türkiye",
                "geoPoint": {"lat": 41.02, "lon": 28.99},
            }
        ]
    }
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )
    )
    result = ClinicalTrialsClient(cache_dir=tmp_path, client=http).get_trial(
        "NCT01234567", location="İstanbul"
    )
    assert result is not None
    assert result.nearest_location == "Fictional Istanbul Center, Istanbul, Türkiye"
    assert result.distance_km is not None
    http.close()


def test_invalid_nct_id_is_rejected_before_request(tmp_path) -> None:
    client = ClinicalTrialsClient(cache_dir=tmp_path)
    with pytest.raises(ValueError):
        client.get_trial("NCT99999999;delete")


def test_rate_limited_empty_response_reports_http_status(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            429,
            text="Too many requests",
            headers={"Retry-After": "0"},
        )

    monkeypatch.setattr("trialmatch.clinicaltrials.time.sleep", lambda _: None)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = ClinicalTrialsClient(
        cache_dir=tmp_path,
        client=http,
        min_request_interval=0,
    )
    with pytest.raises(TrialApiError, match="HTTP 429"):
        client.get_trial("NCT01234567")
    assert len(calls) == 3
    http.close()


def test_trec_metrics_use_expected_relevance_gains() -> None:
    qrels = {"NCT00000001": 2, "NCT00000002": 1, "NCT00000003": 0}
    ranked = ["NCT00000002", "NCT00000001", "NCT00000003"]
    assert precision_at_10(ranked, qrels) == 0.1
    assert 0 < ndcg_at_10(ranked, qrels) < 1
    assert hallucination_rate(ranked, set(qrels)) == 0
    assert hallucination_rate(["NCT99999999"], set(qrels)) == 1
