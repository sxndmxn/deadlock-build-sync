import math

import pytest

from deadlock_build_sync import build_evidence_item, build_evidence_values
from deadlock_build_sync.artifacts import ArtifactError
from tests.build_evidence_fixtures import _document, _first_item


def _valid_item() -> dict[str, object]:
    return dict(_first_item(_document()))


def _validate_scalar(call: str, value: object) -> None:
    if call == "int":
        build_evidence_values._required_int(value, "value")
    elif call == "int_max":
        build_evidence_values._required_int(value, "value", maximum=1)
    elif call == "float":
        build_evidence_values._required_float(value, "value")
    elif call == "float_max":
        build_evidence_values._required_float(value, "value", maximum=1.0)
    elif call == "finite":
        build_evidence_values._finite_float(value, "value")
    elif call == "bool":
        build_evidence_values._required_bool(value, "value")
    else:
        build_evidence_values._required_sha256(value, "value")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"item": ""}, "lacks identity"),
        ({"slot": 7}, "lacks identity"),
        ({"tier": 5}, "invalid tier"),
        ({"adopter_matches": 1_001}, "impossible counts"),
        ({"purchase_events": 1}, "impossible counts"),
        ({"wins": 1_000}, "impossible counts"),
        ({"adoption": 0.5}, "adoption is inconsistent"),
        ({"observed_outcome_rate": 0.9}, "outcome is inconsistent"),
        ({"median_valid_buy_net_worth": None}, "invalid net-worth quantiles"),
        ({"buy_net_worth_q25": 2_000.0}, "invalid net-worth quantiles"),
        ({"training_adopter_matches": 601}, "invalid fold counts"),
        ({"training_adoption": 0.9}, "invalid fold counts"),
        ({"selection_adopter_matches": 1}, "inconsistent selection counts"),
        ({"selection_eligible_player_matches": 799}, "selection counts"),
        ({"selection_adoption": 0.9}, "selection counts"),
        ({"selection_median_buy_time_s": None}, "invalid selection timing"),
        ({"selection_valid_buy_net_worth_observations": 801}, "selection timing"),
        ({"selection_valid_buy_net_worth_share": 0.2}, "selection timing"),
        ({"selection_median_valid_buy_net_worth": None}, "selection timing"),
        ({"selection_buy_net_worth_q25": 2_000.0}, "selection timing"),
        ({"training_valid_buy_net_worth_observations": 601}, "training window"),
        ({"training_buy_net_worth_q25": None}, "training window"),
        ({"training_buy_net_worth_q75": None}, "training window"),
        ({"training_buy_net_worth_q25": 2_000.0}, "training window"),
        ({"validation_valid_buy_net_worth_observations": 0}, "validation window"),
        ({"imbue_target_ability": "Ghost"}, "invalid imbue"),
        ({"imbue_target_matches": 1}, "invalid imbue"),
        ({"imbue_observations": 1}, "invalid imbue"),
        ({"imbue_target_share": 0.1}, "invalid imbue"),
    ],
)
def test_item_parser_rejects_inconsistent_evidence(
    changes: dict[str, object],
    message: str,
) -> None:
    row = _valid_item()
    row.update(changes)

    with pytest.raises(ArtifactError, match=message):
        build_evidence_item._item(row, 13)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"imbue_target_ability": None}, "invalid imbue"),
        ({"imbue_target_matches": 101}, "invalid imbue"),
        ({"imbue_target_matches": 19}, "invalid imbue"),
        ({"imbue_target_share": 0.5}, "invalid imbue"),
        ({"imbue_target_share": 0.9}, "invalid imbue"),
    ],
)
def test_item_parser_rejects_bad_supported_imbue_values(
    changes: dict[str, object],
    message: str,
) -> None:
    row = _valid_item()
    row.update({
        "imbue_target_ability_id": 40,
        "imbue_target_ability": "Ability",
        "imbue_target_matches": 75,
        "imbue_observations": 100,
        "imbue_target_share": 0.75,
    })
    row.update(changes)

    with pytest.raises(ArtifactError, match=message):
        build_evidence_item._item(row, 13)


def test_item_parser_accepts_a_zero_test_fold() -> None:
    row = _valid_item()
    row.update({
        "adopter_matches": row["selection_adopter_matches"],
        "eligible_player_matches": row["selection_eligible_player_matches"],
        "wins": 79,
        "observed_outcome_rate": 79 / 159,
        "adoption": 159 / 800,
        "test_adopter_matches": 0,
        "test_eligible_player_matches": 0,
        "test_adoption": 0.0,
    })

    parsed = build_evidence_item._item(row, 13)

    assert parsed.test_eligible_player_matches == 0


@pytest.mark.parametrize(
    ("call", "value"),
    [
        ("int", True),
        ("int", -1),
        ("int_max", 2),
        ("float", "1"),
        ("float", True),
        ("float", math.inf),
        ("float", -1.0),
        ("float_max", 2.0),
        ("finite", "1"),
        ("finite", True),
        ("finite", math.nan),
        ("bool", 1),
        ("sha", 7),
        ("sha", "a" * 63),
        ("sha", "g" * 64),
    ],
)
def test_scalar_evidence_validators_reject_bad_domains(
    call: str, value: object
) -> None:
    with pytest.raises(ArtifactError):
        _validate_scalar(call, value)


def test_optional_float_and_document_accept_their_valid_edges() -> None:
    assert build_evidence_values._optional_float(None, "value") is None
    assert build_evidence_values._document({}, "bad") == {}
    with pytest.raises(ArtifactError, match="bad"):
        build_evidence_values._document([], "bad")
