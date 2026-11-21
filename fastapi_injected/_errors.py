class InjectedError(Exception):
    pass


class InvalidMarkerError(InjectedError, TypeError):
    pass


__all__ = [
    "InjectedError",
    "InvalidMarkerError",
]
