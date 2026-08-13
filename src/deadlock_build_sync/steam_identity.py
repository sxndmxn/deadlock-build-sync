from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .cache import steam_roots

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

STEAM_ID64_ACCOUNT_OFFSET = 76_561_197_960_265_728


def _persona_from_loginusers(path: Path, account_id: int) -> str | None:
    try:
        document = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    steam_id64 = STEAM_ID64_ACCOUNT_OFFSET + account_id
    user_match = re.search(
        rf'"{steam_id64}"\s*\{{(?P<body>.*?)^\s*\}}',
        document,
        flags=re.DOTALL | re.MULTILINE,
    )
    if user_match is None:
        return None
    persona_match = re.search(
        r'"PersonaName"\s*"(?P<persona>(?:\\.|[^"\\])*)"',
        user_match.group("body"),
    )
    if persona_match is None:
        return None
    persona = re.sub(r'\\(["\\])', r"\1", persona_match.group("persona")).strip()
    return persona or None


def local_steam_persona(
    account_id: int, *, roots: Iterable[Path] | None = None
) -> str | None:
    """Resolve an account's current persona from Steam's local login registry.

    Returns:
        The matching non-empty persona name, or ``None`` when it cannot be resolved.

    """
    candidates = tuple(roots) if roots is not None else steam_roots()
    visited: set[Path] = set()
    for root in candidates:
        loginusers = root.expanduser() / "config/loginusers.vdf"
        identity = loginusers.resolve(strict=False)
        if identity in visited:
            continue
        visited.add(identity)
        persona = _persona_from_loginusers(loginusers, account_id)
        if persona is not None:
            return persona
    return None
