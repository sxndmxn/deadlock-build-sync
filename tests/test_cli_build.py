import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deadlock_build_sync import cli, cli_support
from deadlock_build_sync.cli_build import write_build_guides
from deadlock_build_sync.purchase_guide import PurchaseGuide
from deadlock_build_sync.service import generate_guides
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from scripts import generate_narratives
from tests import service_fake_api
from tests.service_evidence_fixtures import (
    make_grouped_build_evidence,
    make_service_build_evidence,
)
from tests.service_fake_api import FakeApi, make_ability_rows, make_duration_statistics


@pytest.mark.parametrize("output_format", ["markdown", "json"])
@pytest.mark.parametrize("existing_evidence", [False, True])
def test_normal_build_generates_full_files_without_steam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
    *,
    existing_evidence: bool,
) -> None:
    class FixedDatetime:
        @staticmethod
        def now(_timezone: object) -> datetime:
            return datetime(2026, 9, 7, tzinfo=UTC)

    monkeypatch.setattr(service_fake_api, "datetime", FixedDatetime)
    monkeypatch.setattr(generate_narratives, "datetime", FixedDatetime)
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    for asset in api._assets:
        if asset["id"] in {102, 104}:
            asset["description"] = "Grants bullet resist."
    evidence = make_grouped_build_evidence(api)
    source = tmp_path.with_name(f"{tmp_path.name}-evidence.json")
    source.write_bytes(evidence.raw_bytes)
    if existing_evidence:
        (tmp_path / "build-evidence.json").write_bytes(b"previous evidence")
    monkeypatch.setattr(
        cli,
        "_current_evidence",
        lambda _args: (source, evidence),
    )

    def create_evidence_api(*_args: object) -> FakeApi:
        source.write_bytes(b"source changed after admission")
        return api

    monkeypatch.setattr(cli_support, "_create_evidence_api", create_evidence_api)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("build accessed Steam")

    monkeypatch.setattr(cli, "_discover_cache_location", forbidden)
    monkeypatch.setattr(cli_support, "install_guides", forbidden)
    monkeypatch.setattr(api, "steam_persona", forbidden)
    result = cli.main([
        "build",
        "--hero",
        "Kelvin",
        "--format",
        output_format,
        "--artifacts",
        str(tmp_path),
        "--build-evidence",
        str(source),
    ])
    assert result == 0
    assert (tmp_path / "build-evidence.json").read_bytes() == evidence.raw_bytes
    assert source.read_bytes() == b"source changed after admission"
    files = {
        str(path.relative_to(tmp_path)): path.read_text().replace(
            str(tmp_path), "<artifacts>"
        )
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name != "build-evidence.json"
    }
    # The complete Steam presentation defines the review artifact contract.
    assert sha256_json(files) == (
        "21068bc5b8bb33736d02fc1619624575267f0593e1c64989b201ea65fda87e74"
    )
    output = capsys.readouterr()
    _assert_build_output(output.out, output_format)
    for filename in (
        "build-evidence.json",
        "strategy-context.json",
        "policies.json",
        "narratives.json",
        "builds.json",
    ):
        assert (tmp_path / filename).is_file()
    index = require_object_dict(json.loads((tmp_path / "builds.json").read_text()))
    directory = Path(str(index["directory"]))
    files = list(directory.glob("*.md"))
    assert len(files) == 3
    text = next(path for path in files if path.name.endswith(".details.md")).read_text()
    assert "Choice details" in text
    bundle = require_object_dict(json.loads((directory / "guides.json").read_text()))
    guide = require_object_rows(bundle["guides"])[0]
    guidance = require_object_dict(guide["purchase_guidance"])
    choices = require_object_rows(guidance["choices"])
    assert len(choices) == 32
    assert all(row["timing"] is not None for row in choices)


def _assert_build_output(output: str, output_format: str) -> None:
    if output_format == "json":
        emitted = require_object_dict(json.loads(output))
        assert (
            require_object_rows(emitted["guides"])[0]["purchase_guidance"] is not None
        )
    else:
        assert "Steam build content." in output
        assert "## TIER 1" in output
        assert "## CORE OPTIONAL" in output
        assert "## TIER 3" in output
        assert "## TIER 4" in output


def test_build_alias_and_reject_missing_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.sys, "argv", ["build", "--hero", "Kelvin"])
    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda args: seen.append(args) or 0)
    assert cli.build_main() == 0
    assert seen == [["build", "--hero", "Kelvin"]]
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    evidence = make_service_build_evidence(api)
    generated = generate_guides(
        api,
        build_evidence=evidence,
        account_id=0,
        hero_query="Kelvin",
        all_heroes=False,
    )
    with pytest.raises(ValueError, match="no purchase guidance"):
        write_build_guides(
            tmp_path, [replace(generated.guides[0], purchase_guidance=None)], generated
        )


@pytest.mark.parametrize("failure", ["render", "replace"])
def test_failed_build_preserves_complete_current_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    generated = generate_guides(
        api,
        build_evidence=make_service_build_evidence(api),
        account_id=0,
        hero_query="Kelvin",
        all_heroes=False,
    )
    artifact = tmp_path / "artifacts"
    artifact.mkdir()
    for name in ("build-evidence.json", "builds.json", "narratives.json", "user-file"):
        (artifact / name).write_text(f"previous {name}")
    previous = {path.name: path.read_bytes() for path in artifact.iterdir()}

    def render(_generated: object, staged: Path) -> list[PurchaseGuide]:
        (staged / "builds.json").write_text("{}")
        (staged / "narratives.json").write_text("new narrative")
        if failure == "render":
            raise cli.NarrativeError("description failed")
        return generated.guides

    rename = Path.rename

    def fail_replace(path: Path, target: Path) -> Path:
        if path.name == "new":
            raise OSError("replacement failed")
        return rename(path, target)

    monkeypatch.setattr(cli, "_render_build_artifacts", render)
    monkeypatch.setattr(Path, "rename", fail_replace)
    with pytest.raises((OSError, cli.NarrativeError), match="failed"):
        cli._write_build_artifacts(
            generated, artifact, make_service_build_evidence(api)
        )
    assert {path.name: path.read_bytes() for path in artifact.iterdir()} == previous
    assert list(tmp_path.iterdir()) == [artifact]
