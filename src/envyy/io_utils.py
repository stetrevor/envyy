from pathlib import Path
from typing import Any
import yaml


class IndentDumper(yaml.SafeDumper):
    """YAML dumper enforcing 2-space indentation on nested blocks."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow=False, indentless=False)


def load_or_init_catalog(path: Path) -> dict[str, Any]:
    """Loads existing env.yaml or initializes a baseline structure."""
    if not path.is_file():
        return {
            "populate": "dev",
            "localvars": {},
            "environment": {},
        }
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"'{path}' must define a top-level YAML mapping.")
    if "environment" not in data or not isinstance(data["environment"], dict):
        data["environment"] = {}
    if "localvars" not in data or not isinstance(data["localvars"], dict):
        data["localvars"] = {}
    return data


def parse_env_file(path: Path) -> list[tuple[str, Any, str | None]]:
    """Parses a .env file, extracting (key, value, optional_comment)."""
    if not path.is_file():
        raise FileNotFoundError(f"Source environment file '{path}' not found.")

    entries: list[tuple[str, Any, str | None]] = []
    pending_comments: list[str] = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()

            if not stripped:
                pending_comments.clear()
                continue

            if stripped.startswith("#"):
                comment_text = stripped.lstrip("#").strip()
                if comment_text:
                    pending_comments.append(comment_text)
                continue

            if stripped.startswith("export "):
                stripped = stripped[7:].strip()

            if "=" not in stripped:
                continue

            key, raw_val = stripped.split("=", 1)
            key = key.strip()
            raw_val = raw_val.strip()

            if not key:
                continue

            if (raw_val.startswith('"') and raw_val.endswith('"')) or (
                raw_val.startswith("'") and raw_val.endswith("'")
            ):
                val: Any = raw_val[1:-1]
            elif raw_val.lower() == "true":
                val = True
            elif raw_val.lower() == "false":
                val = False
            else:
                try:
                    val = int(raw_val)
                except ValueError:
                    val = raw_val

            comment = " ".join(pending_comments) if pending_comments else None
            pending_comments.clear()
            entries.append((key, val, comment))

    return entries


def format_env_value(val: Any) -> str:
    """Formats Python primitives into standard .env format."""
    if isinstance(val, bool):
        return str(val).lower()
    if val is None:
        return ""
    val_str = str(val)
    if any(char in val_str for char in (" ", "#", "\n", "\t")):
        escaped = val_str.replace('"', '\\"')
        return f'"{escaped}"'
    return val_str


def atomic_write_if_changed(target_path: Path, new_content: str) -> bool:
    """Writes to file only when content has changed, bypassing redundant mtime updates."""
    if target_path.exists():
        try:
            if target_path.read_text(encoding="utf-8") == new_content:
                return False
        except Exception:
            pass

    tmp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    tmp_path.replace(target_path)
    return True
