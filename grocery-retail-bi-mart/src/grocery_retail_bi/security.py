"""Row-level security (RLS) simulation.

Each user has a role and a scope. The semantic layer adds the user's predicate to *every*
query, against the store's **current** dimension row. A regional manager therefore sees the
full history of the stores they manage today, including sales made before the 2026 region
realignment, which is what managers expect when they inherit stores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    EXECUTIVE = "executive"
    REGIONAL = "regional_manager"
    STORE = "store_manager"


class AccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class User:
    username: str
    role: Role
    regions: tuple[str, ...] = field(default_factory=tuple)
    stores: tuple[str, ...] = field(default_factory=tuple)

    def predicate(self, alias: str = "sc") -> tuple[str, list[str]]:
        """SQL predicate plus bind parameters restricting rows to this user's scope."""
        if self.role is Role.EXECUTIVE:
            return "TRUE", []
        if self.role is Role.REGIONAL:
            if not self.regions:
                raise AccessDenied(f"{self.username} has no regions assigned")
            marks = ", ".join("?" for _ in self.regions)
            return f"{alias}.region IN ({marks})", list(self.regions)
        if not self.stores:
            raise AccessDenied(f"{self.username} has no stores assigned")
        marks = ", ".join("?" for _ in self.stores)
        return f"{alias}.store_code IN ({marks})", list(self.stores)


USERS: dict[str, User] = {
    "ceo": User("ceo", Role.EXECUTIVE),
    "finance": User("finance", Role.EXECUTIVE),
    "rm_north_west": User("rm_north_west", Role.REGIONAL, regions=("North West",)),
    "rm_north": User("rm_north", Role.REGIONAL, regions=("North",)),
    "rm_london_se": User("rm_london_se", Role.REGIONAL, regions=("London", "South East")),
    "sm_s105": User("sm_s105", Role.STORE, stores=("S105",)),
    "nobody": User("nobody", Role.REGIONAL),
}


def get_user(username: str) -> User:
    try:
        return USERS[username]
    except KeyError as exc:
        raise AccessDenied(f"unknown user {username!r}") from exc
