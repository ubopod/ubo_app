"""CFFI bridge to libubo_lvgl.

Loads the C renderer shared library (ABI mode, no compile step) and marshals
Python view dataclasses into the C view-model structs declared in
``ubo_lvgl/include/ubo_lvgl.h``. The dataclasses below mirror that header; keep
them in sync with it (the header is the source of truth).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cffi import FFI

if TYPE_CHECKING:
    from collections.abc import Callable

# Mirrors ubo_lvgl/include/ubo_lvgl.h (subset needed by the bridge).
_CDEF = """
typedef enum {
    UBO_BACKEND_SDL=0, UBO_BACKEND_ST7789=1, UBO_BACKEND_BUFFER=2
} ubo_backend_t;

typedef struct {
    ubo_backend_t backend; int32_t width; int32_t height;
} ubo_lvgl_config;

typedef struct {
    const char *key; const char *label; const char *icon;
    const char *color; const char *background_color;
    bool is_short; bool is_selected;
} ubo_menu_item;

typedef struct {
    bool show_status_bar; const ubo_menu_item *items; int item_count;
    double cpu_percent; double ram_percent; double volume_level;
} ubo_home_view;

typedef struct {
    bool show_status_bar; const char *title; const char *heading;
    const char *sub_heading; const char *placeholder;
    const ubo_menu_item *items; int item_count;
    int page_index; int total_pages; int stack_depth;
} ubo_menu_view;

typedef struct {
    bool show_status_bar; const char *notification_id; const char *title;
    const char *content; const char *icon; const char *color;
    const ubo_menu_item *items; int item_count; int page_index; int total_pages;
} ubo_notification_view;

typedef struct {
    bool show_status_bar; const char *title; const char *instruction;
    const char *icon; bool spinner; const char *progress_text;
    const char *footer_text;
} ubo_instruction_view;

typedef struct {
    bool show_status_bar; const char *title; const char *prompt;
    const char *icon; const ubo_menu_item *items; int item_count;
} ubo_prompt_view;

typedef struct {
    bool show_status_bar; const char *application_id;
} ubo_application_view;

typedef struct { const char *key; const char *value; } ubo_render_prop;

typedef struct {
    bool show_status_bar; const char *kind; const char *title;
    const ubo_render_prop *props; int prop_count;
    const ubo_menu_item *items; int item_count; const char *stream_id;
} ubo_render_view;

typedef struct { const char *symbol; const char *color; } ubo_status_icon;

typedef struct {
    const char *id; bool has_progress; double progress; const char *color;
} ubo_progress_notification;

typedef struct {
    const char *title; bool is_recording; bool is_replaying;
    bool is_recording_audio; const ubo_progress_notification *progress_notifications;
    int progress_count; const char *clock; bool has_temperature; double temperature;
    bool has_light; double light_level; const ubo_status_icon *icons; int icon_count;
} ubo_status_bar;

typedef void (*ubo_input_cb)(const char *key, bool pressed, void *user);

