import argparse
import importlib.metadata
import io
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

try:
    __version__ = importlib.metadata.version("envyy")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.1.dev0"

CONFIG_FILE = Path("env.yaml")
SCHEMA_FILE = Path("env.schema.yaml")
ENV_FILE = Path(".env")

STARTER_TEMPLATE = """# ==============================================================================
# envyy Configuration (env.yaml)
# Private environment definition. DO NOT commit this file to public repositories.
# ==============================================================================

populate: dev

localvars:
  # DEFAULT_PORT: 5432
  # APP_NAME: "my_service"

environment:
  # APP_ENV:
  #   _comment: "Application environment runtime mode"
  #   dev: "development"
  #   staging: "staging"
  #   prod: "production"
  #
  # DATABASE_URL:
  #   _comment: "Primary database connection string"
  #   secret: true
  #   dev: "postgresql://localhost:${DEFAULT_PORT}/${APP_NAME}_dev"
  #   prod: "postgresql://db.internal.vpc:${DEFAULT_PORT}/${APP_NAME}_prod"
  #
  # OPTIONAL_FEATURE_FLAG:
  #   _comment: "Set to null or omit to exclude key entirely from compiled .env"
  #   dev: "enabled"
  #   prod: null
"""

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
            continue

        # If the stage key doesn't exist or is explicitly null (~, None, bare 'stage:') -> OMIT
        if stage not in var_spec or var_spec[stage] is None:
            continue

        comment = var_spec.get("_comment")
        if comment:
            lines.append(f"# {comment}")

        raw_val = var_spec[stage]
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

    try:
        env_content = generate_env_content(environment, localvars, stage)
        env_updated = atomic_write_if_changed(ENV_FILE, env_content)
    except KeyError as e:
        print(f"\033[31m✖ Interpolation Error:\033[0m {e}")
        return False
    except Exception as e:
        print(f"\033[31m✖ Error generating {ENV_FILE.name}:\033[0m {e}")
        return False

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


def cmd_init(
    file_path: Path | None = None, stage: str | None = None, populate: str = "dev"
):
    """Initializes env.yaml from a starter template or an existing .env file."""
    if CONFIG_FILE.exists():
        print(f"\033[33mWarning:\033[0m {CONFIG_FILE.name} already exists.")
        if file_path and stage:
            print(
                f"To merge into an existing file, use: envy import {file_path} {stage}"
            )
        return

    # Seed directly from an existing .env file
    if file_path and stage:
        try:
            entries = parse_env_file(file_path)
        except FileNotFoundError:
            print(
                f"\033[31m✖ Error:\033[0m Source environment file '{file_path}' not found."
            )
            print(f"\033[36mUsage:\033[0m envy init [file stage] [--populate POPULATE]")
            sys.exit(1)
        except Exception as e:
            print(f"\033[31m✖ Error reading '{file_path}':\033[0m {e}")
            sys.exit(1)

        print(
            f"Initializing {CONFIG_FILE.name} from '{file_path}' for stage '{stage}'..."
        )
        data = {
            "populate": populate,
            "localvars": {},
            "environment": {},
        }

        for key, val, comment in entries:
            var_entry: dict[str, Any] = {}
            if comment:
                var_entry["_comment"] = comment
            var_entry[stage] = val
            data["environment"][key] = var_entry

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(data, f, Dumper=IndentDumper, sort_keys=False, allow_unicode=True)

        print(
            f"\033[32m✔ Initialized '{CONFIG_FILE.name}' [stage: {stage}, populate: {populate}] with {len(entries)} variables.\033[0m"
        )
        run_pipeline(stage)
        return

    # Bare init: Fall back to existing schema or the default template
    if SCHEMA_FILE.exists():
        print(
            f"Found existing {SCHEMA_FILE.name}. Initializing {CONFIG_FILE.name} from schema..."
        )
        CONFIG_FILE.write_text(
            SCHEMA_FILE.read_text(encoding="utf-8"), encoding="utf-8"
        )
    else:
        print(f"Creating starter {CONFIG_FILE.name}...")
        template = STARTER_TEMPLATE
        if populate != "dev":
            template = re.sub(
                r"^populate:\s*\w+",
                f"populate: {populate}",
                template,
                flags=re.MULTILINE,
            )
        CONFIG_FILE.write_text(template, encoding="utf-8")

    run_pipeline(populate)


