"""Message types. One module per type; importing them registers them.

To add a new type: create a module here, decorate a builder with @register("name"),
import the module below, then add it to config/schedule.yaml. (See README.)
"""

from . import alerts, econ_calendar, funnel, news, sessions, social  # noqa: F401
from .registry import FALLBACKS, KINDS, register, register_fallback  # noqa: F401
