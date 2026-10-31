"""Best-effort versioned completion in user-local application data."""

import json
import os
import sys
import tempfile
from pathlib import Path

TUTORIAL_VERSION = 3


def default_progress_path() -> Path:
    if sys.platform == 'darwin':
        directory = Path.home() / 'Library' / 'Application Support' / 'TankTroubleReconstruction'
    elif sys.platform == 'win32':
        directory = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        directory /= 'TankTroubleReconstruction'
    else:
        directory = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
        if not directory.is_absolute():
            directory = Path.home() / '.local' / 'share'
        directory /= 'tank-trouble-reconstruction'
    return directory / 'tutorial-progress.json'


def load_completed(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return (type(data) is dict and type(data.get('tutorial_version')) is int
                and data['tutorial_version'] == TUTORIAL_VERSION and data.get('completed') is True)
    except (OSError, UnicodeError, ValueError):
        return False


def save_completed(path: Path) -> bool:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.tutorial-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'tutorial_version': TUTORIAL_VERSION, 'completed': True}, stream)
            stream.write('\n')
        os.replace(temporary, path)
        return True
    except (OSError, UnicodeError, ValueError):
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
