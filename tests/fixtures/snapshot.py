"""Window snapshot fixture using gRPC screenshot round-trip."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from str_to_bool import str_to_bool

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.fixtures import SubRequest  # pyright: ignore[reportPrivateImportUsage]


def write_png(image_path: Path, data: bytes) -> None:
    """Write raw PNG bytes to a file."""
    with image_path.open('wb') as f:
        f.write(data)


def read_accepted_hashes(hash_path: Path) -> list[str]:
    """Return every accepted hash from a ``.hash`` file.

    A window ``.hash`` file may list more than one accepted hash, one per
    line after the ``// <filename>`` header comment. This supports boards
    whose GPU rasterises a settled frame a single sub-pixel differently
    (e.g. a Raspberry Pi 4's V3D 4.2 vs a Pi 5's V3D 7.1) — both values are
    valid for the same reference, so the snapshot passes on either board.
    """
    return [
        line.strip()
        for line in hash_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith('//')
    ]


def format_hash_file(filename: str, hashes: list[str]) -> str:
    """Serialise a ``.hash`` file: a header comment then one hash per line."""
    return f'// {filename}\n' + '\n'.join(hashes) + '\n'


class WindowSnapshot:
    """Context object for tests taking snapshots of the window via store events."""

    def __init__(
        self: WindowSnapshot,
        *,
        test_id: str,
        path: Path,
        override: bool,
        make_screenshots: bool,
        prefix: str | None,
    ) -> None:
        """Create a new window snapshot context."""
        self.prefix = prefix
        self._is_failed = False
        self._is_closed = False
        self.override = override
        self.make_screenshots = make_screenshots
        self.test_counter: dict[str | None, int] = defaultdict(int)
        self._latest_hash: str | None = None
        self._latest_data: bytes | None = None

        file = path.with_suffix('').name
        self.results_dir = Path(
            path.parent / 'results' / file / test_id.split('::')[-1][5:],
        )
        if self.results_dir.exists():
            prefix_element = ''
            if self.prefix:
                prefix_element = self.prefix + '-'
            # On ``--override`` we clear stale images/mismatches but deliberately
            # KEEP existing ``.hash`` files: override is a *union* (see ``take``)
            # so regenerating on a second board (e.g. Pi 5 after Pi 4) adds that
            # board's hash to the file rather than wiping the first board's. To
            # reset a reference from scratch after a genuine visual change,
            # delete its ``.hash`` file by hand before regenerating.
            globs = (
                [
                    f'window-{prefix_element}*.png',
                    f'window-{prefix_element}*.mismatch.*',
                ]
                if override
                else [f'window-{prefix_element}*.mismatch.*']
            )
            for glob in globs:
                for file_path in self.results_dir.glob(glob):
                    file_path.unlink(missing_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def _capture_screenshot(self: WindowSnapshot) -> None:
        """Dispatch TakeScreenshotAction and wait for ScreenshotDataEvent.

        Re-dispatches on a fixed cadence until the GUI client answers (the
        action is edge-triggered and lost if sent before the client has
        subscribed). The first capture tolerates the one-time GUI cold-boot on
        slow hardware (e.g. a Raspberry Pi 4 under full-suite load); subsequent
        captures return as soon as the client renders. Raises ``TimeoutError``
        only if the client never responds within the (generous) ceiling.
        """
        from ubo_app.store.core.types import ScreenshotDataEvent, TakeScreenshotAction
        from ubo_app.store.main import store

        # Retry schedule = one ``TakeScreenshotAction`` dispatch per entry,
        # each followed by a wait of that many seconds for the
        # ``ScreenshotDataEvent``. ``TakeScreenshotAction`` is edge-triggered:
        # a dispatch sent before the GUI client has subscribed over gRPC is
        # simply missed — so we re-dispatch every 2s, catching the client the
        # moment it becomes ready (a couple of sparse dispatches would miss the
        # readiness window).
        #
        # The ceiling only bounds the *failure* path: on the happy path a
        # capture returns as soon as the event arrives, so a generous ceiling
        # costs nothing on success. It MUST be sized for the slowest hardware:
        # the first ever capture (``_latest_data is None``) pays the one-time
        # ``ubo-gui-client`` cold-boot (Kivy init + gRPC connect + first
        # render). On a Raspberry Pi 4 this now contends with the assistant +
        # mcp subprocesses cold-starting concurrently — pipecat import, Silero
        # VAD load, onnxruntime, and the full STT/TTS/LLM pipeline build — which
        # saturates the 4 cores for the first ~2 minutes. Measured first-capture
        # latency on a loaded Pi 4 is ~133s, so the cold ceiling is ~180s (Pi 5
        # / Ubuntu answer well inside the old 120s and are unaffected).
        # ``stability`` primes this first capture *before* starting its settle
        # deadline so the cold-boot isn't charged against the settle budget.
        # Once the client is warm every capture returns in well under a second;
        # the warm ceiling (~30s) is just a safety net for momentary load spikes.
        timeouts = [2] * 15 if self._latest_data is not None else [2] * 90

        for attempt, timeout in enumerate(timeouts):
            capture_event = threading.Event()

            def _on_screenshot_data(
                screenshot_event: ScreenshotDataEvent,
                _event: threading.Event = capture_event,
            ) -> None:
                self._latest_hash = screenshot_event.hash
                self._latest_data = screenshot_event.data
                _event.set()

            unsubscribe = store.subscribe_event(
                ScreenshotDataEvent,
                _on_screenshot_data,
            )

            store.dispatch(TakeScreenshotAction())
            capture_event.wait(timeout=timeout)
            unsubscribe()

            if capture_event.is_set():
                return

            if attempt < len(timeouts) - 1:
                continue

            msg = (
                f'Screenshot capture timed out after {len(timeouts)} attempts'
                f' (last timeout: {timeout}s)'
                ' - GUI is not responding. Check that the GUI'
                ' subprocess is running and connected via gRPC.'
            )
            raise TimeoutError(msg)

    @property
    def hash(self: WindowSnapshot) -> str:
        """Return the hash of the current window content."""
        self._capture_screenshot()
        if self._latest_hash is None:
            msg = 'No screenshot data available'
            raise RuntimeError(msg)
        return self._latest_hash

    def get_filename(self: WindowSnapshot, title: str | None) -> str:
        """Get the filename for the snapshot."""
        title_element = ''
        if title:
            title_element = title + '-'
        prefix_element = ''
        if self.prefix:
            prefix_element = self.prefix + '-'
        return (
            f"""window-{prefix_element}{title_element}{self.test_counter[title]:03d}"""
        )

    async def wait_for_render(
        self: WindowSnapshot,
        title: str | None = None,
        *,
        timeout: float = 30.0,  # noqa: ASYNC109
        poll_interval: float = 1.0,
    ) -> None:
        """Wait until the GUI-rendered window converges to a reference hash.

        Why this is needed (cross-process render-lag race)
        --------------------------------------------------
        The GUI runs in a SEPARATE process. Core state (e.g. a freshly
        registered ``wifi:state`` / ``audio:mic-state`` status icon) reaches it
        over a *latest-wins*, sequence-less gRPC channel, while the screenshot
        request rides a *separate, unordered* event stream. So a grab can be
        processed by the GUI BEFORE it applies the state update that adds an
        icon — the icon is in the core store (the test's ``wait_for`` barriers
        assert that) yet missing from the captured frame. ``stability`` doesn't
        catch it either: it settles when the window hash and the store snapshot
        are *each* independently stable, and the GUI can sit "stably lagged" on
        the pre-icon frame for the whole settle window.

        This barrier closes the gap from the test side: after the core store
        holds the icons, it polls the rendered window and returns as soon as the
        frame matches an accepted reference hash — i.e. the GUI has actually
        rendered the settled state. It is bounded and honest: on ``--override``
        (or with no reference yet) it is a no-op, and if the window never
        converges (a genuine regression, not just lag) it falls through after
        ``timeout`` so the subsequent ``take`` still fails with the real
        mismatch. It never turns a real failure into a pass.
        """
        if self.override:
            return
        filename = self.get_filename(title)
        hash_path = (self.results_dir / filename).with_suffix('.hash')
        if not hash_path.exists():
            return
        accepted = read_accepted_hashes(hash_path)
        if not accepted:
            return
        deadline = time.monotonic() + timeout
        while True:
            if self.hash in accepted:
                return
            if time.monotonic() >= deadline:
                return
            await asyncio.sleep(poll_interval)

    def take(self: WindowSnapshot, title: str | None = None) -> None:
        """Take a snapshot of the content of the window."""
        if self._is_closed:
            msg = (
                'Snapshot context is closed, make sure `window_snapshot` is before any '
                'fixture dispatching actions in the fixtures list'
            )
            raise RuntimeError(msg)

        self._capture_screenshot()

        filename = self.get_filename(title)
        path = Path(self.results_dir / filename)
        hash_path = path.with_suffix('.hash')
        image_path = path.with_suffix('.png')
        hash_mismatch_path = path.with_suffix('.mismatch.hash')
        image_mismatch_path = path.with_suffix('.mismatch.png')

        new_snapshot = self._latest_hash
        if new_snapshot is None:
            msg = 'No screenshot data available'
            raise RuntimeError(msg)

        # Why a ``.hash`` may hold MORE THAN ONE accepted hash
        # ----------------------------------------------------------------
        # ``rpi`` window snapshots are shared by every Raspberry Pi runner,
        # but the Pi 4 (VideoCore VI / V3D 4.2) and Pi 5 (VideoCore VII /
        # V3D 7.1) GPUs rasterise the *same* settled, pixel-identical scene a
        # single sub-pixel apart: one anti-aliased glyph-edge pixel comes out
        # one intensity level different (e.g. 236 vs 237). It is deterministic
        # per board, visually undetectable, and — unlike the genuine bugs we
        # already fixed (the texture-height-driven 1px text shift and the
        # screenshot render-thread race) — it is NOT removable in software:
        # the divergence is in the GPU's blend/rasteriser rounding, which the
        # GL spec does not pin down. Identical fonts, Mesa, SDL, layout and
        # capture path all verified. With exact-hash comparison one reference
        # can only ever satisfy one board, so the other ping-pongs to failure.
        # Accepting either board's deterministic hash is the minimal, honest
        # fix. ``divide_into_regions``-style tolerance was the alternative;
        # we keep exact hashing + a small accepted set so a real regression
        # (any *other* pixel changing) still fails loudly.
        if self.override:
            # Union: add this board's hash to the file, preserving any other
            # board's already-recorded hash (init keeps ``.hash`` on override).
            existing = (
                read_accepted_hashes(hash_path) if hash_path.exists() else []
            )
            accepted = (
                [*existing, new_snapshot]
                if new_snapshot not in existing
                else existing
            )
            hash_path.write_text(format_hash_file(filename, accepted))
            if self.make_screenshots and self._latest_data is not None:
                write_png(image_path, self._latest_data)
        else:
            accepted = (
                read_accepted_hashes(hash_path) if hash_path.exists() else []
            )
            if new_snapshot not in accepted:
                self._is_failed = True
                hash_mismatch_path.write_text(  # pragma: no cover
                    f'// MISMATCH: {filename}\n{new_snapshot}\n',
                )
                if self.make_screenshots and self._latest_data is not None:
                    write_png(image_mismatch_path, self._latest_data)
            elif self.make_screenshots and self._latest_data is not None:
                write_png(image_path, self._latest_data)
            assert new_snapshot in accepted, (
                f'Window snapshot mismatch - {filename} '
                f'(produced {new_snapshot}, accepted {accepted})'
            )

        self.test_counter[title] += 1

    def close(self: WindowSnapshot) -> None:
        """Close the snapshot context."""
        self._is_closed = True
        if self._is_failed:
            return
        for title in self.test_counter:
            filename = self.get_filename(title)
            hash_path = (self.results_dir / filename).with_suffix('.hash')

            assert not hash_path.exists(), f'Snapshot {filename} not taken'


@pytest.fixture
def snapshot_prefix() -> str:
    """Return the prefix for the snapshots."""
    from ubo_app.utils import IS_RPI

    if IS_RPI:
        return 'rpi'

    return 'desktop'


@pytest.fixture
def window_snapshot(
    request: SubRequest,
    snapshot_prefix: str | None,
) -> Generator[WindowSnapshot, None, None]:
    """Take a screenshot of the window via store event round-trip."""
    import os

    override = (
        request.config.getoption(
            '--override-window-snapshots',
            default=cast(
                'Any',
                str_to_bool(os.environ.get('UBO_TEST_OVERRIDE_SNAPSHOTS', 'false')),
            ),
        )
        is True
    )
    make_screenshots = (
        request.config.getoption(
            '--make-screenshots',
            default=cast(
                'Any',
                str_to_bool(os.environ.get('UBO_TEST_MAKE_SCREENSHOTS', 'false')),
            ),
        )
        is True
    )

    context = WindowSnapshot(
        test_id=request.node.nodeid,
        path=request.node.path,
        override=override,
        make_screenshots=make_screenshots,
        prefix=snapshot_prefix,
    )
    yield context
    context.close()
