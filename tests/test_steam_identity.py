from pathlib import Path

from deadlock_build_sync.steam_identity import (
    STEAM_ID64_ACCOUNT_OFFSET,
    local_steam_persona,
)


def test_local_steam_persona_matches_the_cache_account(tmp_path: Path) -> None:
    account_id = 146_293_212
    steam_id64 = STEAM_ID64_ACCOUNT_OFFSET + account_id
    config = tmp_path / "config"
    config.mkdir()
    (config / "loginusers.vdf").write_text(
        f"""\
"users"
{{
    "{steam_id64}"
    {{
        "AccountName" "private-account"
        "PersonaName" "XMLJDX"
    }}
}}
""",
        encoding="utf-8",
    )

    assert local_steam_persona(account_id, roots=(tmp_path,)) == "XMLJDX"
    assert local_steam_persona(account_id + 1, roots=(tmp_path,)) is None


def test_local_steam_persona_unescapes_supported_vdf_characters(
    tmp_path: Path,
) -> None:
    account_id = 123
    steam_id64 = STEAM_ID64_ACCOUNT_OFFSET + account_id
    config = tmp_path / "config"
    config.mkdir()
    (config / "loginusers.vdf").write_text(
        f"""\
"users"
{{
    "{steam_id64}"
    {{
        "PersonaName" "XML\\\"JDX"
    }}
}}
""",
        encoding="utf-8",
    )

    assert local_steam_persona(account_id, roots=(tmp_path,)) == 'XML"JDX'
