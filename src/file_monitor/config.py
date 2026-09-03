import os
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from file_monitor.constants import (
    BASE_PORT_ENV_VAR,
    BASE_PORT_KEY,
    BINARY_PATH_ENV_VAR,
    BINARY_PATH_KEY,
    DEFAULT_BASE_PORT,
    DEFAULT_RATE_CEILING_BPS,
    DEFAULT_RATE_FLOOR_BPS,
    DEFAULT_SENDER_BINARY_PATH,
    DEFAULT_SENDER_COUNT,
    DEFAULT_TARGET_HOST,
    FEC_K_ENV_VAR,
    FEC_K_KEY,
    FEC_N_ENV_VAR,
    FEC_N_KEY,
    FEC_SECTION,
    FEC_SYMBOL_BYTES_ENV_VAR,
    FEC_SYMBOL_BYTES_KEY,
    GF256_MAX_SHARES,
    MAX_PORT,
    MAX_SYMBOL_BYTES,
    MIN_PORT,
    PACING_SECTION,
    PATHS_SECTION,
    RATE_CEILING_BPS_ENV_VAR,
    RATE_CEILING_BPS_KEY,
    RATE_FLOOR_BPS_ENV_VAR,
    RATE_FLOOR_BPS_KEY,
    SENDER_COUNT_ENV_VAR,
    SENDER_COUNT_KEY,
    SENDERS_SECTION,
    SOCKET_PATH_ENV_VAR,
    SOCKET_PATH_KEY,
    TARGET_HOST_ENV_VAR,
    TARGET_HOST_KEY,
    WATCH_PATH_ENV_VAR,
    WATCH_PATH_KEY,
)
from file_monitor.domain.models import FecParams

ENV_OVERRIDES: tuple[tuple[str, str, str, Callable[[str], Any]], ...] = (
    (WATCH_PATH_ENV_VAR, PATHS_SECTION, WATCH_PATH_KEY, str),
    (SOCKET_PATH_ENV_VAR, PATHS_SECTION, SOCKET_PATH_KEY, str),
    (RATE_CEILING_BPS_ENV_VAR, PACING_SECTION, RATE_CEILING_BPS_KEY, int),
    (RATE_FLOOR_BPS_ENV_VAR, PACING_SECTION, RATE_FLOOR_BPS_KEY, int),
    (FEC_K_ENV_VAR, FEC_SECTION, FEC_K_KEY, int),
    (FEC_N_ENV_VAR, FEC_SECTION, FEC_N_KEY, int),
    (FEC_SYMBOL_BYTES_ENV_VAR, FEC_SECTION, FEC_SYMBOL_BYTES_KEY, int),
    (TARGET_HOST_ENV_VAR, SENDERS_SECTION, TARGET_HOST_KEY, str),
    (BASE_PORT_ENV_VAR, SENDERS_SECTION, BASE_PORT_KEY, int),
    (BINARY_PATH_ENV_VAR, SENDERS_SECTION, BINARY_PATH_KEY, str),
    (SENDER_COUNT_ENV_VAR, SENDERS_SECTION, SENDER_COUNT_KEY, int),
)


@dataclass(frozen=True)
class PathsConfig:
    watch_path: Path
    socket_path: Path


@dataclass(frozen=True)
class PacingConfig:
    rate_ceiling_bps: int
    rate_floor_bps: int


@dataclass(frozen=True)
class SendersConfig:
    target_host: str
    base_port: int
    binary_path: str
    sender_count: int


@dataclass(frozen=True)
class AppConfig:
    paths: PathsConfig
    pacing: PacingConfig
    fec: FecParams
    senders: SendersConfig


