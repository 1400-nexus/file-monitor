import os
import sys
from pathlib import Path

from file_monitor.config import load_config

DEFAULT_CONFIG_PATH = "config.toml"


def main() -> int:
    load_config(Path(os.environ.get("NEXUS_CONFIG", DEFAULT_CONFIG_PATH)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
