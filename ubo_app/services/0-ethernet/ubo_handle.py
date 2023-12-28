# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from setup import init_service

from ubo_app.load_services import register_service

register_service(
    service_id='wifi',
    label='WiFi',
)

init_service()
