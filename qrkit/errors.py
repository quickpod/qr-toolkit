"""Error types for qrkit."""


class QRKitError(Exception):
    """Raised for any recoverable failure in a qrkit operation.

    Every public function raises this (and only this) on failure, so callers --
    the CLI and the GUI -- have a single exception type to catch and can surface
    a clean message instead of a raw traceback.
    """
