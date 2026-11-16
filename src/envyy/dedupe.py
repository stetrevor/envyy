import re
from typing import Any
from urllib.parse import urlparse


def sanitize_token_slug(text: str) -> str:
    """Converts any string to an uppercase slug containing only letters, numbers, and underscores."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug.upper()


def suggest_token_name(value: Any, occurrences: list[tuple[str, str]]) -> str:
    """Generates an uppercase identifier based on value semantics."""
    val_str = str(value).strip()
    var_names = [var for var, _ in occurrences]

    if isinstance(value, int) or val_str.isdigit():
        for name in var_names:
            if "PORT" in name.upper():
                return "DEFAULT_PORT"
        return sanitize_token_slug(f"SHARED_VAL_{val_str}")

    if re.match(r"^https?://", val_str, re.IGNORECASE):
        parsed = urlparse(val_str)
        host_stem = parsed.hostname or parsed.netloc.split(":")[0]
        return sanitize_token_slug(f"ORIGIN_{host_stem}")

    domain_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9-]*\.)+[a-zA-Z]{2,}(:[0-9]+)?$"
    if re.match(domain_pattern, val_str):
        host_stem = val_str.split(":")[0]
        return sanitize_token_slug(f"HOST_{host_stem}")

    if val_str in ("localhost", "127.0.0.1"):
        return "HOST_LOCALHOST"

    clean_names = [re.sub(r"^(DEV_|PROD_|STAGING_)", "", n) for n in var_names]
    common_stem = clean_names[0]
    return sanitize_token_slug(f"SHARED_{common_stem}")
