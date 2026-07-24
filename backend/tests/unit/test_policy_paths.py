import pytest
from pydantic import ValidationError

from gold_intel.api.schemas import PolicyPathBundleRequest


def test_policy_path_contract_requires_complete_probability_distribution() -> None:
    payload = {
        "provider_code": "MANUAL_POLICY_PATH",
        "is_synthetic": False,
        "snapshots": [
            {
                "snapshot_as_of": "2026-01-10T12:00:00Z",
                "available_at": "2026-01-10T12:00:01Z",
                "outcomes": [
                    {
                        "meeting_date": "2026-03-18",
                        "outcome_basis_points": 400,
                        "probability": 0.6,
                        "source_record_key": "march:400",
                    },
                    {
                        "meeting_date": "2026-03-18",
                        "outcome_basis_points": 425,
                        "probability": 0.3,
                        "source_record_key": "march:425",
                    },
                ],
            }
        ],
    }

    with pytest.raises(ValidationError, match="must sum to 1"):
        PolicyPathBundleRequest.model_validate(payload)


def test_policy_path_contract_accepts_one_distribution_per_meeting() -> None:
    payload = {
        "provider_code": "MANUAL_POLICY_PATH",
        "is_synthetic": True,
        "snapshots": [
            {
                "snapshot_as_of": "2026-01-10T12:00:00Z",
                "available_at": "2026-01-10T12:00:01Z",
                "outcomes": [
                    {
                        "meeting_date": "2026-03-18",
                        "outcome_basis_points": 400,
                        "probability": 0.7,
                        "source_record_key": "march:400",
                    },
                    {
                        "meeting_date": "2026-03-18",
                        "outcome_basis_points": 425,
                        "probability": 0.3,
                        "source_record_key": "march:425",
                    },
                    {
                        "meeting_date": "2026-06-17",
                        "outcome_basis_points": 375,
                        "probability": 1.0,
                        "source_record_key": "june:375",
                    },
                ],
            }
        ],
    }

    parsed = PolicyPathBundleRequest.model_validate(payload)
    assert parsed.snapshots[0].outcomes[0].probability == pytest.approx(0.7)
