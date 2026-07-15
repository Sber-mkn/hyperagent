from agent.tools.registry import tool


@tool
def insert_text(path: str, content: str, line: int = 0) -> str:
    """Вставить текст в файл перед указанной строкой. Если line не указан — текст дописывается
    в конец файла.

    Args:
        path: путь к файлу.
        content: текст для вставки (перевод строки в конце добавляется автоматически, если его нет).
        line: номер строки, перед которой нужно вставить текст (нумерация с 1, как в read_file).
            По умолчанию 0 — дописать в конец файла.
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if content and not content.endswith("\n"):
        content += "\n"

    if 1 <= line <= len(lines):
        lines.insert(line - 1, content)
        where = f"строку {line}"
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(content)
        where = "конец файла"

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return f"Вставлено в {path} ({where})"
