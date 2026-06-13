"""Parse and normalize ``From`` headers."""

from email.utils import parseaddr
from typing import Tuple


def parse_from_header(from_raw):
    # type: (str) -> Tuple[str, str, str]
    """Return ``(from_raw_preserved, display_name, address_normalized)``.

    ``address_normalized`` is lowercased local@domain when an address is present.
    """
    if from_raw is None:
        from_raw = ""
    name, addr = parseaddr(from_raw)
    display = (name or "").strip()
    addr_stripped = (addr or "").strip()
    if not addr_stripped:
        normalized = ""
    else:
        if "@" in addr_stripped:
            local, _, domain = addr_stripped.rpartition("@")
            normalized = local.lower() + "@" + domain.lower()
        else:
            normalized = addr_stripped.lower()
    return (from_raw, display, normalized)
