from dataclasses import dataclass

from .models import Model, parse_watch

MIN_CHECK_INTERVAL = 30
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass
class Config:
    token: "str | None"
    chat_id: "str | None"
    hc_url: "str | None"
    watch: "list[Model]"
    country: str
    check_interval: float
    crosscheck_interval: float
    log_level: str


def _secret(env, name):
    """Read NAME_FILE (stripped) if set, else NAME, else None."""
    path = env.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or None
    return (env.get(name) or "").strip() or None


def _number(env, name, default):
    raw = env.get(name)
    return float(raw) if raw not in (None, "") else float(default)


def load_config(env):
    log_level = (env.get("LOG_LEVEL") or "INFO").upper()
    if log_level not in LOG_LEVELS:
        raise ValueError(f"LOG_LEVEL must be one of {', '.join(sorted(LOG_LEVELS))}")
    return Config(
        token=_secret(env, "TELEGRAM_BOT_TOKEN"),
        chat_id=_secret(env, "TELEGRAM_CHAT_ID"),
        hc_url=_secret(env, "HEALTHCHECKS_PING_URL"),
        watch=parse_watch(env.get("WATCH") or "512oled,1tboled"),
        country=(env.get("COUNTRY_CODE") or "US").strip().upper(),
        check_interval=max(MIN_CHECK_INTERVAL,
                           _number(env, "CHECK_INTERVAL", 60)),
        crosscheck_interval=max(0.0, _number(env, "CROSSCHECK_INTERVAL", 900)),
        log_level=log_level,
    )
