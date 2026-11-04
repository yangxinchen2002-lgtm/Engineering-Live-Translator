"""Compatibility import; implementation lives in app.web_follow."""
import sys
from app.web_follow import server as _implementation
if __name__ == '__main__':
    _implementation.main()
elif __name__ != '__mp_main__':
    sys.modules[__name__] = _implementation
