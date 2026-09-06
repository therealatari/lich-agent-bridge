"""Errors that are safe to map onto the local HTTP interface."""


class LabError(Exception):
    """Base class for expected LAB failures."""


class ValidationError(LabError):
    """The local caller sent malformed or unsupported data."""


class ConfigurationError(LabError):
    """Required local configuration is absent or invalid."""


class ModelError(LabError):
    """The configured model adapter failed to produce an answer."""


class QuestionBusy(LabError):
    """An earlier question still owns the character's inference slot."""


class QuestionCapacity(LabError):
    """All bounded inference slots are occupied."""


class QuestionInvalidated(LabError):
    """Conversation reset or session replacement discarded the answer."""


class QuestionTimeout(LabError):
    """The end-to-end question deadline expired."""
