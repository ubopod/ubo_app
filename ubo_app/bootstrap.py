"""Entry point for the bootstrap script."""

import sys

from ubo_app.system.bootstrap import bootstrap


def main() -> None:
    """Run the bootstrap script."""
    bootstrap(
        with_docker='--with-docker' in sys.argv,
        in_packer='--in-packer' in sys.argv,
    )
    sys.stdout.write('Bootstrap completed.\n')
    sys.stdout.flush()
    sys.exit(0)
