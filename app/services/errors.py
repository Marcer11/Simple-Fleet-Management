class ValidationError(ValueError):
    """Neplatná vstupní data (zobrazí se uživateli ve formuláři)."""

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or [message]


class NotFoundError(LookupError):
    """Záznam neexistuje (nebo k němu uživatel nemá přístup)."""


class PermissionDeniedError(PermissionError):
    """Uživatel nemá k akci dostatečná práva."""
