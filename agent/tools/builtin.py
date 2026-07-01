import os
import re
import subprocess
import sys

from agent.tools.registry import tool


@tool
def web_search(query: str, limit: int = 5) -> str:
    """Веб-поиск, возвращает несколько верхних результатов (заголовок + ссылка).

    Args:
        query: поисковый запрос.
        limit: сколько результатов вернуть.
    """
    import requests
    try:
        r = requests.get(
            "https://duckduckgo.com/html/", params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
        )
        r.raise_for_status()
    except Exception as e:
        return f"[web_search недоступен: {e}]"
    hits = re.findall(r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text)
    if not hits:
        return "(ничего не найдено)"
    lines = [f"{re.sub('<.*?>', '', title).strip()} — {url}" for url, title in hits[:limit]]
    return "\n".join(lines)


@tool
def fetch_url(url: str, limit: int = 4000) -> str:
    """HTTP GET по URL, вернуть текст страницы (усечённо).

    Args:
        url: адрес страницы.
        limit: максимум символов в ответе.
    """
    import requests
    r = requests.get(url, headers={"User-Agent": "agent/1.0"}, timeout=30)
    r.raise_for_status()
    return r.text[:limit]


@tool
def fetch_url_render(url: str, limit: int = 4000) -> str:
    """Загрузить страницу с рендерингом JS через headless-браузер.

    При отсутствии playwright деградирует до fetch_url.

    Args:
        url: адрес страницы.
        limit: максимум символов в ответе.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "[render недоступен: нет playwright] " + fetch_url(url, limit)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        html = page.content()
        browser.close()
    return html[:limit]


@tool
def list_files(path: str = ".") -> str:
    """Список файлов и папок по указанному пути.

    Args:
        path: путь к каталогу (по умолчанию текущий).
    """
    entries = sorted(os.listdir(path))
    return "\n".join(entries) if entries else "(пусто)"


@tool
def read_file(path: str) -> str:
    """Прочитать текстовый файл целиком.

    Args:
        path: путь к файлу.
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def write_file(path: str, content: str) -> str:
    """Записать текст в файл (перезаписывает существующий).

    Args:
        path: путь к файлу.
        content: содержимое для записи.
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Записано {len(content)} символов в {path}"


@tool
def change_file(path: str, old: str, new: str) -> str:
    """Заменить подстроку old на new в файле.

    Args:
        path: путь к файлу.
        old: искомая подстрока.
        new: чем заменить.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = f.read()
    if old not in data:
        return f"Подстрока не найдена в {path}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(data.replace(old, new))
    return f"Заменено в {path}"


@tool
def run_bash(command: str, timeout: int = 60) -> str:
    """Выполнить команду bash и вернуть её вывод.

    Args:
        command: команда для оболочки bash.
        timeout: таймаут в секундах.
    """
    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return "[run_bash недоступен: нет bash в PATH]"
    out = (proc.stdout + proc.stderr).strip()
    return out or f"(код возврата {proc.returncode})"


@tool
def run_python(code: str, timeout: int = 60) -> str:
    """Выполнить Python-код и вернуть стандартный вывод.

    Args:
        code: исходный код на Python.
        timeout: таймаут в секундах.
    """
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=timeout,
    )
    out = (proc.stdout + proc.stderr).strip()
    return out or "(нет вывода)"
