"""Guard against a service importing a module that lives in another service.

Services resolve bare module names through `UboServiceFinder`, which searches
the *calling* service's own directory. So `from upload_handler import ...` works
inside `090-file-system` and fails with `ModuleNotFoundError` anywhere else —
at request time, not at import time, which is why it reached production.

Cross-service communication belongs on the store (actions and events), never a
direct import.

Regression test for UBO-APP-RC.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_ROOT = REPO_ROOT / 'ubo_app' / 'services'

# Vendored trees hold third-party code this rule doesn't govern — and which is
# not always valid UTF-8. `090-assistant` carries a whole sub-project venv, so
# skipping these is what keeps the scan pointed at first-party source.
VENDORED_DIRECTORIES = frozenset(
    {'__pycache__', 'build', 'dist', 'node_modules', 'site-packages'},
)


def _is_first_party(path: Path, service: Path) -> bool:
    """Whether *path* is service source rather than vendored or generated code."""
    return not any(
        part in VENDORED_DIRECTORIES or part.startswith('.')
        for part in path.relative_to(service).parts
    )


def _service_directories(root: Path) -> list[Path]:
    """Every service directory under *root*, identified by its `ubo_handle.py`."""
    return sorted(path.parent for path in root.glob('*/ubo_handle.py'))


def _local_module_names(service: Path) -> set[str]:
    """Bare module names a service can legitimately import from itself."""
    names = {path.stem for path in service.glob('*.py')}
    names |= {
        path.name
        for path in service.iterdir()
        if (path / '__init__.py').exists() and _is_first_party(path, service)
    }
    return names


def _imported_root_names(source: Path) -> set[str]:
    """Root names of every absolute import in one file.

    `import a.b` and `from a.b import c` both contribute `a`. Relative imports
    are skipped: they resolve within the package and can't cross a service
    boundary.
    """
    tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split('.')[0])
    return names


def _foreign_service_imports(
    service: Path,
    root: Path,
) -> list[tuple[Path, str, str]]:
    """Find imports in *service* resolving to a sibling service's directory.

    Returns `(source_file, imported_name, owning_service)` triples.
    """
    own = _local_module_names(service)
    others = {
        name: other.name
        for other in _service_directories(root)
        if other != service
        for name in _local_module_names(other)
    }

    findings: list[tuple[Path, str, str]] = []
    for source in sorted(service.rglob('*.py')):
        if not _is_first_party(source, service):
            continue
        findings.extend(
            (source, name, others[name])
            for name in sorted(_imported_root_names(source))
            if name not in own and name in others
        )
    return findings


@pytest.mark.parametrize(
    'service',
    _service_directories(SERVICES_ROOT),
    ids=lambda service: service.name,
)
def test_service_does_not_import_another_services_module(service: Path) -> None:
    """No service imports a bare module owned by a different service."""
    findings = _foreign_service_imports(service, SERVICES_ROOT)

    assert not findings, '\n'.join(
        f"{source.relative_to(REPO_ROOT)} imports '{name}', which lives in "
        f'{owner} — use the store instead'
        for source, name, owner in findings
    )


def _plant_service(root: Path, name: str, files: dict[str, str]) -> Path:
    """Create a throwaway service directory with the given files."""
    service = root / name
    service.mkdir(parents=True)
    (service / 'ubo_handle.py').write_text('')
    for filename, content in files.items():
        (service / filename).write_text(content)
    return service


class TestDetection:
    """The scan has to actually be able to fail."""

    def test_finds_a_planted_foreign_import(self, tmp_path: Path) -> None:
        """A file importing a sibling service's module is reported."""
        root = tmp_path / 'services'
        _plant_service(root, '090-owner', {'upload_handler.py': ''})
        borrower = _plant_service(
            root,
            '090-borrower',
            {'setup.py': 'from upload_handler import handle\n'},
        )

        findings = _foreign_service_imports(borrower, root)

        assert [(name, owner) for _, name, owner in findings] == [
            ('upload_handler', '090-owner'),
        ]

    def test_ignores_a_services_own_module(self, tmp_path: Path) -> None:
        """Importing a module from the service's own directory is fine."""
        root = tmp_path / 'services'
        service = _plant_service(
            root,
            '090-solo',
            {'constants.py': '', 'setup.py': 'from constants import THING\n'},
        )

        assert _foreign_service_imports(service, root) == []

    def test_ignores_vendored_trees(self, tmp_path: Path) -> None:
        """A sub-project venv inside a service is not scanned.

        `090-assistant` ships one, and its contents are neither first-party nor
        reliably UTF-8 — walking it crashes the scan rather than failing it.
        """
        root = tmp_path / 'services'
        _plant_service(root, '090-owner', {'upload_handler.py': ''})
        service = _plant_service(root, '090-solo', {})
        vendored = service / 'ubo-service' / '.venv' / 'lib'
        vendored.mkdir(parents=True)
        (vendored / 'vendored.py').write_text('from upload_handler import handle\n')
        (vendored / 'binary.py').write_bytes(b'\xa4\xa4 not utf-8\n')

        assert _foreign_service_imports(service, root) == []

    def test_ignores_third_party_and_stdlib(self, tmp_path: Path) -> None:
        """Only names owned by a sibling service count as findings."""
        root = tmp_path / 'services'
        _plant_service(root, '090-owner', {'upload_handler.py': ''})
        service = _plant_service(
            root,
            '090-solo',
            {'setup.py': 'import asyncio\nfrom ubo_app.store.main import store\n'},
        )

        assert _foreign_service_imports(service, root) == []
