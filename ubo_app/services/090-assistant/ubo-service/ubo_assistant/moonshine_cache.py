"""Local model-cache helpers for Moonshine (delete bookkeeping).

``moonshine_voice`` downloads each model's component files into a plain
directory under ``get_cache_dir()`` (derived from the model's CDN URL).
pipecat's ``MoonshineSTTService`` builds via ``get_model_for_language`` and
skips files already present, so once a model is downloaded a rebuild is a fast
cache-load. These helpers locate and remove a downloaded model's files so the
user can free disk space (the deletion counterpart pipecat doesn't provide).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from loguru import logger


def _model_cache_root(model_id: str) -> Path:
    """Return the on-disk cache directory for *model_id* (English models only).

    Mirrors ``moonshine_voice.download.download_model_from_info``: the model's
    component files live under ``get_cache_dir() / <download_url without scheme>``.
    """
    from moonshine_voice import string_to_model_arch
    from moonshine_voice.download import find_model_info
    from moonshine_voice.download_file import get_cache_dir

    arch = string_to_model_arch(model_id)
    info = find_model_info('en', arch)
    folder = info['download_url'].replace('https://', '')
    return Path(get_cache_dir()) / folder


def remove_model(model_id: str) -> None:
    """Delete *model_id*'s cached files. Best-effort; no-op when absent."""
    try:
        root = _model_cache_root(model_id)
    except Exception:
        logger.exception(
            'Failed to resolve Moonshine cache path; skipping delete {extra}',
            extra={'model_id': model_id},
        )
        return
    shutil.rmtree(root, ignore_errors=True)
    logger.info('Deleted Moonshine model cache {extra}', extra={'model_id': model_id})
