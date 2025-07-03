"""gRPC service that implements the Store service."""

from __future__ import annotations

from ubo_app.logger import logger
from ubo_app.utils import secrets

from ubo_bindings.secrets.v1 import (
    QuerySecretRequest,
    QuerySecretResponse,
    SecretsServiceBase,
)


class SecretsService(SecretsServiceBase):
    """gRPC service class that implements the Store service."""

    async def query_secret(
        self,
        query_secret_request: QuerySecretRequest,
    ) -> QuerySecretResponse:
        """Query a secret from the store."""
        logger.debug(
            'Querying secret',
            extra={'key': query_secret_request.key},
        )

        secret = secrets.read_secret(query_secret_request.key)
        if secret is None:
            return QuerySecretResponse(error='Secret not found')

        return QuerySecretResponse(value=secret)
