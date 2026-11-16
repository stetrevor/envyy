import argparse
import importlib.metadata
import sys
from pathlib import Path

from .commands import cmd_dedupe, cmd_import, cmd_init, cmd_watch
from .compiler import run_pipeline
from .constants import CONFIG_FILE

try:
    __version__ = importlib.metadata.version("envyy")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.1.dev0"

__all__ = ["main", "run_pipeline"]


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
    gen_parser.add_argument(
        "-s",
        "--stub",
        action="store_true",
        help="Include the stage name in the output filename (e.g. .env.prod)",
    )

    # watch
    watch_parser = subparsers.add_parser(
        "watch",
        help=f"Watch {CONFIG_FILE.name} and recompile on save",
    )
    watch_parser.add_argument(
        "stage",
        type=str,
        help="Target stage to watch and compile (e.g. dev, staging, prod)",
    )

    # import
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

    subparsers.add_parser(
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
        success = run_pipeline(args.stage, stub=args.stub)
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
