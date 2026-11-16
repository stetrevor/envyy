# envyy

Fast, schema-driven environment configuration compiler and orchestrator.

`envyy` manages multi-stage application configurations through a clean three-tier architecture:

* **`env.yaml`**: Local, private configuration catalog containing secrets, stage matrices, and shared constants (ignored by Git).
* **`env.schema.yaml`**: Public, scrubbed team contract that documents keys, comments, and structure without leaking secrets (committed to Git).
* **`.env`**: Active, single-file runtime payload compiled for a specific deployment stage.

---

## Installation & Quick Run

The package provides two executable command aliases:
* **`envyy`**: Matches the PyPI package name, enabling instant, configuration-free execution via `uvx`.
* **`envy`**: A shorter alias for fast day-to-day terminal usage when installed.

### Run via `uvx` (No Installation Required)

Run directly from PyPI without installing:

```bash
uvx envyy --help
```

*(You can also run the shorter alias with `uvx --from envyy envy --help`)*

### Install Globally via `uv tool`

Install the package globally to make both `envy` and `envyy` commands available across your system:

```bash
uv tool install envyy
```

Once installed, either command works interchangeably:

```bash
envy --help
# or
envyy --help
```

---

## Core Concepts

### 1. Root Configuration (`env.yaml`)

Your local source of truth. It contains two top-level sections: `_meta` (stage registry, schema population rules, and `UPPER_SNAKE_CASE` constants) and `environment`:

```yaml
_meta:
  # Exhaustive list of valid stages (prevents namespace collisions)
  stages:
    - dev
    - staging
    - prod

  # Stage values safe to commit to env.schema.yaml
  populate: dev

  # Shared UPPER_SNAKE_CASE constants referenced via ${TOKEN} (never emitted directly)
  consts:
    BASE_DOMAIN: "example.com"
    DEFAULT_PORT: 8080

# Environment variables per stage
environment:
  PORT:
    _comment: "HTTP server listener port"
    dev: 3000
    staging: "${DEFAULT_PORT}"
    prod: "${DEFAULT_PORT}"

  API_URL:
    _comment: "Backend API gateway"
    dev: "http://localhost:8080"
    staging: "https://staging-api.${BASE_DOMAIN}"
    prod: "https://api.${BASE_DOMAIN}"

  DATABASE_URL:
    _comment: "Database connection string. Scrubbed from schema."
    _secret: true
    dev: "postgresql://postgres:postgres@localhost:5432/app_dev"
    prod: "postgresql://admin:secret@db.prod.internal:5432/app_prod"
```

### 2. Omission Rules During Compilation

* **Omitted:** If a variable has no entry for a given stage, or is set to explicit null (`~`, `null`, or bare `stage:`), it is omitted from `.env` entirely. No orphaned comments are written.
* **Preserved:** Explicit empty strings (`""`), `0`, and `false` are recognized as deliberate operational overrides and emitted as `KEY=`, `KEY=0`, or `KEY=false`.

---

## CLI Usage

> **Note:** All examples below use `envy`, but `envyy` can be substituted interchangeably.

### `init` — Scaffold or Seed Configuration

Initialize a starter template or bootstrap from an existing `.env` file:

```bash
# Initialize a starter env.yaml (or copies existing env.schema.yaml)
envy init

# Seed env.yaml directly from an existing .env file into dev
envy init .env.dev dev

# Seed directly into production and specify schema populate stage
envy init .env.prod prod --populate dev
```

### `gen` — Compile .env and Sync Schema

Compiles `.env` according to the values specified for the stage and updates `env.schema.yaml`. Redundant disk writes are bypassed if file contents have not changed.

```bash
# Compile for development
envy gen dev

# Compile for staging
envy gen staging

# Compile for production
envy gen prod

# Generate a stage-suffixed stub (.env.prod) without overwriting .env
envy gen prod -s
```

### `import` — Ingest External `.env` Files

Merge keys from any `.env` file into a target stage inside `env.yaml` without destroying existing comments or other stages:

```bash
# Import a local development file into the dev stage
envy import .env.local dev

# Ingest production values into the prod stage
envy import /path/to/production.env prod
```

### `dedupe` — Identify Duplicates & Suggest `localvars`

Scans stage values across `env.yaml` to detect duplicates, suggesting sanitized, underscore-slugged `${TOKEN}` identifiers:

* Distinguishes full URLs with protocols as `ORIGIN_*`.
* Distinguishes bare hostnames/domains as `HOST_*`.
* Automatically disambiguates stage-specific keys (e.g., `SHARED_API_KEYS_DEV` vs. `SHARED_API_KEYS_PROD`).

```bash
# Inspect potential duplicate values
envy dedupe

# Inspect with custom occurrence threshold (default: 2)
envy dedupe --min-count 3

# Automatically apply suggested localvars and refactor env.yaml
envy dedupe --apply
```

### `watch` — Live Development Sync

Monitors `env.yaml` for edits and recompiles `.env` and `env.schema.yaml` on save with built-in debouncing:

```bash
# Watch and keep .env compiled for dev
envy watch dev
```

---

## Recommended `.gitignore`

Ensure private catalogs and generated environments stay out of version control while committing the schema contract:

```gitignore
# Envy local configurations and generated files
env.yaml
.env
.env.*
*.tmp

# DO NOT ignore the team schema contract
!env.schema.yaml
```

---

## License

MIT

---

## Compiler & Validation Rules

`envyy` enforces strict structural rules on `env.yaml` before writing `.env` or updating `env.schema.yaml`:

1. **Unified `_meta` Block:** All compiler metadata lives under the top-level `_meta` mapping (`stages`, `populate`, and `consts`). Legacy top-level `populate` or `localvars` keys are rejected to keep metadata cleanly separated from `environment` definitions.
2. **Explicit Stage Registry (`_meta.stages`):** Every valid stage must be declared in `_meta.stages` (e.g., `[dev, staging, prod]`). CLI commands (`gen`, `watch`, `import`, `dedupe`) and `_meta.populate` validate against this list upfront and fail fast if an undeclared stage is referenced.
3. **Strict Namespace Isolation:** Inside any variable block under `environment`, keys must either start with an underscore (`_comment`, `_secret`) as compiler directives or match a stage listed in `_meta.stages`. Any unrecognized key triggers a namespace collision error rather than being silently ignored.
4. **Immutable `UPPER_SNAKE_CASE` Constants (`_meta.consts`):** Shared constants must match `^[A-Z][A-Z0-9_]*$` (e.g., `DEFAULT_PORT`, `BASE_DOMAIN`). Both `_meta.consts` keys and `${TOKEN}` references inside `environment` values are validated against this pattern, and referencing an undefined constant aborts compilation.
5. **Deterministic Omission & Preservation:**
   * **Omitted:** If a variable omits a target stage or sets it to explicit null (`~`, `null`, or bare `stage:`), both the key and its `_comment` are omitted from `.env`.
   * **Preserved:** Explicit empty strings (`""`), `0`, and `false` are emitted verbatim as `KEY=`, `KEY=0`, and `KEY=false`.
6. **Non-Destructive Watch Loop:** During `envy watch <stage>`, any validation or interpolation error prints a diagnostic message and skips file generation until `env.yaml` is saved in a valid state, preserving your last known-good `.env`.
