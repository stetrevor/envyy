# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-11-07

### Changed
- **Breaking**: Changed `watch` subcommand to require `stage` as a positional argument (e.g., `envy watch dev`), removing the `--stage` flag and the implicit `dev` fallback to prevent accidental overwrites across environments.

## [0.3.2] - 2026-11-07

### Added
- Project `CHANGELOG.md` documenting version history, breaking changes, and release milestones following the Keep a Changelog standard.
- Changelog repository reference in `pyproject.toml` metadata.

### Added
- Project `CHANGELOG.md` documenting version history, breaking changes, and release milestones following the Keep a Changelog standard.
- Changelog repository reference in `pyproject.toml` metadata.

## [0.3.1] - 2026-11-07

### Added
- Informative header documentation banner to `env.schema.yaml` detailing file purpose, masking behavior, and regeneration commands.

## [0.3.0] - 2026-11-07

### Changed
- Standardized metadata compiler directives: replaced `secret: true` with `_secret: true` to align with `_comment`.
- Simplified internal parsing by treating all keys starting with an underscore (`_`) strictly as compiler directives.
- Updated bare `init` starter template with commented-out variable patterns and inline instructions.

### Removed
- Legacy support for unprefixed `secret: true` directive.

## [0.2.0] - 2026-11-06

### Added
- `version` subcommand to print the installed package version.
- `-v` / `--version` CLI flags.

## [0.1.1] - 2026-11-06

### Added
- `envy` CLI script alias alongside `envyy`.
- Explicit MIT license metadata in `pyproject.toml`.

## [0.1.0] - 2026-11-06

### Added
- Initial public release of `envyy`.
- Core compilation pipeline generating `.env` runtime files and `env.schema.yaml` contract from `env.yaml`.
- CLI commands: `init`, `gen` (aliased as `generate`), `watch`, `import`, and `dedupe`.
- Variable substitution via `${TOKEN}` interpolation referencing `localvars`.
- Omission handling for `null` stage values.
