"""A DI provider defined in its own module — grounded cross-file (ENH-011)."""


def get_db() -> object:
    return object()
