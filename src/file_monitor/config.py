import os
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from file_monitor.constants import (
    DEFAULT_RATE_CEILING_BPS,
    DEFAULT_RATE_FLOOR_BPS,
    FEC_K_ENV_VAR,
    FEC_K_KEY,
    FEC_N_ENV_VAR,
    FEC_N_KEY,
    FEC_SECTION,
    FEC_SYMBOL_BYTES_ENV_VAR,
    FEC_SYMBOL_BYTES_KEY,
    GF256_MAX_SHARES,
    MAX_SYMBOL_BYTES,
    PACING_SECTION,
    PATHS_SECTION,
    RATE_CEILING_BPS_ENV_VAR,
    RATE_CEILING_BPS_KEY,
    RATE_FLOOR_BPS_ENV_VAR,
    RATE_FLOOR_BPS_KEY,
    SOCKET_PATH_ENV_VAR,
    SOCKET_PATH_KEY,
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
class AppConfig:
    paths: PathsConfig
    pacing: PacingConfig
    fec: FecParams


def _require(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Missing config key: {'/'.join(keys[: keys.index(key) + 1])}")
        current = current[key]
    return current


def load_config(config_path: Path) -> AppConfig:
    with open(config_path, "rb") as file_handle:
        data = tomllib.load(file_handle)

    environment = os.environ
    section_data_by_name = {
        PATHS_SECTION: data.setdefault(PATHS_SECTION, {}),
        PACING_SECTION: data.setdefault(PACING_SECTION, {}),
        FEC_SECTION: data.setdefault(FEC_SECTION, {}),
    }

    for env_var_name, section, key, cast_value in ENV_OVERRIDES:
        if env_var_name in environment:
            section_data_by_name[section][key] = cast_value(environment[env_var_name])

    paths_data = section_data_by_name[PATHS_SECTION]
    pacing_data = section_data_by_name[PACING_SECTION]
    fec_data = section_data_by_name[FEC_SECTION]

    app_config = AppConfig(
        paths=PathsConfig(
            watch_path=Path(_require(paths_data, WATCH_PATH_KEY)),
            socket_path=Path(_require(paths_data, SOCKET_PATH_KEY)),
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
