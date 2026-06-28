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
    """Поиск в интернете через DuckDuckGo. Используй для проверки фактов (дата, версии, цены) и поиска документации.
    Возвращает список заголовков, ссылок и кратких сниппетов. Чтобы прочитать конкретную страницу целиком,
    передай её URL в fetch_url.

    Args:
        query: Поисковый запрос
        num_results: Количество результатов (по умолчанию 5)
    """
    try:
        from ddgs import DDGS
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
    """Выполняет команду в системной оболочке и возвращает stdout + stderr. Используй для установки зависимостей
    (pip install ...), запуска скриптов и файлов, операций с системой. Требует подтверждения пользователя.

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
def run_python(code: str, timeout: int = 120) -> str:
    """Выполняет Python-код в изолированном подпроцессе (тем же интерпретатором, sys.executable)
    и возвращает stdout+stderr или текст ошибки. Используй для запуска кода из generate_code и проверки
    результата. Результат виден, только если код печатает его через print().
    Изоляция в подпроцессе означает: блокирующий код прерывается по таймауту, а пакеты, только что
    установленные через run_bash (pip install), сразу видны. Состояние между вызовами не сохраняется.

    Args:
        code: Python-код для выполнения
        timeout: Таймаут в секундах (по умолчанию 120)
    """
    import sys
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        path = f.name

    try:
        result = subprocess.run(
            [sys.executable, path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if not output.strip():
            output = f"(код выполнен, код возврата {result.returncode}, вывод пустой)"
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return f"Ошибка: таймаут {timeout}с превышен"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


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


# ── generate_code ─────────────────────────────────────────────────────────────

_CODER_FORMAT = {
    "type": "object",
    "properties": {
        "realizable": {
            "type": "boolean",
            "description": "true если задача реализуема, false если нет"
        },
        "code": {
            "type": "string",
            "description": "Готовый код (заполни если realizable=true, иначе пустая строка)"
        },
        "reason": {
            "type": "string",
            "description": "Объяснение почему задача нереализуема (заполни если realizable=false, иначе пустая строка)"
        },
    },
    "required": ["realizable", "code", "reason"]
}

_CODER_SYSTEM = (
    "Ты — экспертная модель-кодер. Тебе передают структурированное техническое задание от оркестратора. "
    "Верни рабочий код строго по требованиям.\n\n"
    "Правила:\n"
    "- Пиши чистый, самодостаточный код: определи все нужные функции/классы, затем вызови точку входа и выведи "
    "результат через print(). Код запускается через exec(), поэтому без print() вывода не будет.\n"
    "- Не оставляй заглушек, TODO и псевдокода — реализуй задачу полностью.\n"
    "- Используй только стандартную библиотеку и то, что явно указано в требованиях. Если нужна внешняя "
    "библиотека — используй её, считая, что она установлена.\n"
    "- Если в требованиях передан текст ошибки прошлого запуска — найди причину и исправь её.\n"
    "- Считай примеры вход/выход контрактом: код обязан им соответствовать.\n"
    "- Если задача действительно нереализуема (внутренне противоречива или требует принципиально недоступных "
    "ресурсов) — верни realizable=false и объясни причину в reason; не выдумывай заведомо нерабочий код.\n\n"
    "Отвечай строго в формате JSON по заданной схеме, без какого-либо текста вне JSON."
)


def _build_coder_prompt(
    description: str,
    language: str,
    signature: str,
    requirements: str,
    examples: str,
) -> str:
    sections = [f"## Задача\n{description}"]
    if language:
        sections.append(f"## Язык\n{language}")
    if signature:
        sections.append(f"## Сигнатура / интерфейс\n```\n{signature}\n```")
    if requirements:
        sections.append(f"## Требования\n{requirements}")
    if examples:
        sections.append(f"## Примеры входа/выхода\n{examples}")
    return "\n\n".join(sections)


_coder_client = None

# Учёт токенов модели-кодера. Граф его не видит (вызов внутри инструмента),
# поэтому копим здесь; test.py сбрасывает перед задачей и читает после.
CODER_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}


def reset_coder_usage() -> None:
    for k in CODER_USAGE:
        CODER_USAGE[k] = 0


def _get_coder_client():
    global _coder_client
    if _coder_client is None:
        from agent.llminterface.clients.ollama_client import OllamaClient
        url = "http://localhost:11434/api/chat"
        _coder_client = OllamaClient(url, "nemotron-cascade-2:latest", temperature=0.2, num_ctx = 32768)
    return _coder_client


@agent_tool
def generate_code(
    description: str,
    language: str = "",
    signature: str = "",
    requirements: str = "",
    examples: str = "",
) -> str:
    """Делегирует написание кода специализированной модели-кодеру. Сам код не пиши — вызывай этот инструмент.
    Возвращает готовый самодостаточный код (с вызовом точки входа и выводом результата через print) либо
    объяснение, почему задача нереализуема. Чем точнее ТЗ, тем лучше результат.
    После получения кода запусти его через run_python или run_bash и проверь вывод; при ошибке вызови инструмент
    снова, передав текст ошибки в requirements.

    Args:
        description: Что нужно реализовать — чёткое и полное описание задачи
        language: Язык программирования (Python, C++, TypeScript, Go, ...). По умолчанию Python
        signature: Желаемая сигнатура функции/класса или интерфейс, который нужно реализовать
        requirements: Требования, ограничения, версии библиотек, а также текст ошибки прошлого запуска для исправления
        examples: Примеры входных данных и ожидаемого результата (контракт поведения)
    """
    import json

    prompt = _build_coder_prompt(description, language, signature, requirements, examples)
    messages = [
        {"role": "system", "content": _CODER_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    try:
        resp = _get_coder_client().chat(messages, format=_CODER_FORMAT, timeout=600)
    except Exception as e:
        return f"Ошибка при обращении к модели-кодеру: {e}"

    if resp.usage is not None:
        CODER_USAGE["prompt_tokens"] += getattr(resp.usage, "prompt_tokens", 0) or 0
        CODER_USAGE["completion_tokens"] += getattr(resp.usage, "completion_tokens", 0) or 0
        CODER_USAGE["total_tokens"] += getattr(resp.usage, "total_tokens", 0) or 0
        CODER_USAGE["calls"] += 1

    try:
        result = json.loads(resp.content)
    except json.JSONDecodeError as e:
        return f"Ошибка парсинга ответа модели: {e}\nСырой ответ: {resp.content[:500]}"

    if not result.get("realizable", True):
        return f"[нереализуемо] {result.get('reason', 'причина не указана')}"

    code = result.get("code", "").strip()
    if not code:
        return "Ошибка: модель вернула пустой код"
    return code


SAFE_TOOLS = [web_search, fetch_url, fetch_url_render, list_files, read_file, generate_code]
HUMAN_IN_LOOP_TOOLS = [run_bash, run_python, write_file, change_file]
ALL_TOOLS = SAFE_TOOLS + HUMAN_IN_LOOP_TOOLS
