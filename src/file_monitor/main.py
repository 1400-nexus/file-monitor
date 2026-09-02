import os
import sys
from pathlib import Path

from file_monitor.config import load_config
from file_monitor.constants import DEFAULT_CONFIG_PATH, NEXUS_CONFIG_ENV_VAR


def main() -> int:
    load_config(Path(os.environ.get(NEXUS_CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
