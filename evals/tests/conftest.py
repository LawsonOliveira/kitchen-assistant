import sys
from pathlib import Path

# graders.py and runner.py live in evals/, next to the datasets they read.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