def cmd_import(file_path: Path, stage: str):
    """Imports variables from a .env file into env.yaml under the designated stage."""
    try:
        entries = parse_env_file(file_path)
    except FileNotFoundError:
        print(
            f"\033[31m✖ Error:\033[0m Source environment file '{file_path}' not found."
        )
        print(f"\033[36mUsage:\033[0m envy import <file> <stage>")
        print(f"       Example: envy import .env.dev {file_path}")
        sys.exit(1)
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
            var_entry: dict[str, Any] = {}
            if comment:
                var_entry["_comment"] = comment
            var_entry[stage] = val
            env_dict[key] = var_entry
            added += 1
        else:
            target_entry = env_dict[key]
            if comment and "_comment" not in target_entry:
                target_entry["_comment"] = comment
            target_entry[stage] = val
            updated += 1

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, Dumper=IndentDumper, sort_keys=False, allow_unicode=True)

    print(
        f"\033[32m✔ Imported into '{CONFIG_FILE.name}' [stage: {stage}]:\033[0m {added} added, {updated} updated."
    )
    run_pipeline(stage)


def cmd_dedupe(apply: bool, min_count: int, stage: str):
    """Scans environment section for duplicate values and suggests localvars."""
    data = load_or_init_catalog(CONFIG_FILE)
    environment = data.get("environment", {})
    localvars = data.setdefault("localvars", {})

    value_map: dict[Any, list[tuple[str, str]]] = {}

    for var_name, var_spec in environment.items():
        if not isinstance(var_spec, dict):
            continue
        for s_key, s_val in var_spec.items():
            if s_key.startswith("_") or s_key == "secret":
                continue
            if s_val in ("", None) or isinstance(s_val, bool):
                continue
            if isinstance(s_val, str) and TOKEN_PATTERN.search(s_val):
                continue

            value_map.setdefault(s_val, []).append((var_name, s_key))

    duplicates = {
        val: occs for val, occs in value_map.items() if len(occs) >= min_count
    }

    if not duplicates:
        print(
            f"\033[32m✔ No duplicate values found\033[0m (threshold: >= {min_count} occurrences)."
        )
        return

    print(f"\033[33mFound {len(duplicates)} candidate value(s) for localvars:\033[0m\n")

    suggested_localvars: dict[str, Any] = {}
    replacements: list[tuple[str, str, str, Any]] = []

    for val, occs in duplicates.items():
        base_token = suggest_token_name(val, occs)

        stages = {s_key for _, s_key in occs}
        if len(stages) == 1:
            stage_suffix = next(iter(stages)).upper()
            if not base_token.endswith(f"_{stage_suffix}"):
                base_token = f"{base_token}_{stage_suffix}"

        token = base_token
        counter = 1

        all_claimed_tokens = {**localvars, **suggested_localvars}
        while token in all_claimed_tokens and all_claimed_tokens[token] != val:
            token = f"{base_token}_{counter}"
            counter += 1

        suggested_localvars[token] = val
        print(
            f"• \033[36m${{{token}}}\033[0m = \033[32m{repr(val)}\033[0m ({len(occs)} occurrences)"
        )
        for var_name, s_key in occs:
            print(f"    - {var_name} [{s_key}]")
            replacements.append((var_name, s_key, token, val))
        print()

    if not apply:
        print("Suggested \033[1mlocalvars:\033[0m additions:")
        for t, v in suggested_localvars.items():
            print(f"  {t}: {repr(v)}")
        print("\nRun with \033[36m--apply\033[0m to rewrite env.yaml automatically.")
        return

    for token, val in suggested_localvars.items():
        localvars[token] = val

    for var_name, s_key, token, _ in replacements:
        environment[var_name][s_key] = f"${{{token}}}"

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, Dumper=IndentDumper, sort_keys=False, allow_unicode=True)

    print(
        f"\033[32m✔ Applied {len(suggested_localvars)} localvars to {CONFIG_FILE.name}!\033[0m"
    )
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
        prog="envy",
        description="Centralized environment manager producing single .env and schema files.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # init
    init_parser = subparsers.add_parser(
        "init",
        help=f"Initialize {CONFIG_FILE.name} (bare template or from a file + stage)",
    )
    init_parser.add_argument(
        "seed",
        nargs="*",
        help="Optional: <file> <stage> to seed env.yaml from an existing file",
    )
    init_parser.add_argument(
        "--populate",
        "-p",
        default="dev",
        help="Stage values safe to commit in env.schema.yaml (default: dev)",
    )

    # gen (aliased as generate)
    gen_parser = subparsers.add_parser(
        "gen",
        aliases=["generate"],
        help="Generate .env according to values specified by stage and sync schema",
        description="Generate .env according to values specified by stage.",
    )
    gen_parser.add_argument(
        "stage",
        type=str,
        help="Target stage to extract values from (e.g. dev, staging, prod)",
    )
    # watch
    watch_parser = subparsers.add_parser(
        "watch",
        help=f"Watch {CONFIG_FILE.name} and recompile on save",
    )
    watch_parser.add_argument(
        "--stage",
        "-s",
        default="dev",
        help="Target deployment stage to watch and compile. Default: dev",
    )

    # import: two positional arguments (file and stage)
    import_parser = subparsers.add_parser(
        "import",
        help="Import an existing .env file into a stage",
    )
    import_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .env file to import",
    )
    import_parser.add_argument(
        "stage",
        type=str,
        help="Target stage to import into (e.g. dev, staging, prod)",
    )

    # dedupe
    dedupe_parser = subparsers.add_parser(
        "dedupe",
        help="Find duplicate values in environment and suggest localvars",
    )
    dedupe_parser.add_argument(
        "--stage",
        "-s",
        default="dev",
        help="Target stage to compile after refactoring. Default: dev",
    )
    dedupe_parser.add_argument(
        "--apply",
        action="store_true",
        help="Automatically write suggested tokens to env.yaml and replace duplicates",
    )
    dedupe_parser.add_argument(
        "--min-count",
        type=int,
        default=2,
        help="Minimum number of occurrences to consider a duplicate (default: 2)",
    )

    version_parser = subparsers.add_parser(
        "version",
        help="Display installed envyy version",
    )

    args = parser.parse_args()

    if args.command == "init":
        file_path = None
        stage = None

        if len(args.seed) == 1:
            init_parser.error(
                "When providing a file, you must also specify the stage: envy init <file> <stage>"
            )
        elif len(args.seed) == 2:
            file_path = Path(args.seed[0])
            stage = args.seed[1]
        elif len(args.seed) > 2:
            init_parser.error(
                "Too many arguments. Usage: envy init [file stage] [--populate POPULATE]"
            )

        cmd_init(file_path=file_path, stage=stage, populate=args.populate)
    elif args.command in ("gen", "generate"):
        success = run_pipeline(args.stage)
        sys.exit(0 if success else 1)
    elif args.command == "watch":
        cmd_watch(args.stage)
    elif args.command == "import":
        cmd_import(args.file, args.stage)
    elif args.command == "dedupe":
        cmd_dedupe(args.apply, args.min_count, args.stage)
    elif args.command == "version":
        print(f"envyy {__version__}")
        sys.exit(0)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
