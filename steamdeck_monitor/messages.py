"""Telegram message text. Pure functions; HTML parse mode."""
import time

SALE_PAGE = "https://store.steampowered.com/sale/steamdeckrefurbished/"
FAULT = "⚠️ steamdeck-monitor:"
RECOVERY = "🔧 steamdeck-monitor:"


def _ts(at):
    return time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(at))


def in_stock(model, at):
    lines = [f"🚨🚨 <b>IN STOCK: {model.name}</b>",
             f"Since {_ts(at)}",
             f"Buy: https://store.steampowered.com/sub/{model.package_id}/"]
    if "refurb" in model.name:
        lines.append(f"Sale page: {SALE_PAGE}")
    return "\n".join(lines)


def sold_out(model, at, up_seconds):
    return (f"❌ <b>{model.name}</b> is sold out again "
            f"(was up ~{int(up_seconds // 60)} min, as of {_ts(at)}). "
            "Back to watching.")


def fault(label, since):
    return (f"{FAULT} {label}. No successful Steam check since {_ts(since)}. "
            "Still retrying. Stock alerts may be missing until this clears.")


def fault_recovered():
    return f"{RECOVERY} Steam checks are working again."


def _word(in_stock_):
    return "in stock" if in_stock_ else "out of stock"


def out_of_sync(rows):
    lines = [f"{FAULT} my stock view disagrees with steamhardwarestock. "
             "Steam's API may have changed."]
    lines += [f"- {m.name}: Steam says {_word(ours)}, "
              f"steamhardwarestock says {_word(theirs)}"
              for m, ours, theirs in rows]
    return "\n".join(lines)


def in_sync():
    return f"{RECOVERY} Steam and steamhardwarestock agree again."


def crosscheck_down(since):
    return (f"{FAULT} the steamhardwarestock cross-check has been unavailable "
            f"since {_ts(since)}. Stock alerts are unaffected.")


def crosscheck_up():
    return f"{RECOVERY} the steamhardwarestock cross-check is available again."
