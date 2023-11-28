# ruff: noqa: D100, D101, D102, D103, D104, D107
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

from redux import CombineReducerRegisterAction, CombineReducerRegisterActionPayload

from ubo_app.logging import logger

ROOT_PATH = Path(__file__).parent


def load(path: Path) -> Any:
    try:
        if path.exists():
            spec = importlib.util.spec_from_file_location(
                '__ubo_service__',
                location=path.as_posix(),
                submodule_search_locations=[path.parent.as_posix()],
            )
            if not spec:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            if spec.loader:
                spec.loader.exec_module(module)
            return module
    except Exception as exception:  # noqa: BLE001
        logger.error(f'Error loading "{path}"')
        logger.exception(exception)


def load_services() -> None:
    from ubo_app import store

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
                if not service_path.is_dir():
                    continue
                current_path = os.curdir
                os.chdir(service_path.as_posix())

                info = load(service_path.joinpath('__init__.py'))
                reducer = load(service_path.joinpath('reducer.py'))
                load(service_path.joinpath('setup.py'))

                if reducer is not None and hasattr(reducer, 'reducer'):
                    store.dispatch(
                        CombineReducerRegisterAction(
                            _id=store.root_reducer_id,
                            payload=CombineReducerRegisterActionPayload(
                                key=info.ubo_service_id,
                                reducer=reducer.reducer,
                            ),
                        ),
                    )

                os.chdir(current_path)
