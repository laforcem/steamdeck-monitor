import logging

__version__ = "0.1.0"

# Library convention: stay silent unless the entry point configures logging.
logging.getLogger("steamdeck-monitor").addHandler(logging.NullHandler())
