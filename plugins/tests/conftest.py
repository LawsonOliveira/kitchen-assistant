import sys
from pathlib import Path

# Plugins are imported by package name (e.g. `sabor_a2a.client`), as Hermes does from $HERMES_HOME/plugins.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
