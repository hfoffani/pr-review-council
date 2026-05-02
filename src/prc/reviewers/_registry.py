from .base import Reviewer

_FAMILIES: dict[str, type[Reviewer]] = {}


def register_family(name: str):
    def deco(cls: type[Reviewer]) -> type[Reviewer]:
        _FAMILIES[name] = cls
        return cls
    return deco
