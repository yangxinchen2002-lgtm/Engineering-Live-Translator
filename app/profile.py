"""Optional isolated distribution profile; never contains a credential value."""
import os
import re


def profile_id() -> str|None:
    value=os.environ.get('ELT_PROFILE_ID')
    if not value:return None
    if not re.fullmatch(r'portable-[0-9a-f]{32}',value):raise ValueError('invalid ELT distribution profile')
    return value
