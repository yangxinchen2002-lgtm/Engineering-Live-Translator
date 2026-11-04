"""User-local temporary speech and non-secret preferences; no writes to app code."""
import os
from pathlib import Path
import tempfile
from app.profile import profile_id


def runtime_root():
    override=os.environ.get('ELT_WEB_RUNTIME_DIR')
    root=Path(override) if override else Path(tempfile.gettempdir())/'ELT-WebFollow'/(profile_id() or 'local')
    root.mkdir(parents=True,exist_ok=True)
    return root


def preferences_path():
    from app.ui.preferences import default_path
    return default_path().with_name('web-follow-options.json')
