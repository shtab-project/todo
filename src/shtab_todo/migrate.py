"""Миграции только Todo: python -m shtab_todo.migrate upgrade head."""

from pathlib import Path

from alembic.config import CommandLine, Config


def migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    return config


def main() -> None:
    cli = CommandLine(prog="python -m shtab_todo.migrate")
    options = cli.parser.parse_args()
    if not hasattr(options, "cmd"):
        cli.parser.error("Укажите команду, например: upgrade head")
    config = migration_config()
    config.cmd_opts = options
    cli.run_cmd(config, options)


if __name__ == "__main__":
    main()
