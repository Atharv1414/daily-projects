"""Exception hierarchy.

Every error raised deliberately by the package derives from ``ExpenseTrackerError`` so the
CLI can turn it into a clean message and a non-zero exit code instead of a traceback.
"""


class ExpenseTrackerError(Exception):
    """Base class for all expected, user-facing errors."""

    exit_code = 1


class ValidationError(ExpenseTrackerError, ValueError):
    """Input failed validation (bad amount, unknown category, malformed date...)."""

    exit_code = 2


class NotFoundError(ExpenseTrackerError, LookupError):
    """A requested record does not exist."""

    exit_code = 3


class ImportFormatError(ExpenseTrackerError):
    """A bank statement file could not be understood (e.g. missing required columns)."""

    exit_code = 4


class MigrationError(ExpenseTrackerError):
    """The database schema is newer than this version of the tool understands."""

    exit_code = 5
