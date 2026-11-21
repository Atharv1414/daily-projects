"""Exception hierarchy for the pipeline."""

from __future__ import annotations


class PipelineError(Exception):
    """Base class."""


class ConfigError(PipelineError):
    pass


class SchemaError(PipelineError):
    """A source file does not match any registered schema version."""


class TransientSourceError(PipelineError):
    """A source was temporarily unavailable. The DAG runner retries these."""


class DagError(PipelineError):
    """Invalid DAG definition (cycle, unknown dependency, duplicate task)."""


class TaskFailedError(PipelineError):
    def __init__(self, task: str, attempts: int, cause: BaseException) -> None:
        super().__init__(f"task {task!r} failed after {attempts} attempt(s): {cause}")
        self.task = task
        self.attempts = attempts
        self.cause = cause


class DataQualityError(PipelineError):
    """Too many rows failed quality checks; the batch is rejected rather than half-loaded."""