int  ubo_lvgl_init(const ubo_lvgl_config *cfg);
void ubo_lvgl_set_input_cb(ubo_input_cb cb, void *user);
void ubo_lvgl_render_home(const ubo_home_view *v);
void ubo_lvgl_render_menu(const ubo_menu_view *v);
void ubo_lvgl_render_notification(const ubo_notification_view *v);
void ubo_lvgl_render_instruction(const ubo_instruction_view *v);
void ubo_lvgl_render_prompt(const ubo_prompt_view *v);
void ubo_lvgl_render_application(const ubo_application_view *v);
void ubo_lvgl_render_render(const ubo_render_view *v);
void ubo_lvgl_update_frame(const uint8_t *rgb, int32_t width, int32_t height);
void ubo_lvgl_set_status_bar(const ubo_status_bar *s);
void ubo_lvgl_set_blanked(bool blanked);
void ubo_lvgl_set_connected(bool connected);
void ubo_lvgl_set_disconnect_status(int attempt, int max_attempts, int seconds);
int  ubo_lvgl_run(bool threaded);
void ubo_lvgl_shutdown(void);
int  ubo_lvgl_snapshot(const char *path);
int  ubo_lvgl_get_framebuffer(const uint8_t **data, int32_t *width, int32_t *height);
"""

# Backend selector values (match the enum above).
BACKEND_SDL = 0
BACKEND_ST7789 = 1
BACKEND_BUFFER = 2


# --- Python view dataclasses (mirror the C structs) ------------------------


@dataclass
class MenuItem:
    """A selectable menu/action item (mirrors ubo_menu_item)."""

    key: str = ''
    label: str = ''
    icon: str | None = None
    color: str | None = None
    background_color: str | None = None
    is_short: bool = False
    is_selected: bool = False


@dataclass
class HomeView:
    """Home view: nav items, CPU/RAM gauges, volume (mirrors ubo_home_view)."""

    show_status_bar: bool = True
    items: list[MenuItem] = field(default_factory=list)
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    volume_level: float = 0.0


@dataclass
class MenuView:
    """Menu view: title/heading and paginated items (mirrors ubo_menu_view)."""

    show_status_bar: bool = True
    title: str = ''
    heading: str | None = None
    sub_heading: str | None = None
    placeholder: str | None = None
    items: list[MenuItem] = field(default_factory=list)
    page_index: int = 0
    total_pages: int = 1
    stack_depth: int = 1


@dataclass
class NotificationView:
    """Notification view (mirrors ubo_notification_view)."""

    show_status_bar: bool = True
    notification_id: str = ''
    title: str = ''
    content: str = ''
    icon: str | None = None
    color: str | None = None
    items: list[MenuItem] = field(default_factory=list)
    page_index: int = 0
    total_pages: int = 1


@dataclass
class InstructionView:
    """Instruction/waiting view (mirrors ubo_instruction_view)."""

    show_status_bar: bool = True
    title: str = ''
    instruction: str = ''
    icon: str | None = None
    spinner: bool = False
    progress_text: str | None = None
    footer_text: str | None = None


@dataclass
class PromptView:
    """Confirmation prompt view (mirrors ubo_prompt_view)."""

    show_status_bar: bool = True
    title: str = ''
    prompt: str = ''
    icon: str | None = None
    items: list[MenuItem] = field(default_factory=list)


@dataclass
class ApplicationView:
    """Application placeholder view (mirrors ubo_application_view)."""

    show_status_bar: bool = True
    application_id: str = ''


@dataclass
class RenderProp:
    """A generic render-widget property (mirrors ubo_render_prop)."""

    key: str = ''
    value: str = ''


@dataclass
class RenderView:
    """Generic render view (mirrors ubo_render_view)."""

    show_status_bar: bool = False
    kind: str = ''
    title: str = ''
    props: list[RenderProp] = field(default_factory=list)
    items: list[MenuItem] = field(default_factory=list)
    stream_id: str | None = None


@dataclass
class StatusIcon:
    """A status-bar icon (mirrors ubo_status_icon)."""

    symbol: str = ''
    color: str | None = None


@dataclass
class ProgressNotification:
    """A progress indicator in the status bar (mirrors ubo_progress_notification)."""

    id: str = ''
    progress: float | None = None
    color: str | None = None


@dataclass
class StatusBar:
    """Header/footer status data (mirrors ubo_status_bar)."""

    title: str = ''
    is_recording: bool = False
    is_replaying: bool = False
    is_recording_audio: bool = False
    progress_notifications: list[ProgressNotification] = field(default_factory=list)
    clock: str = ''
    temperature: float | None = None
    light_level: float | None = None
    icons: list[StatusIcon] = field(default_factory=list)


def _default_lib_path() -> str:
    env = os.environ.get('UBO_LVGL_LIB')
    if env:
        return env
    # ubo_app/gui/ubo_lvgl_gui_client/bridge.py -> repo root is 4 parents up.
    root = Path(__file__).resolve().parents[3]
    ext = 'dylib' if os.uname().sysname == 'Darwin' else 'so'
    return str(root / 'ubo_lvgl' / 'build' / f'libubo_lvgl.{ext}')


class Renderer:
    """Thin Pythonic wrapper around the libubo_lvgl C API."""

    def __init__(self, lib_path: str | None = None) -> None:
        """Load libubo_lvgl (ABI mode) and prepare the cdef interface."""
        # CFFI is dynamically typed; annotate as Any so the ABI calls and CData
        # field assignments below don't trip the type checker.
        self.ffi: Any = FFI()
        self.ffi.cdef(_CDEF)
        self.lib: Any = self.ffi.dlopen(lib_path or _default_lib_path())
        self._input_handle = None  # keep the cffi callback alive

    # -- lifecycle --
    def init(
        self,
        backend: int = BACKEND_SDL,
        width: int = 240,
        height: int = 240,
    ) -> None:
        """Initialize LVGL and the display backend."""
        # Point the C renderer at the icon-font assets unless already set.
        if 'UBO_LVGL_ASSETS_DIR' not in os.environ:
            root = Path(__file__).resolve().parents[3]
            os.environ['UBO_LVGL_ASSETS_DIR'] = str(root / 'ubo_lvgl' / 'assets')
        cfg = self.ffi.new(
            'ubo_lvgl_config*', {'backend': backend, 'width': width, 'height': height},
        )
        if self.lib.ubo_lvgl_init(cfg) != 0:
            msg = 'ubo_lvgl_init failed'
            raise RuntimeError(msg)

    def run(self, *, threaded: bool) -> None:
        """Run the LVGL loop (blocking unless threaded)."""
        self.lib.ubo_lvgl_run(threaded)

    def shutdown(self) -> None:
        """Stop the LVGL loop."""
        self.lib.ubo_lvgl_shutdown()

    def snapshot(self, path: str) -> None:
        """Write the current screen to a BMP (BACKEND_BUFFER only)."""
        if self.lib.ubo_lvgl_snapshot(path.encode()) != 0:
            msg = f'snapshot to {path} failed'
            raise RuntimeError(msg)

    def get_framebuffer(self) -> tuple[bytes, int, int]:
        """Return (rgb565_le_bytes, width, height) of the current screen."""
        pdata = self.ffi.new('const uint8_t**')
        pw = self.ffi.new('int32_t*')
        ph = self.ffi.new('int32_t*')
        if self.lib.ubo_lvgl_get_framebuffer(pdata, pw, ph) != 0:
            msg = 'framebuffer unavailable (needs BACKEND_BUFFER)'
            raise RuntimeError(msg)
        w = int(pw[0])
        h = int(ph[0])
        return bytes(self.ffi.buffer(pdata[0], w * h * 2)), w, h

    def set_input_callback(self, cb: Callable[[str, bool], None]) -> None:
        """Register a Python callable cb(key: str, pressed: bool)."""

        @self.ffi.callback('void(const char*, bool, void*)')
        def _trampoline(key, pressed, _user):  # noqa: ANN001, ANN202
            cb(self.ffi.string(key).decode(), bool(pressed))

        self._input_handle = _trampoline  # prevent GC
        self.lib.ubo_lvgl_set_input_cb(_trampoline, self.ffi.NULL)

    # -- marshalling helpers --
    def _s(self, value: str | None, keep: list) -> object:
        """Marshal a str (or None) to a C string, keeping it alive in `keep`."""
        if value is None:
            return self.ffi.NULL
        buf = self.ffi.new('char[]', value.encode('utf-8'))
        keep.append(buf)
        return buf

    def _items(self, items: list[MenuItem], keep: list) -> object:
        """Marshal a list of MenuItem to a C ubo_menu_item array."""
        arr = self.ffi.new('ubo_menu_item[]', len(items))
        keep.append(arr)
        for i, it in enumerate(items):
            arr[i].key = self._s(it.key, keep)
            arr[i].label = self._s(it.label, keep)
            arr[i].icon = self._s(it.icon, keep)
            arr[i].color = self._s(it.color, keep)
            arr[i].background_color = self._s(it.background_color, keep)
            arr[i].is_short = it.is_short
            arr[i].is_selected = it.is_selected
        return arr

    # -- render entry points --
    def render_home(self, v: HomeView) -> None:
        """Render the home view."""
        keep: list = []
        c = self.ffi.new('ubo_home_view*')
        c.show_status_bar = v.show_status_bar
        c.items = self._items(v.items, keep)
        c.item_count = len(v.items)
        c.cpu_percent = v.cpu_percent
        c.ram_percent = v.ram_percent
        c.volume_level = v.volume_level
        self.lib.ubo_lvgl_render_home(c)

    def render_menu(self, v: MenuView) -> None:
        """Render a menu view."""
        keep: list = []
        c = self.ffi.new('ubo_menu_view*')
        c.show_status_bar = v.show_status_bar
        c.title = self._s(v.title, keep)
        c.heading = self._s(v.heading, keep)
        c.sub_heading = self._s(v.sub_heading, keep)
        c.placeholder = self._s(v.placeholder, keep)
        c.items = self._items(v.items, keep)
        c.item_count = len(v.items)
        c.page_index = v.page_index
        c.total_pages = v.total_pages
        c.stack_depth = v.stack_depth
        self.lib.ubo_lvgl_render_menu(c)

    def render_notification(self, v: NotificationView) -> None:
        """Render a notification view."""
        keep: list = []
        c = self.ffi.new('ubo_notification_view*')
        c.show_status_bar = v.show_status_bar
        c.notification_id = self._s(v.notification_id, keep)
        c.title = self._s(v.title, keep)
        c.content = self._s(v.content, keep)
        c.icon = self._s(v.icon, keep)
        c.color = self._s(v.color, keep)
        c.items = self._items(v.items, keep)
        c.item_count = len(v.items)
        c.page_index = v.page_index
        c.total_pages = v.total_pages
        self.lib.ubo_lvgl_render_notification(c)

    def render_instruction(self, v: InstructionView) -> None:
        """Render an instruction view."""
        keep: list = []
        c = self.ffi.new('ubo_instruction_view*')
        c.show_status_bar = v.show_status_bar
        c.title = self._s(v.title, keep)
        c.instruction = self._s(v.instruction, keep)
        c.icon = self._s(v.icon, keep)
        c.spinner = v.spinner
        c.progress_text = self._s(v.progress_text, keep)
        c.footer_text = self._s(v.footer_text, keep)
        self.lib.ubo_lvgl_render_instruction(c)

    def render_prompt(self, v: PromptView) -> None:
        """Render a prompt view."""
        keep: list = []
        c = self.ffi.new('ubo_prompt_view*')
        c.show_status_bar = v.show_status_bar
        c.title = self._s(v.title, keep)
        c.prompt = self._s(v.prompt, keep)
        c.icon = self._s(v.icon, keep)
        c.items = self._items(v.items, keep)
        c.item_count = len(v.items)
        self.lib.ubo_lvgl_render_prompt(c)

    def render_application(self, v: ApplicationView) -> None:
        """Render an application placeholder view."""
        keep: list = []
        c = self.ffi.new('ubo_application_view*')
        c.show_status_bar = v.show_status_bar
        c.application_id = self._s(v.application_id, keep)
        self.lib.ubo_lvgl_render_application(c)

    def render_render(self, v: RenderView) -> None:
        """Render a generic RenderViewData widget (text/qr/status/...)."""
        keep: list = []
        props = self.ffi.new('ubo_render_prop[]', max(len(v.props), 1))
        keep.append(props)
        for i, p in enumerate(v.props):
            props[i].key = self._s(p.key, keep)
            props[i].value = self._s(p.value, keep)
        c = self.ffi.new('ubo_render_view*')
        c.show_status_bar = v.show_status_bar
        c.kind = self._s(v.kind, keep)
        c.title = self._s(v.title, keep)
        c.props = props
        c.prop_count = len(v.props)
        c.items = self._items(v.items, keep)
        c.item_count = len(v.items)
        c.stream_id = self._s(v.stream_id, keep)
        self.lib.ubo_lvgl_render_render(c)

    def update_frame(self, rgb: bytes, width: int, height: int) -> None:
        """Push a raw RGB888 frame into the current image/frame_stream view."""
        buf = self.ffi.new('uint8_t[]', rgb)
        self.lib.ubo_lvgl_update_frame(buf, width, height)

    def set_status_bar(self, s: StatusBar) -> None:
        """Update the header/footer status bar."""
        keep: list = []
        progress = self.ffi.new(
            'ubo_progress_notification[]', max(len(s.progress_notifications), 1),
        )
        keep.append(progress)
        for i, p in enumerate(s.progress_notifications):
            progress[i].id = self._s(p.id, keep)
            progress[i].has_progress = p.progress is not None
            progress[i].progress = p.progress or 0.0
            progress[i].color = self._s(p.color, keep)

        icons = self.ffi.new('ubo_status_icon[]', max(len(s.icons), 1))
        keep.append(icons)
        for i, ic in enumerate(s.icons):
            icons[i].symbol = self._s(ic.symbol, keep)
            icons[i].color = self._s(ic.color, keep)

        c = self.ffi.new('ubo_status_bar*')
        c.title = self._s(s.title, keep)
        c.is_recording = s.is_recording
        c.is_replaying = s.is_replaying
        c.is_recording_audio = s.is_recording_audio
        c.progress_notifications = progress
        c.progress_count = len(s.progress_notifications)
        c.clock = self._s(s.clock, keep)
        c.has_temperature = s.temperature is not None
        c.temperature = s.temperature or 0.0
        c.has_light = s.light_level is not None
        c.light_level = s.light_level or 0.0
        c.icons = icons
        c.icon_count = len(s.icons)
        self.lib.ubo_lvgl_set_status_bar(c)

    def set_blanked(self, blanked: bool) -> None:  # noqa: FBT001
        """Blank the display (black cover + backlight off)."""
        self.lib.ubo_lvgl_set_blanked(blanked)

    def set_connected(self, connected: bool) -> None:  # noqa: FBT001
        """Show/hide the disconnect overlay."""
        self.lib.ubo_lvgl_set_connected(connected)

    def set_disconnect_status(
        self,
        attempt: int,
        max_attempts: int,
        seconds: int,
    ) -> None:
        """Show the disconnect overlay with a reconnect countdown subtitle."""
        self.lib.ubo_lvgl_set_disconnect_status(attempt, max_attempts, seconds)
