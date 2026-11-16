from pathlib import Path
import re
import sys
from typing import Any
import yaml

from .compiler import run_pipeline
from .constants import CONFIG_FILE, SCHEMA_FILE, STARTER_TEMPLATE, TOKEN_PATTERN
from .dedupe import suggest_token_name
from .io_utils import IndentDumper, load_or_init_catalog, parse_env_file


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
            "_meta": {
                "stages": list(dict.fromkeys([stage, populate])),
                "populate": populate,
                "consts": {},
            },
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
                r"^(\s*populate:\s*)\w+",
                rf"\g<1>{populate}",
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
    """Scans environment section for duplicate values and suggests _meta.consts."""
    data = load_or_init_catalog(CONFIG_FILE)
    environment = data.get("environment", {})
    consts = data["_meta"].setdefault("consts", {})

    value_map: dict[Any, list[tuple[str, str]]] = {}

    for var_name, var_spec in environment.items():
        if not isinstance(var_spec, dict):
            continue
        for s_key, s_val in var_spec.items():
            if s_key.startswith("_"):
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

    print(
        f"\033[33mFound {len(duplicates)} candidate value(s) for _meta.consts:\033[0m\n"
    )

    suggested_consts: dict[str, Any] = {}
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

        all_claimed_tokens = {**consts, **suggested_consts}
        while token in all_claimed_tokens and all_claimed_tokens[token] != val:
            token = f"{base_token}_{counter}"
            counter += 1

        suggested_consts[token] = val
        print(
            f"• \033[36m${{{token}}}\033[0m = \033[32m{repr(val)}\033[0m ({len(occs)} occurrences)"
        )
        for var_name, s_key in occs:
            print(f"    - {var_name} [{s_key}]")
            replacements.append((var_name, s_key, token, val))
        print()

    if not apply:
        print("Suggested \033[1m_meta.consts:\033[0m additions:")
        for t, v in suggested_consts.items():
            print(f"  {t}: {repr(v)}")
        print("\nRun with \033[36m--apply\033[0m to rewrite env.yaml automatically.")
        return

    for token, val in suggested_consts.items():
        consts[token] = val

    for var_name, s_key, token, _ in replacements:
        environment[var_name][s_key] = f"${{{token}}}"

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, Dumper=IndentDumper, sort_keys=False, allow_unicode=True)

    print(
        f"\033[32m✔ Applied {len(suggested_consts)} constant(s) to {CONFIG_FILE.name}!\033[0m"
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
            print("\033[33m[Change detected]\033[0m ", end="")
            run_pipeline(stage)
    except KeyboardInterrupt:
        print("\nWatcher stopped.")
