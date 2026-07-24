from datetime import UTC, date, datetime

import httpx
import pytest

from gold_intel.api.schemas import PolicyPathBundleRequest
from gold_intel.application.cme_fedwatch import cme_fedwatch_bundle
from gold_intel.providers.cme_fedwatch import CmeFedWatchProvider


@pytest.mark.asyncio
async def test_fedwatch_preserves_complete_path_and_official_publication_clock() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/as/token.oauth2":
            assert request.headers["authorization"].startswith("Basic ")
            assert request.content == b"grant_type=client_credentials"
            return httpx.Response(
                200,
                json={
                    "access_token": "test-access-token",
                    "token_type": "bearer",
                    "expires_in": 1799,
                },
            )
        assert request.headers["authorization"] == "Bearer test-access-token"
        assert request.headers["cme-application-name"] == ("Gold Market Intelligence Engine")
        if request.url.path == "/fedwatch/v1/meetings/history":
            return httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "meetingDt": "2026-01-28",
                            "offsetDayCount": -13,
                            "lowerRt": 350,
                            "upperRt": 375,
                        }
                    ],
                    "metadata": {"totalPages": 1},
                },
            )
        if request.url.path == "/fedwatch/v1/meetings/future":
            return httpx.Response(
                200,
                json={
                    "payload": [
                        {"meetingDt": "2026-03-18", "offsetDayCount": 36},
                        {"meetingDt": "2026-04-29", "offsetDayCount": 78},
                    ],
                    "metadata": {"totalPages": 1},
                },
            )
        if request.url.path == "/fedwatch/v1/forecasts":
            assert request.url.params["reportingDt"] == "2026-02-10"
            assert request.url.params["meetingDt"] == "2026-03-18,2026-04-29"
            return httpx.Response(
                200,
                json={
                    "payload": [
                        {
                            "meetingDt": "2026-03-18",
                            "reportingDt": "2026-02-10",
                            "rateRange": [
                                {
                                    "lowerRt": 325,
                                    "upperRt": 350,
                                    "probability": 0.25,
                                },
                                {
                                    "lowerRt": 350,
                                    "upperRt": 375,
                                    "probability": 0.75,
                                },
                            ],
                        },
                        {
                            "meetingDt": "2026-04-29",
                            "reportingDt": "2026-02-10",
                            "rateRange": [
                                {
                                    "lowerRt": 300,
                                    "upperRt": 325,
                                    "probability": 0.1,
                                },
                                {
                                    "lowerRt": 325,
                                    "upperRt": 350,
                                    "probability": 0.9,
                                },
                            ],
                        },
                    ],
                    "metadata": {"totalPages": 1},
                },
            )
        raise AssertionError(f"Unexpected CME path: {request.url.path}")

    provider = CmeFedWatchProvider(
        client_id="api-id",
        client_secret="api-password",
        transport=httpx.MockTransport(handler),
    )
    path = await provider.fetch(
        start=date(2026, 2, 10),
        end=date(2026, 2, 10),
        retrieved_at=datetime(2026, 2, 11, 9, 0, tzinfo=UTC),
    )

    assert path.fetched_forecast_records == 2
    assert len(path.snapshots) == 1
    snapshot = path.snapshots[0]
    assert snapshot.snapshot_as_of == datetime(2026, 2, 10, 1, 45, tzinfo=UTC)
    assert snapshot.available_at == snapshot.snapshot_as_of
    assert snapshot.availability_quality == "OFFICIAL_EOD_PUBLICATION_SCHEDULE"
    assert len(snapshot.outcomes) == 4
    march_high = next(
        outcome
        for outcome in snapshot.outcomes
        if outcome.meeting_date == date(2026, 3, 18) and outcome.upper_basis_points == 375
    )
    assert march_high.expected_rate == pytest.approx(3.625)

    parsed = PolicyPathBundleRequest.model_validate(cme_fedwatch_bundle(path))
    assert parsed.provider_code == "CME_FEDWATCH_EOD"
    parsed_march_high = next(
        outcome
        for outcome in parsed.snapshots[0].outcomes
        if outcome.meeting_date == date(2026, 3, 18) and outcome.outcome_basis_points == 375
    )
    assert parsed_march_high.expected_rate == pytest.approx(3.625)
    assert (
        parsed_march_high.metadata["outcome_semantics"] == "TARGET_RANGE_UPPER_BOUND_BASIS_POINTS"
    )
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_fedwatch_rejects_invalid_or_unentitled_oauth_credentials() -> None:
    provider = CmeFedWatchProvider(
        client_id="invalid",
        client_secret="invalid",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401,
                json={
                    "error": "invalid_client",
                    "error_description": "Invalid client or client credentials.",
                },
            )
        ),
    )

    with pytest.raises(ValueError, match="rejected the OAuth API ID"):
        await provider.fetch(
            start=date(2026, 2, 10),
            end=date(2026, 2, 10),
        )
