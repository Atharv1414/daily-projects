from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int
    name: str
    new_per_day: int = 10

    def __post_init__(self) -> None:
        if not 1 <= len(self.name.strip()) <= 40:
            raise ValueError("Name must be 1 to 40 characters.")
        if not 0 <= self.new_per_day <= 100:
            raise ValueError("New words per day must be between 0 and 100.")
