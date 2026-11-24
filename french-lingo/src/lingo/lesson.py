from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    id: str
    prompt: str
    answers: tuple[str, ...]
    example: str = ""


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    words: tuple[Word, ...]


@dataclass(frozen=True)
class LanguagePack:
    id: str
    name: str
    lessons: tuple[Lesson, ...]

    def words(self) -> dict[str, Word]:
        return {w.id: w for lesson in self.lessons for w in lesson.words}

    def lesson_of(self) -> dict[str, Lesson]:
        return {w.id: lesson for lesson in self.lessons for w in lesson.words}
