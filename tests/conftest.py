import sys
from pathlib import Path

# enrich.py/merge_gdrive.py live at the repo root, not inside tests/ or a package -
# put the root on sys.path so `import enrich` works regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
