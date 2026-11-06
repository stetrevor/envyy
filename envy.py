# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0.2",
#     "watchfiles>=0.21.0",
# ]
# ///

import argparse
import io
import re
import sys
from pathlib import Path
from typing import Any
import yaml

CONFIG_FILE = Path("env.yaml")
SCHEMA_FILE = Path("env.schema.yaml")
ENV_FILE = Path(".env")

TOKEN_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


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

            # Empty lines reset detached comments
            if not stripped:
                pending_comments.clear()
                continue

            # Collect comment lines
            if stripped.startswith("#"):
                comment_text = stripped.lstrip("#").strip()
                if comment_text:
                    pending_comments.append(comment_text)
                continue

            # Strip optional leading 'export '
            if stripped.startswith("export "):
                stripped = stripped[7:].strip()

            if "=" not in stripped:
                continue

            key, raw_val = stripped.split("=", 1)
            key = key.strip()
            raw_val = raw_val.strip()

            if not key:
                continue

            # Strip surrounding quotes
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


def resolve_token(value: Any, localvars: dict[str, Any], context_label: str) -> Any:
    """Substitutes ${KEY} placeholders using flat localvars definitions."""
    if not isinstance(value, str):
        return value

    exact_match = re.fullmatch(r"\$\{([A-Za-z0-9_]+)\}", value.strip())
    if exact_match:
        token = exact_match.group(1)
        if token not in localvars:
            raise KeyError(
                f"Undefined localvar '${{{token}}}' referenced in {context_label}"
            )
        return localvars[token]

    def _replace(match: re.Match) -> str:
        token = match.group(1)
        if token not in localvars:
            raise KeyError(
                f"Undefined localvar '${{{token}}}' referenced in {context_label}"
            )
        return str(localvars[token])

    return TOKEN_PATTERN.sub(_replace, value)


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


def build_schema_data(data: dict[str, Any]) -> dict[str, Any]:
    """Builds the sanitized structural schema for Git tracking."""
    populate_rules = data.get("populate", "dev")
    allowed_stages = (
        {populate_rules}
        if isinstance(populate_rules, str)
        else set(populate_rules or [])
    )

    schema: dict[str, Any] = {"populate": populate_rules}

    localvars = data.get("localvars", {})
    schema["localvars"] = {k: "" for k in localvars.keys()}

    environment = data.get("environment", {})
    schema_env: dict[str, Any] = {}

    for var_name, var_spec in environment.items():
        if not isinstance(var_spec, dict):
            schema_env[var_name] = ""
            continue

        var_schema: dict[str, Any] = {}
        is_secret = var_spec.get("secret", False) is True

        for field_key, field_val in var_spec.items():
            if field_key.startswith("_") or field_key == "secret":
                var_schema[field_key] = field_val
            elif is_secret:
                var_schema[field_key] = ""
            elif isinstance(field_val, str) and TOKEN_PATTERN.search(field_val):
                var_schema[field_key] = field_val
            elif field_key in allowed_stages:
                var_schema[field_key] = field_val
            else:
                var_schema[field_key] = ""

        schema_env[var_name] = var_schema

    schema["environment"] = schema_env
    return schema


def generate_env_content(
    environment: dict[str, Any], localvars: dict[str, Any], stage: str
) -> str:
    """Generates the full in-memory .env content for the requested stage."""
    lines = [
        f"# Auto-generated configuration for stage: {stage}",
        "# DO NOT EDIT DIRECTLY. Manage via env.yaml\n",
    ]

    for var_name, var_spec in environment.items():
        if not isinstance(var_spec, dict):
            resolved = resolve_token(var_spec, localvars, var_name)
            lines.append(f"{var_name}={format_env_value(resolved)}")
            continue

        comment = var_spec.get("_comment")
        if comment:
            lines.append(f"# {comment}")

        raw_val = var_spec.get(stage, var_spec.get("default", ""))
        resolved_val = resolve_token(raw_val, localvars, f"{var_name} [{stage}]")
        lines.append(f"{var_name}={format_env_value(resolved_val)}\n")

    return "\n".join(lines).strip() + "\n"


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


