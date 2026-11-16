import io
from pathlib import Path
import re
from typing import Any
import yaml

from .constants import (
    CONFIG_FILE,
    ENV_FILE,
    SCHEMA_FILE,
    SCHEMA_HEADER,
    TOKEN_PATTERN,
)
from .io_utils import (
    IndentDumper,
    atomic_write_if_changed,
    format_env_value,
    load_or_init_catalog,
)


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
        is_secret = var_spec.get("_secret", False) is True

        for field_key, field_val in var_spec.items():
            if field_key.startswith("_"):
                var_schema[field_key] = field_val
            elif is_secret:
                var_schema[field_key] = ""
            elif (
                isinstance(field_val, str)
                and TOKEN_PATTERN.search(field_val)
                or field_key in allowed_stages
            ):
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

        if stage not in var_spec or var_spec[stage] is None:
            continue

        comment = var_spec.get("_comment")
        if comment:
            lines.append(f"# {comment}")

        raw_val = var_spec[stage]
        resolved_val = resolve_token(raw_val, localvars, f"{var_name} [{stage}]")
        lines.append(f"{var_name}={format_env_value(resolved_val)}\n")

    return "\n".join(lines).strip() + "\n"


def run_pipeline(stage: str, stub: bool = False) -> bool:
    """Executes interpolation, change detection, and atomic writing."""
    target_env_file = Path(f".env.{stage}") if stub else ENV_FILE

    try:
        data = load_or_init_catalog(CONFIG_FILE)
    except Exception as e:
        print(f"\033[31m✖ Error loading {CONFIG_FILE}:\033[0m {e}")
        return False

    localvars = data.get("localvars", {})
    environment = data.get("environment", {})

    try:
        env_content = generate_env_content(environment, localvars, stage)
        env_updated = atomic_write_if_changed(target_env_file, env_content)
    except KeyError as e:
        print(f"\033[31m✖ Interpolation Error:\033[0m {e}")
        return False
    except Exception as e:
        print(f"\033[31m✖ Error generating {target_env_file.name}:\033[0m {e}")
        return False

    try:
        schema_data = build_schema_data(data)
        buffer = io.StringIO()
        buffer.write(SCHEMA_HEADER)
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
            f"updated \033[32m{target_env_file.name}\033[0m (stage: \033[36m{stage}\033[0m)"
        )
    else:
        actions.append(f"\033[90m{target_env_file.name} unchanged\033[0m")

    if schema_updated:
        actions.append(f"updated \033[32m{SCHEMA_FILE.name}\033[0m")
    else:
        actions.append(f"\033[90m{SCHEMA_FILE.name} unchanged\033[0m")

    print(" | ".join(actions))
    return True