def _require(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Missing config key: {'/'.join(keys[: keys.index(key) + 1])}")
        current = current[key]
    return current


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def load_config(config_path: Path) -> AppConfig:
    with open(config_path, "rb") as file_handle:
        data = tomllib.load(file_handle)

    # Not the process CWD: behaviour shouldn't depend on launch directory.
    config_dir = config_path.resolve().parent

    environment = os.environ
    section_data_by_name = {
        PATHS_SECTION: data.setdefault(PATHS_SECTION, {}),
        PACING_SECTION: data.setdefault(PACING_SECTION, {}),
        FEC_SECTION: data.setdefault(FEC_SECTION, {}),
        SENDERS_SECTION: data.setdefault(SENDERS_SECTION, {}),
    }

    for env_var_name, section, key, cast_value in ENV_OVERRIDES:
        if env_var_name in environment:
            section_data_by_name[section][key] = cast_value(environment[env_var_name])

    paths_data = section_data_by_name[PATHS_SECTION]
    pacing_data = section_data_by_name[PACING_SECTION]
    fec_data = section_data_by_name[FEC_SECTION]
    senders_data = section_data_by_name[SENDERS_SECTION]

    app_config = AppConfig(
        paths=PathsConfig(
            watch_path=_resolve_path(config_dir, str(_require(paths_data, WATCH_PATH_KEY))),
            socket_path=_resolve_path(config_dir, str(_require(paths_data, SOCKET_PATH_KEY))),
        ),
        pacing=PacingConfig(
            rate_ceiling_bps=int(pacing_data.get(RATE_CEILING_BPS_KEY, DEFAULT_RATE_CEILING_BPS)),
            rate_floor_bps=int(pacing_data.get(RATE_FLOOR_BPS_KEY, DEFAULT_RATE_FLOOR_BPS)),
        ),
        fec=FecParams(
            k=int(_require(fec_data, FEC_K_KEY)),
            n=int(_require(fec_data, FEC_N_KEY)),
            symbol_bytes=int(_require(fec_data, FEC_SYMBOL_BYTES_KEY)),
        ),
        senders=SendersConfig(
            target_host=str(senders_data.get(TARGET_HOST_KEY, DEFAULT_TARGET_HOST)),
            base_port=int(senders_data.get(BASE_PORT_KEY, DEFAULT_BASE_PORT)),
            binary_path=str(
                _resolve_path(
                    config_dir, str(senders_data.get(BINARY_PATH_KEY, DEFAULT_SENDER_BINARY_PATH))
                )
            ),
            sender_count=int(senders_data.get(SENDER_COUNT_KEY, DEFAULT_SENDER_COUNT)),
        ),
    )

    validate_config(app_config)
    return app_config


def validate_config(app_config: AppConfig) -> None:
    if app_config.paths.watch_path.is_dir():
        pass
    elif app_config.paths.watch_path.exists():
        raise ValueError(f"paths.watch_path is not a directory: {app_config.paths.watch_path}")
    else:
        app_config.paths.watch_path.mkdir(parents=True, exist_ok=True)

    if app_config.pacing.rate_floor_bps <= 0:
        raise ValueError("pacing.rate_floor_bps must be > 0")

    if app_config.pacing.rate_ceiling_bps < app_config.pacing.rate_floor_bps:
        raise ValueError(
            f"pacing.rate_ceiling_bps ({app_config.pacing.rate_ceiling_bps}) must be >= "
            f"pacing.rate_floor_bps ({app_config.pacing.rate_floor_bps})"
        )

    if app_config.fec.k <= 0 or app_config.fec.n <= 0 or app_config.fec.symbol_bytes <= 0:
        raise ValueError("fec.k, fec.n, and fec.symbol_bytes must all be > 0")

    if app_config.fec.n > GF256_MAX_SHARES:
        raise ValueError(
            f"fec.n ({app_config.fec.n}) cannot exceed {GF256_MAX_SHARES} (GF(2^8) limit)"
        )

    if app_config.fec.k >= app_config.fec.n:
        raise ValueError(f"fec.k ({app_config.fec.k}) must be less than fec.n ({app_config.fec.n})")

    if app_config.fec.symbol_bytes > MAX_SYMBOL_BYTES:
        raise ValueError(
            f"fec.symbol_bytes ({app_config.fec.symbol_bytes}) exceeds MTU budget "
            f"({MAX_SYMBOL_BYTES})"
        )

    if not app_config.senders.binary_path:
        raise ValueError("senders.binary_path must not be empty")

    if app_config.senders.sender_count < 0:
        raise ValueError(
            f"senders.sender_count must be >= 0, got {app_config.senders.sender_count}"
        )

    if not (MIN_PORT <= app_config.senders.base_port <= MAX_PORT):
        raise ValueError(
            f"senders.base_port must be in [{MIN_PORT}, {MAX_PORT}], "
            f"got {app_config.senders.base_port}"
        )
