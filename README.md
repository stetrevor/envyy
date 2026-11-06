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

Your local source of truth. It contains three top-level sections:

```yaml
# Stage values safe to commit to env.schema.yaml
populate: dev

# Shared constants referenced via ${TOKEN} (never emitted directly)
localvars:
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
    secret: true
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
envy watch --stage dev
```

---

## Recommended `.gitignore`

Ensure private catalogs and generated environments stay out of version control while committing the schema contract:

```gitignore
# Envy local configurations
env.yaml
.env
*.tmp

# DO NOT ignore the team schema contract
!env.schema.yaml
```

---

## License

MIT
