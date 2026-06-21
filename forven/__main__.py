"""Module entrypoint for `python -m forven`."""

from forven.migration.juddex_to_forven import migrate_home_directory

migrate_home_directory()

from forven.config import ensure_state_dir_bootstrapped

ensure_state_dir_bootstrapped()

from forven.cli import cli


if __name__ == "__main__":
    cli()
