"""Progress messages of the pipeline stages.

Library code reports progress through the ``mos2.progress`` logger instead of
``print``. Only the command-line entry points call ``configure_cli_logging``,
which writes the messages to standard output, one line each: the Run Analysis
page reads the stage lines (``[fit] ...``, ``[select] ...``, ``[review] ...``)
from there. Without that call (tests, GUI refit) nothing is printed.
"""

from __future__ import annotations

import logging
import sys

PROGRESS_LOGGER_NAME = "mos2.progress"
progress = logging.getLogger(PROGRESS_LOGGER_NAME)


def configure_cli_logging() -> None:
    """Send progress messages to standard output. Call once, at the start of a command-line entry point."""
    if progress.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)  # flushes after every message
    handler.setFormatter(logging.Formatter("%(message)s"))
    progress.addHandler(handler)
    progress.setLevel(logging.INFO)
    progress.propagate = False
