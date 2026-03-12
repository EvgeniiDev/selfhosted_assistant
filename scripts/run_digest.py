"""
Digest system CLI runner.

Usage:
    python scripts/run_digest.py ingest [days]
    python scripts/run_digest.py digest [topic]
    python scripts/run_digest.py schedule
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from digest.runner import main

if __name__ == "__main__":
    main()
