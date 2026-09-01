import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PathsConfig:
    watch_path: Path
    socket_path: Path

@dataclass(frozen=True)
class PacingConfig:
    rate_limit: int

@dataclass(frozen=True)
class FecConfig:
    k: int
    n: int
    symbol_bytes: int

@dataclass(frozen=True)
class AppConfig:
    paths: PathsConfig
    pacing: PacingConfig
    fec: FecConfig

def _require(mapping: dict, *keys: str):
    current = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Missing config key: {'/'.join(keys[: keys.index(key)+1])}")
        current = current[key]
    return current

def load_config(config_path: Path) -> AppConfig:
    with open(config_path, "rb") as fh:
        data = tomllib.load(fh)

    env = os.environ

    paths_data = data.setdefault("paths", {})
    pacing_data = data.setdefault("pacing", {})
    fec_data = data.setdefault("fec", {})

    if "WATCH_PATH" in env:
        paths_data["watch_path"] = env["WATCH_PATH"]
    if "SOCKET_PATH" in env:
        paths_data["socket_path"] = env["SOCKET_PATH"]
    if "RATE_LIMIT" in env:
        pacing_data["rate_limit"] = int(env["RATE_LIMIT"])
    if "FEC_K" in env:
        fec_data["k"] = int(env["FEC_K"])
    if "FEC_N" in env:
        fec_data["n"] = int(env["FEC_N"])
    if "FEC_SYMBOL_BYTES" in env:
        fec_data["symbol_bytes"] = int(env["FEC_SYMBOL_BYTES"])

    cfg = AppConfig(
        paths=PathsConfig(
            watch_path=Path(_require(paths_data, "watch_path")),
            socket_path=Path(_require(paths_data, "socket_path")),
        ),
        pacing=PacingConfig(rate_limit=int(_require(pacing_data, "rate_limit"))),
        fec=FecConfig(
            k=int(_require(fec_data, "k")),
            n=int(_require(fec_data, "n")),
            symbol_bytes=int(_require(fec_data, "symbol_bytes")),
        ),
    )

    validate_config(cfg)
    return cfg

def validate_config(cfg: AppConfig) -> None:
    if not cfg.paths.watch_path.exists():
        raise ValueError(f"Watch path does not exist: {cfg.paths.watch_path}")
    if not cfg.paths.watch_path.is_dir():
        raise ValueError(f"Watch path is not a directory: {cfg.paths.watch_path}")

    if cfg.pacing.rate_limit <= 0:
        raise ValueError("pacing.rate_limit must be > 0")

    if cfg.fec.k <= 0 or cfg.fec.n <= 0 or cfg.fec.symbol_bytes <= 0:
        raise ValueError("fec.k, fec.n, and fec.symbol_bytes must all be > 0")

    if cfg.fec.k > cfg.fec.n:
        raise ValueError("fec.k cannot be greater than fec.n")

    mtu = 1500
    if cfg.fec.symbol_bytes > mtu:
        raise ValueError(
            f"fec.symbol_bytes ({cfg.fec.symbol_bytes}) exceeds MTU budget ({mtu})"
        )