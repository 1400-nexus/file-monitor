from pathlib import Path

import pytest

from file_monitor.config import (
    AppConfig,
    PacingConfig,
    PathsConfig,
    SendersConfig,
    load_config,
    validate_config,
)
from file_monitor.constants import (
    DEFAULT_BASE_PORT,
    DEFAULT_RATE_CEILING_BPS,
    DEFAULT_RATE_FLOOR_BPS,
    DEFAULT_SENDER_BINARY_PATH,
    DEFAULT_SENDER_COUNT,
    DEFAULT_TARGET_HOST,
    GF256_MAX_SHARES,
    MAX_SYMBOL_BYTES,
    WATCH_PATH_ENV_VAR,
)
from file_monitor.domain.models import FecParams

MINIMAL_CONFIG_TOML = """
[paths]
watch_path = "./watch"
socket_path = "./run/file-monitor.sock"

[fec]
k = 1
n = 2
symbol_bytes = 1
"""


def make_config(
    watch_path: Path,
    *,
    rate_ceiling_bps: int = DEFAULT_RATE_CEILING_BPS,
    rate_floor_bps: int = DEFAULT_RATE_FLOOR_BPS,
    k: int = 200,
    n: int = 255,
    symbol_bytes: int = 1400,
    target_host: str = DEFAULT_TARGET_HOST,
    base_port: int = DEFAULT_BASE_PORT,
    binary_path: str = DEFAULT_SENDER_BINARY_PATH,
    sender_count: int = DEFAULT_SENDER_COUNT,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(watch_path=watch_path, socket_path=watch_path / "run.sock"),
        pacing=PacingConfig(rate_ceiling_bps=rate_ceiling_bps, rate_floor_bps=rate_floor_bps),
        fec=FecParams(k=k, n=n, symbol_bytes=symbol_bytes),
        senders=SendersConfig(
            target_host=target_host,
            base_port=base_port,
            binary_path=binary_path,
            sender_count=sender_count,
        ),
    )


def test_watch_path_is_created_when_missing(tmp_path: Path) -> None:
    watch_path = tmp_path / "does-not-exist-yet"
    app_config = make_config(watch_path)
    validate_config(app_config)
    assert watch_path.is_dir()


def test_watch_path_rejects_non_directory(tmp_path: Path) -> None:
    watch_path = tmp_path / "a-file"
    watch_path.write_text("not a directory")
    app_config = make_config(watch_path)
    with pytest.raises(ValueError, match="paths.watch_path"):
        validate_config(app_config)


def test_rate_floor_must_be_positive(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, rate_floor_bps=0)
    with pytest.raises(ValueError, match="pacing.rate_floor_bps"):
        validate_config(app_config)


def test_rate_ceiling_must_be_at_least_floor(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, rate_ceiling_bps=1_000_000, rate_floor_bps=5_000_000)
    with pytest.raises(ValueError, match="pacing.rate_ceiling_bps"):
        validate_config(app_config)


def test_fec_fields_must_be_positive(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, k=0)
    with pytest.raises(ValueError, match="fec.k"):
        validate_config(app_config)


def test_fec_n_cannot_exceed_255(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, k=200, n=GF256_MAX_SHARES + 1)
    with pytest.raises(ValueError, match="fec.n"):
        validate_config(app_config)


def test_fec_k_must_be_strictly_less_than_n(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, k=200, n=200)
    with pytest.raises(ValueError, match="fec.k"):
        validate_config(app_config)


def test_fec_symbol_bytes_over_mtu_budget_is_rejected(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, symbol_bytes=MAX_SYMBOL_BYTES + 1)
    with pytest.raises(ValueError, match="fec.symbol_bytes"):
        validate_config(app_config)


def test_fec_symbol_bytes_at_mtu_budget_is_accepted(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, symbol_bytes=MAX_SYMBOL_BYTES)
    validate_config(app_config)


def test_senders_binary_path_must_not_be_empty(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, binary_path="")
    with pytest.raises(ValueError, match="senders.binary_path"):
        validate_config(app_config)


def test_senders_sender_count_cannot_be_negative(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, sender_count=-1)
    with pytest.raises(ValueError, match="senders.sender_count"):
        validate_config(app_config)


def test_senders_sender_count_of_zero_is_accepted(tmp_path: Path) -> None:
    # Means "supervise nothing" -- the sender binary lives in a different
    # repo and won't exist in the file-monitor image.
    validate_config(make_config(tmp_path, sender_count=0))


def test_senders_base_port_below_range_is_rejected(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, base_port=0)
    with pytest.raises(ValueError, match="senders.base_port"):
        validate_config(app_config)


def test_senders_base_port_above_range_is_rejected(tmp_path: Path) -> None:
    app_config = make_config(tmp_path, base_port=65536)
    with pytest.raises(ValueError, match="senders.base_port"):
        validate_config(app_config)


def test_senders_base_port_at_range_edges_is_accepted(tmp_path: Path) -> None:
    validate_config(make_config(tmp_path, base_port=1))
    validate_config(make_config(tmp_path / "other", base_port=65535))


def test_load_config_resolves_relative_paths_against_config_file_directory(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "etc"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    config_path.write_text(MINIMAL_CONFIG_TOML)

    app_config = load_config(config_path)

    assert app_config.paths.watch_path == config_dir / "watch"
    assert app_config.paths.socket_path == config_dir / "run" / "file-monitor.sock"
    assert Path(app_config.senders.binary_path) == config_dir / "bin" / "nexus-sender"


def test_load_config_leaves_absolute_paths_untouched(tmp_path: Path) -> None:
    config_dir = tmp_path / "etc"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    absolute_watch = tmp_path / "var" / "nexus" / "watch"
    config_path.write_text(f"""
[paths]
watch_path = "{absolute_watch.as_posix()}"
socket_path = "./run/file-monitor.sock"

[fec]
k = 1
n = 2
symbol_bytes = 1
""")

    app_config = load_config(config_path)

    assert app_config.paths.watch_path == absolute_watch


def test_load_config_resolves_a_relative_env_override_against_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "etc"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    config_path.write_text(MINIMAL_CONFIG_TOML)
    monkeypatch.setenv(WATCH_PATH_ENV_VAR, "./overridden-watch")

    app_config = load_config(config_path)

    assert app_config.paths.watch_path == config_dir / "overridden-watch"
