from pathlib import Path

import pytest

from file_monitor.config import (
    GF256_MAX_SHARES,
    MAX_SYMBOL_BYTES,
    AppConfig,
    FecConfig,
    PacingConfig,
    PathsConfig,
    validate_config,
)


def make_config(
    watch_path: Path,
    *,
    rate_limit: int = 1000,
    k: int = 200,
    n: int = 255,
    symbol_bytes: int = 1400,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(watch_path=watch_path, socket_path=watch_path / "run.sock"),
        pacing=PacingConfig(rate_limit=rate_limit),
        fec=FecConfig(k=k, n=n, symbol_bytes=symbol_bytes),
    )


def test_watch_path_is_created_when_missing(tmp_path: Path) -> None:
    watch_path = tmp_path / "does-not-exist-yet"
    cfg = make_config(watch_path)
    validate_config(cfg)
    assert watch_path.is_dir()


def test_watch_path_rejects_non_directory(tmp_path: Path) -> None:
    watch_path = tmp_path / "a-file"
    watch_path.write_text("not a directory")
    cfg = make_config(watch_path)
    with pytest.raises(ValueError, match="paths.watch_path"):
        validate_config(cfg)


def test_rate_limit_must_be_positive(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, rate_limit=0)
    with pytest.raises(ValueError, match="pacing.rate_limit"):
        validate_config(cfg)


def test_fec_fields_must_be_positive(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, k=0)
    with pytest.raises(ValueError, match="fec.k"):
        validate_config(cfg)


def test_fec_n_cannot_exceed_255(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, k=200, n=GF256_MAX_SHARES + 1)
    with pytest.raises(ValueError, match="fec.n"):
        validate_config(cfg)


def test_fec_k_must_be_strictly_less_than_n(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, k=200, n=200)
    with pytest.raises(ValueError, match="fec.k"):
        validate_config(cfg)


def test_fec_symbol_bytes_over_mtu_budget_is_rejected(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, symbol_bytes=MAX_SYMBOL_BYTES + 1)
    with pytest.raises(ValueError, match="fec.symbol_bytes"):
        validate_config(cfg)


def test_fec_symbol_bytes_at_mtu_budget_is_accepted(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, symbol_bytes=MAX_SYMBOL_BYTES)
    validate_config(cfg)
