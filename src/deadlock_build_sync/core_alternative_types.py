from dataclasses import dataclass


@dataclass(frozen=True)
class CoreAlternativeDescription:
    vs: str
    why: str
    swap: str
    when: str
    skip: str
    mechanics_refs: tuple[str, ...]
    comparator_mechanics_refs: tuple[str, ...]
