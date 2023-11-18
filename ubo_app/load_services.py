# ruff: noqa: D100, D101, D102, D103, D104, D107
import importlib
import importlib.util
import os
import sys
from pathlib import Path

ROOT_PATH = Path(__file__).parent


def load_services() -> None:
    for services_directory_path in [
        ROOT_PATH.joinpath('services').as_posix(),
        *(
            os.environ.get('UBO_SERVICES_PATH', '').split(':')
            if os.environ.get('UBO_SERVICES_PATH')
            else []
        ),
    ]:
        if Path(services_directory_path).is_dir():
            for service_path in Path(services_directory_path).iterdir():
                spec = importlib.util.spec_from_file_location(
                    '__ubo_service__',
                    location=service_path.joinpath('__init__.py').as_posix(),
                )
                if not spec:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                if spec.loader:
                    spec.loader.exec_module(module)
