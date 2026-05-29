from pathlib import Path
from focusflow.main import main
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))


if __name__ == "__main__":
    raise SystemExit(main())
