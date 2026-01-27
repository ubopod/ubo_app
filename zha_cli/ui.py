"""Terminal UI helpers using rich."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import IntPrompt, Prompt
from rich.table import Table

if TYPE_CHECKING:
    from zha_cli.coordinator_probe import DetectedCoordinator

console = Console()


def spinner(message: str) -> Progress:
    """Return a spinner context manager for loading screens."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}"),
        console=console,
        transient=True,
    )


def print_header(title: str) -> None:
    """Print a styled header."""
    console.print()
    console.print(Panel(title, style="bold blue"))


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[green]{message}[/green]")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[red]{message}[/red]")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]{message}[/yellow]")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[cyan]{message}[/cyan]")


def print_coordinators_table(coordinators: list[DetectedCoordinator]) -> None:
    """Display coordinators in a table."""
    table = Table(title="Detected Coordinators")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("Port", style="green")
    table.add_column("Description", style="white")
    table.add_column("Radio Type", style="yellow")
    table.add_column("Baudrate", style="magenta")

    for idx, coord in enumerate(coordinators, 1):
        table.add_row(
            str(idx),
            coord.port,
            coord.description,
            coord.radio_type.pretty_name,
            str(coord.baudrate),
        )

    console.print(table)


def print_devices_table(devices: list[dict[str, Any]]) -> None:
    """Display devices in a table."""
    table = Table(title="Paired Devices")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("IEEE", style="green")
    table.add_column("Manufacturer", style="white")
    table.add_column("Model", style="yellow")
    table.add_column("Name", style="magenta")
    table.add_column("Available", style="blue")

    for idx, device in enumerate(devices, 1):
        available = "[green]Yes[/green]" if device["available"] else "[red]No[/red]"
        table.add_row(
            str(idx),
            str(device["ieee"]),
            device["manufacturer"],
            device["model"],
            device["name"],
            available,
        )

    console.print(table)


def print_entities_table(entities: list[dict[str, Any]]) -> None:
    """Display entities in a table."""
    table = Table(title="Controllable Entities")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("Platform", style="green")
    table.add_column("Name", style="white")
    table.add_column("State", style="yellow")

    for idx, entity in enumerate(entities, 1):
        state_str = _format_entity_state(entity)
        table.add_row(
            str(idx),
            entity["platform"],
            entity.get("fallback_name") or entity.get("unique_id", "Unknown"),
            state_str,
        )

    console.print(table)


def _format_entity_state(entity: dict[str, Any]) -> str:
    """Format entity state for display."""
    state = entity.get("state", {})
    if "state" in state:
        return "[green]ON[/green]" if state["state"] else "[red]OFF[/red]"
    if "on" in state:
        return "[green]ON[/green]" if state["on"] else "[red]OFF[/red]"
    return "Unknown"


def prompt_menu(title: str, options: list[str]) -> int:
    """Display a menu and get user choice."""
    print_header(title)
    for idx, option in enumerate(options, 1):
        console.print(f"  [cyan]{idx}[/cyan]. {option}")
    console.print()

    while True:
        try:
            choice = IntPrompt.ask("Select option", default=1)
            if 1 <= choice <= len(options):
                return choice
            print_error(f"Please enter a number between 1 and {len(options)}")
        except KeyboardInterrupt:
            return 0


def prompt_confirm(message: str, default: bool = True) -> bool:
    """Prompt for confirmation."""
    default_str = "y" if default else "n"
    response = Prompt.ask(f"{message} [y/n]", default=default_str)
    return response.lower() in ("y", "yes")


def prompt_int(message: str, default: int | None = None) -> int:
    """Prompt for an integer."""
    return IntPrompt.ask(message, default=default)


def prompt_str(message: str, default: str | None = None) -> str:
    """Prompt for a string."""
    return Prompt.ask(message, default=default or "")
