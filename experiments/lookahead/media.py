"""Compatibility import; implementation lives in app.web_follow."""
import sys
from app.web_follow import media as _implementation
sys.modules[__name__] = _implementation
