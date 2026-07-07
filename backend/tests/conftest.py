import sys
from pathlib import Path

# Ensure the backend package root (…/backend) is importable as `app.*` no matter
# where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
