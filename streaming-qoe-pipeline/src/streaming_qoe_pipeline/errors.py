"""Custom exceptions."""


class PipelineError(Exception):
    """Base class for pipeline errors."""


class LogCorruptionError(PipelineError):
    """A log segment contains a record that is not a valid envelope."""


class CheckpointError(PipelineError):
    """A checkpoint could not be read or does not match the log it claims to describe."""


class SimulatedCrash(PipelineError):  # noqa: N818 - reads naturally at call sites
    """Raised on purpose by tests and the CLI to prove crash recovery."""
