import platform
import shutil
import subprocess

from agent.tools.registry import tool


@tool(default_target="client")
def run_in_terminal(command: str) -> str:
    """Запустить команду в отдельном окне терминала на машине пользователя и сразу вернуть управление.

    Единственный способ запустить программу, с которой пользователь будет работать руками:
    обычный run_bash выполняется без терминала, и любой input() там сразу падает с EOFError.
    Здесь наоборот — открывается настоящее окно консоли, пользователь вводит в него что угодно,
    а окно остаётся открытым после завершения программы, чтобы он увидел результат.

    Вывод программы тебе не возвращается и не может быть возвращён: окно принадлежит пользователю.
    Инструмент отвечает сразу после запуска, не дожидаясь окончания работы. Если тебе нужен
    результат выполнения, это не тот инструмент — используй run_bash. Если нужен ответ человека,
    используй ask_user.

    Args:
        command: команда для запуска, например "python script.py".
    """
    if platform.system() == "Windows":
        subprocess.Popen(
            f'cmd /c "{command} & echo. & pause"',
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return f"Запущено в новом окне терминала: {command}"

    for terminal in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        if shutil.which(terminal):
            subprocess.Popen([terminal, "-e", f"sh -c '{command}; read -p \"\"'"])
            return f"Запущено в новом окне терминала: {command}"

    return "[run_in_terminal недоступен: не найден эмулятор терминала]"
