import os
import subprocess
import textwrap
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from agent.llminterface.agentgraph.tool import agent_tool


def _confirm(prompt: str) -> bool:
    """Запрашивает подтверждение у пользователя. Возвращает True если согласен."""
    answer = input(f"\n[human-in-loop] {prompt}\nПродолжить? [y/N]: ").strip().lower()
    return answer in ("y", "yes", "д", "да")


def _truncate(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [обрезано, всего {len(text)} символов]"


@agent_tool
def web_search(query: str, num_results: int = 5) -> str:
    """Поиск в интернете через DuckDuckGo. Возвращает список заголовков и ссылок.

    Args:
        query: Поисковый запрос
        num_results: Количество результатов (по умолчанию 5)
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "Ошибка: установите библиотеку duckduckgo-search (pip install duckduckgo-search)"

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=num_results):
            results.append(f"- [{r['title']}]({r['href']})\n  {r['body']}")

    return "\n\n".join(results) if results else "Результаты не найдены"


@agent_tool
def fetch_url(url: str) -> str:
    """Загружает содержимое страницы по URL и возвращает сырой текст (без рендеринга JS).

    Args:
        url: URL страницы
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return "Ошибка: установите requests и beautifulsoup4"

    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return _truncate(text)


@agent_tool
def fetch_url_render(url: str) -> str:
    """Загружает страницу с рендерингом JavaScript через Playwright.
    Используй вместо fetch_url когда контент загружается динамически.

    Args:
        url: URL страницы
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Ошибка: установите playwright (pip install playwright && playwright install chromium)"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        text = page.inner_text("body")
        browser.close()

    return _truncate(text)


@agent_tool
def list_files(path: str = ".", pattern: str = "**/*") -> str:
    """Возвращает список файлов в директории.

    Args:
        path: Путь к директории (по умолчанию текущая)
        pattern: Glob-паттерн для фильтрации (по умолчанию все файлы)
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return f"Ошибка: путь не существует: {root}"
    if not root.is_dir():
        return f"Ошибка: {root} — не директория"

    files = sorted(root.glob(pattern))
    if not files:
        return "Файлы не найдены"

    lines = []
    for f in files:
        rel = f.relative_to(root)
        tag = "/" if f.is_dir() else ""
        lines.append(f"{rel}{tag}")

    return "\n".join(lines)


@agent_tool
def read_file(path: str, encoding: str = "utf-8") -> str:
    """Читает содержимое файла и возвращает его текст.

    Args:
        path: Путь к файлу
        encoding: Кодировка файла (по умолчанию utf-8)
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"Ошибка: файл не найден: {p}"
    if not p.is_file():
        return f"Ошибка: {p} — не файл"

    try:
        content = p.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return f"Ошибка: не удалось прочитать файл в кодировке {encoding}"

    return _truncate(content)


@agent_tool
def run_bash(command: str, timeout: int = 30) -> str:
    """Выполняет bash-команду в оболочке и возвращает stdout + stderr.

    Args:
        command: Команда для выполнения
        timeout: Таймаут в секундах (по умолчанию 30)
    """

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, timeout=timeout
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if not output.strip():
            output = f"(команда завершилась с кодом {result.returncode}, вывод пустой)"
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return f"Ошибка: таймаут {timeout}с превышен"


@agent_tool
def run_python(code: str) -> str:
    """Выполняет Python-код и возвращает вывод (stdout) или ошибку.

    Args:
        code: Python-код для выполнения
    """

    preview = textwrap.indent(textwrap.shorten(code, width=200, placeholder="..."), "  ")

    import io
    import sys

    stdout_capture = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_capture

    try:
        local_ns: dict = {}
        exec(compile(code, "<agent>", "exec"), local_ns)  # noqa: S102
        output = stdout_capture.getvalue()
        return _truncate(output) if output.strip() else "(код выполнен, вывод пустой)"
    except Exception as e:
        return f"Ошибка: {type(e).__name__}: {e}"
    finally:
        sys.stdout = old_stdout


@agent_tool
def write_file(path: str, content: str, encoding: str = "utf-8") -> str:
    """Записывает текст в файл, создавая промежуточные директории при необходимости.

    Args:
        path: Путь к файлу
        content: Содержимое для записи
        encoding: Кодировка (по умолчанию utf-8)
    """

    p = Path(path).expanduser().resolve()
    action = "Перезаписать" if p.exists() else "Создать"
    preview = textwrap.shorten(content, width=120, placeholder="...")

    if not _confirm(f'{action} файл: {p}\nПервые символы:\n  "{preview}"'):
        return "Отменено пользователем"

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)
    return f"Файл записан: {p} ({len(content)} символов)"


@agent_tool
def change_file(path: str, old: str, new: str, encoding: str = "utf-8") -> str:
    """Заменяет точное вхождение текста в файле. Фрагмент old должен встречаться ровно один раз.

    Args:
        path: Путь к файлу
        old: Фрагмент текста, который нужно заменить (должен совпадать дословно)
        new: Текст, на который заменяется фрагмент
        encoding: Кодировка файла (по умолчанию utf-8)
    """
    import difflib

    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"Ошибка: файл не найден: {p}"
    if not p.is_file():
        return f"Ошибка: {p} — не файл"

    try:
        original = p.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return f"Ошибка: не удалось прочитать файл в кодировке {encoding}"

    count = original.count(old)
    if count == 0:
        return "Ошибка: фрагмент old не найден в файле"
    if count > 1:
        return f"Ошибка: фрагмент old найден {count} раза(з) — укажите более уникальный фрагмент"

    updated = original.replace(old, new, 1)

    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{p.name}",
        tofile=f"b/{p.name}",
        lineterm="",
    )
    diff_text = "".join(list(diff)[:60])

    p.write_text(updated, encoding=encoding)
    return f"Файл изменён: {p}"


SAFE_TOOLS = [web_search, fetch_url, fetch_url_render, list_files, read_file]
HUMAN_IN_LOOP_TOOLS = [run_bash, run_python, write_file, change_file]
ALL_TOOLS = SAFE_TOOLS + HUMAN_IN_LOOP_TOOLS
