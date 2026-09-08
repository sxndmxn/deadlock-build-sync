"""Stable JSON conversion for complete output snapshots."""


def json_default(value: object) -> object:
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=repr)
    raise TypeError(f"cannot normalize {type(value).__name__}")
