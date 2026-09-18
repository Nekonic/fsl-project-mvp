import sys
from pathlib import Path

# redteam is a sibling of the repository root. Putting the root on sys.path
# risks shadowing the stdlib `platform` module, but platform/ has no
# __init__.py and we always run with platform/ as the working directory, so
# `import platform` still resolves to the standard library.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
