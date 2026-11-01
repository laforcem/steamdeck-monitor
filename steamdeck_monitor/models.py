from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    key: str
    package_id: int
    name: str


MODELS = {m.key: m for m in (
    Model("512oled", 1202542, "Steam Deck 512 GB OLED (refurb)"),
    Model("1tboled", 1202547, "Steam Deck 1 TB OLED (refurb)"),
    Model("dock", 761892, "Steam Deck Docking Station"),
    Model("64lcd", 903905, "Steam Deck 64 GB LCD (refurb)"),
    Model("256lcd", 903906, "Steam Deck 256 GB LCD (refurb)"),
    Model("512lcd", 903907, "Steam Deck 512 GB LCD (refurb)"),
)}

ALL_PACKAGE_IDS = [m.package_id for m in MODELS.values()]


def parse_watch(raw):
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise ValueError("WATCH is empty")
    unknown = [k for k in keys if k not in MODELS]
    if unknown:
        raise ValueError(f"unknown WATCH key(s): {', '.join(unknown)} "
                         f"(valid: {', '.join(MODELS)})")
    return [MODELS[k] for k in keys]
