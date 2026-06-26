"""
core.config — Configuration management for Stock JSON Clipper V2.1.
Reads/writes config.ini using configparser.
Creates default config.ini next to the executable (or project root in dev).
"""

import os
import sys
import configparser
from typing import Any, Dict

# --- Default configuration ---
DEFAULTS: Dict[str, Any] = {
    "output_format": "json",
    "default_count": 250,
    "poll_interval": 0.5,
    "cache_ttl": 300,
    "request_timeout": 5,
    "save_directory": "",
}


def _get_config_dir() -> str:
    """Get the directory where config.ini should live.

    PyInstaller (frozen): next to the .exe
    Dev mode: project root (parent of core/ directory)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        # core/config.py → core/ → project root
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CONFIG_PATH = os.path.join(_get_config_dir(), "config.ini")


def load_config(config_path: str = CONFIG_PATH) -> Dict[str, Any]:
    """Load configuration from INI file, creating it with defaults if missing.

    Args:
        config_path: Path to config.ini file.

    Returns:
        Dict with merged config values (defaults overridden by file values).
    """
    cfg = dict(DEFAULTS)
    parser = configparser.ConfigParser()

    if os.path.exists(config_path):
        parser.read(config_path, encoding="utf-8")
        if parser.has_section("settings"):
            for key in cfg:
                if parser.has_option("settings", key):
                    raw = parser.get("settings", key)
                    # Type-cast based on default type
                    if isinstance(cfg[key], int):
                        cfg[key] = int(raw)
                    elif isinstance(cfg[key], float):
                        cfg[key] = float(raw)
                    else:
                        cfg[key] = raw
    else:
        # Create default config.ini
        save_config(cfg, config_path)

    return cfg


def save_config(cfg: Dict[str, Any], config_path: str = CONFIG_PATH) -> None:
    """Save configuration to INI file.

    Args:
        cfg: Config dict to save.
        config_path: Path to config.ini file.
    """
    # Ensure directory exists (esp. for frozen bundles)
    cfg_dir = os.path.dirname(config_path)
    if cfg_dir:
        os.makedirs(cfg_dir, exist_ok=True)

    parser = configparser.ConfigParser()
    parser.add_section("settings")
    for key, value in cfg.items():
        parser.set("settings", key, str(value))

    with open(config_path, "w", encoding="utf-8") as f:
        parser.write(f)


def update_config(key: str, value: Any, config_path: str = CONFIG_PATH) -> None:
    """Update a single configuration key and persist to file.

    Args:
        key: Config key name.
        value: New value.
        config_path: Path to config.ini file.
    """
    cfg = load_config(config_path)
    cfg[key] = value
    save_config(cfg, config_path)


# ============================================================
# Alert config — CRUD functions for price alert system
# ============================================================

import threading  # noqa: E402

_file_lock = threading.Lock()  # Protects alert config file writes


def get_alerts_config(config_path: str = CONFIG_PATH) -> dict:
    """Read the [alerts] master section.

    Returns dict with keys: enabled (bool), poll_interval (int),
    buffer_pct (float), max_alerts (int). Defaults if section missing.
    """
    parser = configparser.ConfigParser()
    defaults = {"enabled": True, "poll_interval": 5, "buffer_pct": 2.0, "max_alerts": 10}
    try:
        parser.read(config_path, encoding="utf-8")
    except Exception:
        return defaults
    if not parser.has_section("alerts"):
        return defaults
    result = {}
    for key, default in defaults.items():
        try:
            if parser.has_option("alerts", key):
                raw = parser.get("alerts", key)
                if isinstance(default, bool):
                    result[key] = raw.lower() in ("true", "1", "yes")
                elif isinstance(default, int):
                    result[key] = int(raw)
                elif isinstance(default, float):
                    result[key] = float(raw)
                else:
                    result[key] = raw
            else:
                result[key] = default
        except Exception:
            result[key] = default
    return result


def _save_alerts_config(cfg: dict, config_path: str = CONFIG_PATH) -> None:
    """Write [alerts] section (internal — called under _file_lock by other functions)."""
    import os as _os
    # Read existing file to preserve non-alert sections
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
    except Exception:
        pass
    if not parser.has_section("alerts"):
        parser.add_section("alerts")
    for key, value in cfg.items():
        parser.set("alerts", key, str(value))
    # Atomic write
    cfg_dir = _os.path.dirname(config_path)
    if cfg_dir:
        _os.makedirs(cfg_dir, exist_ok=True)
    tmp_path = config_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        parser.write(f)
    _os.replace(tmp_path, config_path)


def load_alerts(config_path: str = CONFIG_PATH) -> dict:
    """Load all [alert_*] sections from config.ini.

    Returns dict {code: AlertConfig, ...}.  Empty dict if none.
    Single-section corruption is isolated — bad sections are skipped.
    File corruption → tries .tmp backup → returns {} on total failure.
    """
    from core.alert_engine import AlertConfig

    parser = configparser.ConfigParser()
    alerts: Dict[str, AlertConfig] = {}

    try:
        parser.read(config_path, encoding="utf-8")
    except Exception as e:
        # Try .tmp backup
        try:
            parser.read(config_path + ".tmp", encoding="utf-8")
        except Exception:
            return alerts

    for section in parser.sections():
        if not section.startswith("alert_"):
            continue
        try:
            code = section[6:]  # strip "alert_" prefix
            if not code:
                continue
            cfg = AlertConfig(code=code)
            if parser.has_option(section, "name"):
                cfg.name = parser.get(section, "name")
            if parser.has_option(section, "enabled"):
                cfg.enabled = parser.get(section, "enabled").lower() in ("true", "1", "yes")
            if parser.has_option(section, "price_upper"):
                raw = parser.get(section, "price_upper").strip()
                cfg.price_upper = float(raw) if raw else None
            if parser.has_option(section, "price_lower"):
                raw = parser.get(section, "price_lower").strip()
                cfg.price_lower = float(raw) if raw else None
            if parser.has_option(section, "upper_triggered"):
                cfg.upper_triggered = parser.get(section, "upper_triggered").lower() in ("true", "1", "yes")
            if parser.has_option(section, "lower_triggered"):
                cfg.lower_triggered = parser.get(section, "lower_triggered").lower() in ("true", "1", "yes")
            if parser.has_option(section, "last_price"):
                cfg.last_price = float(parser.get(section, "last_price"))
            if parser.has_option(section, "last_update"):
                cfg.last_update = parser.get(section, "last_update")
            alerts[code] = cfg
        except Exception:
            # Skip corrupted single alert, log warning
            import logging
            logging.getLogger("config").warning("Skipping corrupted alert section [%s]", section, exc_info=True)

    return alerts


def save_alert(alert, config_path: str = CONFIG_PATH) -> None:
    """Save or update a single alert section in config.ini.

    Args:
        alert: AlertConfig instance.
        config_path: Path to config.ini.

    Uses atomic write-then-rename (iron rule 5).
    """
    import os as _os

    with _file_lock:
        parser = configparser.ConfigParser()
        try:
            parser.read(config_path, encoding="utf-8")
        except Exception:
            pass

        section = f"alert_{alert.code}"
        if not parser.has_section(section):
            parser.add_section(section)

        parser.set(section, "name", alert.name)
        parser.set(section, "enabled", str(alert.enabled).lower())
        parser.set(section, "price_upper", str(alert.price_upper) if alert.price_upper is not None else "")
        parser.set(section, "price_lower", str(alert.price_lower) if alert.price_lower is not None else "")
        parser.set(section, "upper_triggered", str(alert.upper_triggered).lower())
        parser.set(section, "lower_triggered", str(alert.lower_triggered).lower())
        parser.set(section, "last_price", str(alert.last_price))
        parser.set(section, "last_update", alert.last_update)

        cfg_dir = _os.path.dirname(config_path)
        if cfg_dir:
            _os.makedirs(cfg_dir, exist_ok=True)
        tmp_path = config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            parser.write(f)
        _os.replace(tmp_path, config_path)


def delete_alert_config(code: str, config_path: str = CONFIG_PATH) -> None:
    """Remove a single alert section from config.ini."""
    import os as _os

    with _file_lock:
        parser = configparser.ConfigParser()
        try:
            parser.read(config_path, encoding="utf-8")
        except Exception:
            return

        section = f"alert_{code}"
        if parser.has_section(section):
            parser.remove_section(section)

        tmp_path = config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            parser.write(f)
        _os.replace(tmp_path, config_path)


def update_alert_state(code: str, upper_triggered: bool, lower_triggered: bool,
                       last_price: float, config_path: str = CONFIG_PATH) -> None:
    """Update only the trigger state + last price fields for an alert.
    Does NOT rewrite the entire alert — only touches 4 fields.
    """
    import os as _os

    with _file_lock:
        parser = configparser.ConfigParser()
        try:
            parser.read(config_path, encoding="utf-8")
        except Exception:
            return

        section = f"alert_{code}"
        if not parser.has_section(section):
            return

        parser.set(section, "upper_triggered", str(upper_triggered).lower())
        parser.set(section, "lower_triggered", str(lower_triggered).lower())
        parser.set(section, "last_price", str(last_price))
        import time as _time
        parser.set(section, "last_update", _time.strftime("%Y-%m-%d %H:%M:%S"))

        tmp_path = config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            parser.write(f)
        _os.replace(tmp_path, config_path)
