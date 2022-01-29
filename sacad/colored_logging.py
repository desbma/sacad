""" Formatter for the logging module, coloring terminal output according to error criticity. """

import enum
import logging
import sys

Colors = enum.Enum("Colors", ("RED", "GREEN", "YELLOW", "BLUE"))

LEVEL_COLOR_MAPPING = {logging.WARNING: Colors.YELLOW, logging.ERROR: Colors.RED, logging.CRITICAL: Colors.RED}
LEVEL_BOLD_MAPPING = {logging.WARNING: False, logging.ERROR: False, logging.CRITICAL: True}


class ColoredFormatter(logging.Formatter):

    """Logging formatter coloring terminal output according to error criticity."""

    def format(self, record):
        """See logging.Formatter.format."""
        message = super().format(record)
        if sys.stderr.isatty() and not sys.platform.startswith("win32"):
            try:
                color_code = LEVEL_COLOR_MAPPING[record.levelno].value
                bold = LEVEL_BOLD_MAPPING[record.levelno]
            except KeyError:
                pass
            else:
                message = f"\033[{bold:d};{30 + color_code}m{message}\033[0m"
        return message
