import os
import platform
import re
import shutil
import subprocess
import sys

from agent.tools.registry import tool, truncate_middle
from agent.tools import registry

MAX_LIMIT_CHARS = 20000  # потолок, выше которого limit не поднять ни одним инструментом — защита от совсем неадекватных запросов

def _find_bash() -> str:
    """На Windows голое имя 'bash' из PATH может резолвиться в лаунчер WSL
    (...\\WindowsApps\\bash.exe ИЛИ ...\\System32\\bash.exe — оба запускают
    `wsl bash`), даже если рядом стоит рабочий bash от Git for Windows. Это не
    просто "падает с ошибкой": WSL — совсем другая ФС и другой python3, чем
    тот, что использует run_python (sys.executable, обычный Windows-процесс).
    Инструменты молча расходятся по разным окружениям: pip install в run_bash
    ставит пакет в домашний каталог WSL, а run_python его не видит; пути вида
    /home/user, которые бы имели смысл в git-bash (общая с Windows ФС через
    /c/...), в WSL не существуют. Поэтому Git Bash ищем в первую очередь и
    явно отбрасываем WSL-заглушки при поиске по PATH."""
    if platform.system() != "Windows":
        return "bash"

    preferred = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
    ]
    for exe in preferred:
        if os.path.isfile(exe):
            return exe

    skip_markers = ("windowsapps", "system32", "syswow64", "sysnative")
    for p in os.environ.get("PATH", "").split(os.pathsep):
        exe = os.path.join(p, "bash.exe")
        if os.path.isfile(exe) and not any(m in exe.lower() for m in skip_markers):
            return exe

    return "bash"  # ничего не нашли — пробуем как есть, пусть падает с понятной ошибкой




def _html_to_text(html: str) -> str:
    """Вытащить видимый текст: убрать скрипты/стили/теги, схлопнуть пустоты.
    Так лимит расходуется на содержимое, а не на <head>/<script>."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "template", "svg", "head"]):
            tag.decompose()
        text = soup.get_text("\n")
    except ImportError:                                # fallback без bs4
        import html as _html
        html = re.sub(r"(?is)<(script|style|noscript|template|svg|head)\b.*?</\1>", " ", html)
        text = _html.unescape(re.sub(r"(?s)<[^>]+>", " ", html))
    lines = (ln.strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


@tool
def web_search(query: str, limit: int = 5) -> str:
    """Веб-поиск, возвращает несколько верхних результатов (заголовок + ссылка).

    Args:
        query: поисковый запрос.
        limit: сколько результатов вернуть.
    """
    from ddgs import DDGS
    from ddgs.exceptions import RatelimitException, TimeoutException, DDGSException

    try:
        hits = DDGS().text(query, max_results=limit)
    except RatelimitException:
        return "[web_search временно заблокирован поисковиком (rate limit), попробуй другой инструмент или повтори запрос позже]"
    except TimeoutException:
        return "[web_search: таймаут запроса, попробуй ещё раз]"
    except DDGSException as e:
        return f"[web_search недоступен: {e}]"

    if not hits:
        return "(ничего не найдено)"
    blocks = []
    for h in hits:
        block = f"{h['title']} — {h['href']}"
        body = (h.get("body") or "").strip()
        if body:
            block += f"\n    {body}"
        blocks.append(block)
    return "\n\n".join(blocks)


@tool
def fetch_url(url: str, limit: int = 4000) -> str:
    """HTTP GET по URL, вернуть видимый текст страницы (без разметки, усечённо).

    Для сайтов, где данные подгружаются через JS (напр. gismeteo), текста может
    почти не быть — тогда используй fetch_url_render.

    Args:
        url: адрес страницы.
        limit: максимум символов текста в ответе. По умолчанию небольшой, чтобы не раздувать контекст —
            если знаешь, что нужные данные не поместятся (большой JSON, длинная таблица и т.п.), смело
            увеличивай значение (до 20000).
    """
    import requests
    limit = min(limit, MAX_LIMIT_CHARS)
    r = requests.get(url, headers={"User-Agent": "agent/1.0"}, timeout=30)
    r.raise_for_status()
    text = _html_to_text(r.text)
    return truncate_middle(text, limit) if text else "(на странице нет текстового содержимого — вероятно, JS-рендеринг; попробуй fetch_url_render)"


@tool
def fetch_url_render(url: str, limit: int = 4000) -> str:
    """Загрузить страницу с рендерингом JS через headless-браузер.

    Args:
        url: адрес страницы.
        limit: максимум символов в ответе (см. fetch_url — до 20000 при необходимости).
    """
    limit = min(limit, MAX_LIMIT_CHARS)
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
    return truncate_middle(_html_to_text(html), limit)


@tool(default_target="client")
def ask_user(question: str) -> str:
    """Задать пользователю уточняющий вопрос и дождаться ответа.

    Используй этот инструмент только тогда, когда нужную информацию действительно невозможно получить другими
    инструментами (например, узнать личные предпочтения пользователя). Прежде чем спрашивать, попробуй сначала
    определить ответ сам: например, местоположение пользователя можно узнать по IP через run_python/web_search,
    не спрашивая об этом напрямую.

    Args:
        question: вопрос, который нужно задать пользователю.
    """
    if registry.on_ask_user is not None:
        return registry.on_ask_user(question)
    print(f"\n[Вопрос пользователю] {question}")
    return input("> ")


@tool
def list_files(path: str = ".") -> str:
    """Список файлов и папок по указанному пути.

    Args:
        path: путь к каталогу (по умолчанию текущий).
    """
    entries = sorted(os.listdir(path))
    return "\n".join(entries) if entries else "(пусто)"


@tool
def read_file(path: str, start: int = 1, end: int = 0) -> str:
    """Прочитать текстовый файл целиком или диапазон строк. Для больших файлов сначала вызови
    file_length, затем читай нужный диапазон строк по частям, а не весь файл сразу.

    Args:
        path: путь к файлу.
        start: номер первой строки для чтения (нумерация с 1, по умолчанию с начала файла).
        end: номер последней строки для чтения включительно (по умолчанию 0 — до конца файла).
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    end_idx = end if end > 0 else len(lines)
    return "".join(lines[max(start - 1, 0):end_idx])


