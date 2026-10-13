"""Configuration from environment variables and an optional TOML file."""
import os
import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: Path = Path("data")
    timezone: str = "UTC"
    session_secret: str = ""
    github_token: str = ""
    fetch_concurrency: int = 4
    fetch_timeout: int = 30
    fetch_max_bytes: int = 5 * 1024 * 1024
    fetch_max_redirects: int = 5
    http_proxy: str = ""
    fetch_allow_hosts: str = ""
    stale_lock_seconds: int = 600

    @property
    def listen(self):
        return f"{self.host}:{self.port}"

    @property
    def db_path(self):
        return Path(self.data_dir) / "driftwatch.db"

    @property
    def base_url(self):
        host = "127.0.0.1" if self.host in ("0.0.0.0", "::", "") else self.host
        return f"http://{host}:{self.port}"


# env var -> (attribute, caster)
_KEYS = {
    "DRIFTWATCH_DATA_DIR": ("data_dir", Path),
    "DRIFTWATCH_TIMEZONE": ("timezone", str),
    "DRIFTWATCH_SESSION_SECRET": ("session_secret", str),
    "DRIFTWATCH_GITHUB_TOKEN": ("github_token", str),
    "DRIFTWATCH_FETCH_CONCURRENCY": ("fetch_concurrency", int),
    "DRIFTWATCH_FETCH_TIMEOUT": ("fetch_timeout", int),
    "DRIFTWATCH_FETCH_MAX_BYTES": ("fetch_max_bytes", int),
    "DRIFTWATCH_FETCH_MAX_REDIRECTS": ("fetch_max_redirects", int),
    "DRIFTWATCH_HTTP_PROXY": ("http_proxy", str),
    "DRIFTWATCH_FETCH_ALLOW_HOSTS": ("fetch_allow_hosts", str),
}


def parse_listen(value: str):
    value = value.strip()
    if value.startswith("["):  # [::1]:8080
        host, _, port = value[1:].partition("]:")
    elif ":" in value:
        host, _, port = value.rpartition(":")
    else:
        host, port = value, "8080"
    try:
        return host or "127.0.0.1", int(port)
    except ValueError:
        raise ConfigError(f"DRIFTWATCH_LISTEN must look like host:port, got {value!r}")


def load(env=None, config_file=None) -> Config:
    env = os.environ if env is None else env
    cfg = Config()
    path = config_file or env.get("DRIFTWATCH_CONFIG") or ("driftwatch.toml" if Path("driftwatch.toml").exists() else None)
    if path:
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read config file {path}: {exc}")
        if "listen" in data:
            cfg.host, cfg.port = parse_listen(str(data.pop("listen")))
        for key, val in data.items():
            if not hasattr(cfg, key):
                raise ConfigError(f"unknown config key {key!r} in {path}")
            setattr(cfg, key, type(getattr(cfg, key))(val))
    if env.get("DRIFTWATCH_LISTEN"):
        cfg.host, cfg.port = parse_listen(env["DRIFTWATCH_LISTEN"])
    for var, (attr, cast) in _KEYS.items():
        if env.get(var):
            try:
                setattr(cfg, attr, cast(env[var]))
            except ValueError:
                raise ConfigError(f"{var} has an invalid value: {env[var]!r}")
    cfg.data_dir = Path(cfg.data_dir)
    return cfg


def prepare_data_dir(cfg: Config):
    """Create the data directory and make sure it is writable; resolve the session secret."""
    d = cfg.data_dir
    try:
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        probe = d / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise ConfigError(f"data directory {d} is not writable: {exc.strerror or exc}")
    if not cfg.session_secret:
        sf = d / "secret.key"
        if sf.exists():
            cfg.session_secret = sf.read_text().strip()
        else:
            cfg.session_secret = secrets.token_hex(32)
            fd = os.open(sf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(cfg.session_secret)
    for sub in ("exports", "fixtures"):
        (d / sub).mkdir(exist_ok=True)
