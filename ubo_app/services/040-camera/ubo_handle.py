# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from reducer import reducer
from setup import init_service

from ubo_app.load_services import register_service
from ubo_app.utils import IS_RPI

register_service(
    service_id='camera',
    label='Camera',
    reducer=reducer,
)

if IS_RPI:
    init_service()