def run_pipeline(stage: str) -> bool:
    """Executes interpolation, change detection, and atomic writing."""
    try:
        data = load_or_init_catalog(CONFIG_FILE)
    except Exception as e:
        print(f"\033[31m✖ Error loading {CONFIG_FILE}:\033[0m {e}")
        return False

    localvars = data.get("localvars", {})
    environment = data.get("environment", {})

    # 1. Compile .env
    try:
        env_content = generate_env_content(environment, localvars, stage)
        env_updated = atomic_write_if_changed(ENV_FILE, env_content)
    except KeyError as e:
        print(f"\033[31m✖ Interpolation Error:\033[0m {e}")
        return False
    except Exception as e:
        print(f"\033[31m✖ Error generating {ENV_FILE.name}:\033[0m {e}")
        return False

    # 2. Compile env.schema.yaml
    try:
        schema_data = build_schema_data(data)
        buffer = io.StringIO()
        buffer.write("# Auto-generated from env.yaml. DO NOT EDIT DIRECTLY.\n")
        buffer.write(
            "# Commit this file to Git as the team configuration contract.\n\n"
        )
        yaml.dump(
            schema_data,
            buffer,
            Dumper=IndentDumper,
            sort_keys=False,
            allow_unicode=True,
        )
        schema_content = buffer.getvalue()
        schema_updated = atomic_write_if_changed(SCHEMA_FILE, schema_content)
    except Exception as e:
        print(f"\033[31m✖ Error generating {SCHEMA_FILE.name}:\033[0m {e}")
        return False

    # Status reporting
    actions = []
    if env_updated:
        actions.append(
            f"updated \033[32m{ENV_FILE.name}\033[0m (stage: \033[36m{stage}\033[0m)"
        )
    else:
        actions.append(f"\033[90m{ENV_FILE.name} unchanged\033[0m")

    if schema_updated:
        actions.append(f"updated \033[32m{SCHEMA_FILE.name}\033[0m")
    else:
        actions.append(f"\033[90m{SCHEMA_FILE.name} unchanged\033[0m")

    print(" | ".join(actions))
    return True


def cmd_import(file_path: Path, stage: str):
    """Imports variables from a .env file into env.yaml under the designated stage."""
    try:
        entries = parse_env_file(file_path)
    except Exception as e:
        print(f"\033[31m✖ Error reading '{file_path}':\033[0m {e}")
        sys.exit(1)

    if not entries:
        print(
            f"\033[33mWarning:\033[0m No variable assignments found in '{file_path}'."
        )
        return

    data = load_or_init_catalog(CONFIG_FILE)
    env_dict = data["environment"]

    added = 0
    updated = 0

    for key, val, comment in entries:
        if key not in env_dict or not isinstance(env_dict[key], dict):
            # New entry
            var_entry: dict[str, Any] = {}
            if comment:
                var_entry["_comment"] = comment
            var_entry[stage] = val
            env_dict[key] = var_entry
            added += 1
        else:
            # Existing entry: merge the stage value without destroying other stages/comments
            target_entry = env_dict[key]
            if comment and "_comment" not in target_entry:
                target_entry["_comment"] = comment
            target_entry[stage] = val
            updated += 1

    # Write updated env.yaml
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, Dumper=IndentDumper, sort_keys=False, allow_unicode=True)

    print(
        f"\033[32m✔ Imported into '{CONFIG_FILE.name}' [stage: {stage}]:\033[0m {added} added, {updated} updated."
    )

    # Re-generate schema and sync target
    run_pipeline(stage)


def cmd_watch(stage: str):
    """Watches env.yaml for changes with debounced execution."""
    from watchfiles import watch

    print(
        f"\033[36m⚡ Watching {CONFIG_FILE.name} for stage '{stage}' (Ctrl+C to quit)...\033[0m"
    )
    run_pipeline(stage)

    try:
        for _ in watch(CONFIG_FILE, debounce=150):
            print(f"\033[33m[Change detected]\033[0m ", end="")
            run_pipeline(stage)
    except KeyboardInterrupt:
        print("\nWatcher stopped.")


def main():
    parser = argparse.ArgumentParser(
        prog="env-sync",
        description="Centralized environment manager producing single .env and schema files.",
    )
    parser.add_argument(
        "--stage",
        "-s",
        default="dev",
        help="Target deployment stage (e.g. dev, staging, prod). Default: dev",
    )

    subparsers = parser.add_subparsers(dest="command")

    # generate
    subparsers.add_parser("generate", help="Compile .env and schema once and exit")

    # watch
    subparsers.add_parser(
        "watch", help=f"Watch {CONFIG_FILE.name} and recompile on save"
    )

    # import
    import_parser = subparsers.add_parser(
        "import", help="Import an existing .env file into a stage"
    )
    import_parser.add_argument(
        "file", type=Path, help="Path to the .env file to import"
    )

    args = parser.parse_args()

    if args.command == "import":
        cmd_import(args.file, args.stage)
    elif args.command == "generate":
        success = run_pipeline(args.stage)
        sys.exit(0 if success else 1)
    elif args.command == "watch":
        cmd_watch(args.stage)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
