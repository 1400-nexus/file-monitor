import sys
from pathlib import Path

from file_monitor.config import load_config


def main() -> int:
    load_config(Path("config.toml"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