@tool
def file_length(path: str) -> str:
    """Узнать количество строк и символов в файле — используй перед read_file, чтобы выбрать
    диапазон строк для чтения большого файла по частям.

    Args:
        path: путь к файлу.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return f"{lines} строк, {len(content)} символов"


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


def _bash_env() -> dict:
    """PATH для run_bash с каталогом текущего интерпретатора (sys.executable) первым —
    чтобы голые 'python'/'python3'/'pip' внутри run_bash резолвились в тот же Python,
    что использует run_python, а не в первый попавшийся на машине. Без этого пакет,
    поставленный через 'pip install' в run_bash, может быть не виден из run_python."""
    env = os.environ.copy()
    python_dir = os.path.dirname(sys.executable)
    env["PATH"] = os.pathsep.join([python_dir, os.path.join(python_dir, "Scripts"), env.get("PATH", "")])
    return env


@tool(default_target="client")
def run_bash(command: str, timeout: int = 60, limit: int = 4000) -> str:
    """Выполнить команду bash на машине пользователя и вернуть её вывод.

    Args:
        command: команда для оболочки bash.
        timeout: таймаут в секундах.
        limit: максимум символов вывода. По умолчанию небольшой — если ожидаешь длинный вывод,
            который весь тебе нужен (например, большой JSON), увеличивай значение (до 20000).
    """
    try:
        proc = subprocess.run(
            [_find_bash(), "-lc", command],
            capture_output=True, text=True, timeout=timeout, env=_bash_env(),
        )
    except FileNotFoundError:
        return "[run_bash недоступен: не найден рабочий bash]"
    out = (proc.stdout + proc.stderr).strip()
    out = out or f"(код возврата {proc.returncode})"
    if proc.returncode != 0:
        out = f"[exit {proc.returncode}] {out}"
    return truncate_middle(out, min(limit, MAX_LIMIT_CHARS))


def _find_powershell() -> str:
    """Предпочитаем pwsh (PowerShell 7+), но он не гарантированно установлен на
    машине пользователя — откатываемся на всегда присутствующий на Windows
    powershell.exe (5.1)."""
    return shutil.which("pwsh") or "powershell"


@tool(default_target="client")
def run_powershell(command: str, timeout: int = 60, limit: int = 4000) -> str:
    """Выполнить команду PowerShell на машине пользователя и вернуть её вывод.

    Args:
        command: команда для PowerShell.
        timeout: таймаут в секундах.
        limit: максимум символов вывода. По умолчанию небольшой — если ожидаешь длинный вывод,
            который весь тебе нужен (например, большой JSON), увеличивай значение (до 20000).
    """
    try:
        proc = subprocess.run(
            [_find_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return "[run_powershell недоступен: PowerShell не найден]"
    out = (proc.stdout + proc.stderr).strip()
    out = out or f"(код возврата {proc.returncode})"
    if proc.returncode != 0:
        out = f"[exit {proc.returncode}] {out}"
    return truncate_middle(out, min(limit, MAX_LIMIT_CHARS))


@tool(default_target="client")
def run_python(code: str, timeout: int = 60, limit: int = 4000) -> str:
    """Выполнить Python-код на машине пользователя и вернуть стандартный вывод.

    Args:
        code: исходный код на Python.
        timeout: таймаут в секундах.
        limit: максимум символов вывода. По умолчанию небольшой — если ожидаешь длинный вывод,
            который весь тебе нужен (например, большой JSON), увеличивай значение (до 20000).
    """
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=timeout,
    )
    out = (proc.stdout + proc.stderr).strip()
    out = out or "(нет вывода)"
    if proc.returncode != 0:
        out = f"[exit {proc.returncode}] {out}"
    return truncate_middle(out, min(limit, MAX_LIMIT_CHARS))


@tool
def version_commit(message: str):
    """Обновить текущую версию агента (аналогично последовательному выполнению команд "git add ." и "git commit -m '<message>'"). Данную функцию следует использовать после того, как ты изменил файлы на сервере:
    изменил инструменты, изменил код агента и так далее. После выполнения данной функции тебе станет доступна новая
    логика работы агента. Без выполнения функции version_commit все имзменения, которые ты делаешь на сервере не будут
    доступны.
    При выполнении данной функции автоматически проверяется синтаксис модулей на сервере. Если проверка не будет
    пройдена, то инструмент вернёт описание ошибки. Если версия сможет правильно обновиться, то тебе вернётся сообщение
    об успешном обновлении версии.

    Args:
        message: сообщение, которое описывает изменения в версии.
    """
    return registry.on_command({
        "type": "git",
        "command": {
            "command": "commit",
            "message": message
        }
    })

@tool
def version_status() -> str:
    """Выводит список изменённых файлов. Вывод состоит из двухбуквенных кодов, где первая буква — статус в индексе
    (Staged), а вторая — в рабочей директории.
    Первая буква (Индекс):
    - M — файл изменен и добавлен для коммита.
    - A — добавлен новый файл.
    - D — файл удален.
    Вторая буква (Рабочая директория):
    - M — изменен, но не добавлен в индекс.
    - D — удален, но удаление не добавлено в индекс.
    - ?? — неотслеживаемый (новый) файл.
    """
    return registry.on_command({
        "type": "git",
        "command": {
            "command": "status"
        }
    })


@tool
def version_diff():
    """Используется для сравнения изменений между различными состояниями версий агента: рабочим каталогом, индексом (staging) и коммитами. version_diff показывает, что ты изменил с момента последнего сохранения.
    Чтобы правильно читать вывод команды, ориентируйся на следующие условные обозначения:
    Основные маркеры изменений:
        --- a/файл — исходный файл, помеченный знаком минус (часто отображается как удаленный или старый).
        +++ b/файл — измененный файл, помеченный знаком плюс (новый или обновленный).
        - (строка) — строка была удалена из файла или изменена.
        + (строка) — строка была добавлена в файл.
    Заголовок блока (@@) обозначает начало нового измененного участка и выглядит, например, так:
        @@ -84,7 +84,5 @@
        Левая часть (-84,7): относится к исходному файлу. Показывает, что фрагмент начинается со строки номер 84 и включает в себя 7 строк.
        Правая часть (+84,5): относится к новому файлу. Показывает, что этот фрагмент начинается со строки 84 и охватывает уже 5 строк.
    """
    return registry.on_command({
        "type": "git",
        "command": {
            "command": "diff"
        }
    })


@tool
def version_diff_hash(_hash: str) -> str:
    """Используется для сравнения изменений между различными состояниями версий агента: рабочим каталогом, индексом
    (staging) и коммитами. version_diff_hash показывает изменения текущих файлов на сервере относительно файлов в
    заданной версии (определяется по хэшу).

    Чтобы правильно читать вывод команды, ориентируйся на следующие условные обозначения:

    Основные маркеры изменений:
        --- a/файл — исходный файл, помеченный знаком минус (часто отображается как удаленный или старый).

        +++ b/файл — измененный файл, помеченный знаком плюс (новый или обновленный).

        - (строка) — строка была удалена из файла или изменена.

        + (строка) — строка была добавлена в файл.

    Заголовок блока (@@) обозначает начало нового измененного участка и выглядит, например, так: @@ -84,7 +84,5 @@

        Левая часть (-84,7): относится к исходному файлу. Показывает, что фрагмент начинается со строки номер 84 и включает в себя 7 строк.

        Правая часть (+84,5): относится к новому файлу. Показывает, что этот фрагмент начинается со строки 84 и охватывает уже 5 строк.

    Args:
        _hash: хэш версии сервера (агента), с которой нужно сравнить текущую версию.
    """
    return registry.on_command({
        "type": "git",
        "command": {
            "command": "diff",
            "hash": _hash
        }
    })


@tool
def version_log() -> str:
    """Возвращает список версий агента в формате "<хэш версии> <описание изменений>". Все версии которые выводятся с помощью данного инструмента 100% являются стабильными.
    Данный инструмент следует использовать перед просмотром изменений относительно определённой версии (с помощью инструмента version_diff_hash) или для отката к определённой версии с помощью инструмента version_rollback.
    """
    return registry.on_command({
        "type": "git",
        "command": {
            "command": "log"
        }
    })


@tool
def version_rollback(_hash: str) -> str:
    """Позволяет откатить файлы сервера (агента) к состоянию определённой версии, которая задаётся с помощью хэша, получаемого из инструмента version_log.
    После применения version_rollback абсолютно все файлы на сервере будут соответствовать заданной стабильной версии.
    Следует использовать данный инструмент только в тех случаях, когда необходимо серьёзно откатить версию сервера для последующих изменений.

    Args:
        _hash: хэш версии сервера (агента), на которую следует откатиться.
    """
    return registry.on_command({
        "type": "git",
        "command": {
            "command": "rollback",
            "target_sha": _hash
        }
    })
