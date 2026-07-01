import json
from typing import Any, Dict

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

console = Console()


def _fmt_dur(ns: Any) -> str:
    return f"{ns / 1e9:.2f}s" if ns else "—"


class StreamPrinter:

    def __init__(self, con: Console = console):
        self.console = con
        self.mode = None

    def _switch(self, mode: str, header: str) -> None:
        if self.mode == mode:
            return
        if self.mode is not None:
            self.console.print()
        self.console.print(header)
        self.mode = mode

    def on_think(self, s: str) -> None:
        self._switch("think", "[dim italic]🤔 размышление[/dim italic]")
        self.console.print(s, end="", style="dim italic", markup=False, highlight=False)

    def on_content(self, s: str) -> None:
        self._switch("content", "[bold]💬 ответ[/bold]")
        self.console.print(s, end="", markup=False, highlight=False)

    def done(self) -> None:
        if self.mode is not None:
            self.console.print()
            self.mode = None


def render_footer(msg, con: Console = console) -> None:
    parts = []
    if msg.model:
        parts.append(f"[cyan]{msg.model}[/cyan]")
    tok = msg.tokens
    if tok:
        p, r = tok.prompt or 0, tok.response or 0
        parts.append(f"токены {p}+{r}={p + r}")
    dur = msg.duration
    if dur:
        speed = ""
        if dur.response and tok and tok.response:
            speed = f" ({tok.response / (dur.response / 1e9):.1f} tok/s)"
        parts.append(
            f"load {_fmt_dur(dur.load)} · prompt {_fmt_dur(dur.prompt)} · gen {_fmt_dur(dur.response)}{speed}"
        )
    if msg.done_reason and msg.done_reason != "stop":
        parts.append(f"причина: {msg.done_reason}")
    if parts:
        con.print(Text("└─ ", style="dim") + Text.from_markup("[dim]" + "  ·  ".join(parts) + "[/dim]"))


def render_tool_call(name: str, args: Any, result: Any, con: Console = console) -> None:
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
    con.print(Panel(body, title=f"🔧 [bold]{name}[/bold]", border_style="magenta", expand=True))


def render_final(state: Dict[str, Any], con: Console = console) -> None:
    chat = state["chat"]
    tp = sum((m.tokens.prompt or 0) for m in chat if m.tokens)
    tr = sum((m.tokens.response or 0) for m in chat if m.tokens)
    answer = chat[-1].content or "(пусто)"

    con.print()
    con.print(Panel(
        answer,
        title=f"[bold green]{state.get('title') or 'Ответ'}[/bold green]",
        border_style="green", expand=True,
    ))
    con.print(f"[dim]сообщений: {len(chat)}  ·  токенов всего: {tp}+{tr}={tp + tr}[/dim]")
