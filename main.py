"""
Entrypoint. Run with: python main.py

Make sure you've copied .env.example to .env and filled it in first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from trade_relay.app import main  # noqa: E402

if __name__ == "__main__":
    main()
