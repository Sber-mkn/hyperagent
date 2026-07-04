import json
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()


def _s(ns: Any) -> str:
    return f"{(ns or 0) / 1e9:.2f}s"


_stream = {"mode": None}


def stream_print():

    def emit(chunk: str, mode: str, header: str, style: str) -> None:
        if _stream["mode"] != mode:
            if _stream["mode"] is not None:
                console.print()
            console.print(header)
            _stream["mode"] = mode
        console.print(chunk, end="", style=style, markup=False, highlight=False)

    def on_think(chunk: str) -> None:
        emit(chunk, "think", "[dim italic]🤔 Размышление[/dim italic]", "dim italic")

    def on_content(chunk: str) -> None:
        emit(chunk, "content", "[bold green]💬 Ответ[/bold green]", "")

    return on_think, on_content


_STYLES = {
    "оркестратор": "cyan", "рефлектор": "yellow",
    "именователь": "green", "инструмент": "magenta", "сводка": "dim",
}


def print_section(title: str) -> None:
    _stream["mode"] = None
    style = next((v for k, v in _STYLES.items() if k in title.lower()), "cyan")
    console.print()
    console.rule(f"[bold {style}]{title}[/bold {style}]", style=style)


def render_summary(msg, name: str) -> None:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column()

    tok = msg.tokens
    if tok:
        p, r = tok.prompt or 0, tok.response or 0
        grid.add_row("токены", f"prompt {p} · response {r} · всего {p + r}")
    dur = msg.duration
    if dur:
        total = (dur.load or 0) + (dur.prompt or 0) + (dur.response or 0)
        grid.add_row("время", f"load {_s(dur.load)} · prompt {_s(dur.prompt)} · "
                              f"gen {_s(dur.response)} · всего {_s(total)}")
    if msg.tool_calls:
        names = ", ".join(c.get("function", c).get("name", "?") for c in msg.tool_calls)
        grid.add_row("инструменты", f"[magenta]{names}[/magenta]")

    console.print()
    console.print(Panel(grid, title=f"[dim]Сводка · {name}[/dim]",
                        border_style="dim", expand=False))


def render_tool_call(name: str, args: Any, result: Any) -> None:
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            pass
    arg_str = json.dumps(args, ensure_ascii=False, indent=2) if isinstance(args, dict) else str(args)

    body = Group(
        Text("вход:", style="bold"),
        Syntax(arg_str, "json", theme="ansi_dark", word_wrap=True, background_color="default"),
        Text("\nвыход:", style="bold"),
        Text(str(result)),
    )
    console.print(Panel(body, title=f"🔧 [bold]{name}[/bold]", border_style="magenta", expand=True))


def render_final(state) -> None:
    chat = state["chat"]
    tp = sum((m.tokens.prompt or 0) for m in chat if m.tokens)
    tr = sum((m.tokens.response or 0) for m in chat if m.tokens)
    answer = state.get("answer") or next(
        (m.content for m in reversed(chat) if m.role == "assistant" and m.content), "(пусто)")
    accepted = state.get("accepted", True)
    color = "green" if accepted else "yellow"

    console.print()
    console.print(Panel(answer, title=f"[bold {color}]{state.get('title') or 'Ответ'}[/bold {color}]",
                        border_style=color, expand=True))
    if not accepted:
        console.print("[yellow]⚠ ответ не принят рефлектором — исчерпан лимит доработок[/yellow]")
    console.print(f"[dim]сообщений: {len(chat)}  ·  токенов всего: {tp}+{tr}={tp + tr}[/dim]")
