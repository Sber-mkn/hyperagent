"""
Тестовый прогон агента: RUNS повторов × 3 задачи в каждом.

Структура результатов:
    test_runs/
        run_1/
            task1_weather/   ← excel + pdf + history.md
            task2_snake/     ← игра, текстуры + history.md
            task3_ml_repo/   ← датасет, ipynb, README + history.md
        run_2/ ...

В каждой папке задачи лежит history.md — полный транскрипт работы агента
(размышления, вызовы инструментов, ответы) + итог и вердикт рефлектора.
После всех прогонов печатается и сохраняется сводка test_runs/summary.md.

"""
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime

# чтобы запускалось и как `python agent/test.py`, и как `python -m agent.test`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import main as M
from agent.tools import computer_tools

# ── Настройки прогона ────────────────────────────────────────────────────────
RUNS = 5
BASE_DIR = Path(__file__).resolve().parent / "test_runs"
RECURSION_LIMIT = 80  # задачи длинные (github, ML) — поднимаем лимит шагов графа

# Автономный тест: иначе write_file/run_bash/change_file будут блокироваться на input().
# Снимаем human-in-the-loop подтверждение на время прогона.
computer_tools._confirm = lambda prompt: True

C = M.C  # ANSI-цвета


# ── Описание задач ───────────────────────────────────────────────────────────
def task_specs(run_idx: int, run_dir: Path) -> list[tuple[str, Path, str]]:
    """Возвращает [(имя_задачи, папка_задачи, промпт), ...] для одного прогона."""
    t1 = run_dir / "task1_weather"
    t2 = run_dir / "task2_snake"
    t3 = run_dir / "task3_ml_repo"
    return [
        (
            "task1_weather", t1,
            f"Определи мой текущий город. Создай Excel-файл с реальной температурой за каждый день "
            f"текущего года в этом городе. Дополнительно создай PDF-файл с графиком этой температуры. "
            f"Все итоговые файлы сохрани строго в папку {t1}. "
            f"В конце проверь, что оба файла реально созданы в этой папке.",
        ),
        (
            "task2_snake", t2,
            f"Напиши на Python игру «Змейка» с использованием pygame. У самой змейки и у еды должны быть "
            f"красивые текстуры — при необходимости скачай подходящие изображения текстур из интернета "
            f"и используй их как спрайты. Сохрани игру и все ресурсы (текстуры/спрайты) в папку {t2}, "
            f"точкой входа сделай файл {t2 / 'snake.py'}. Убедись, что игра импортируется/запускается без ошибок.",
        ),
        (
            "task3_ml_repo", t3,
            f"Создай на GitHub новый репозиторий с именем rep_test_{run_idx} (через gh CLI). "
            f"Тему датасета и тип модели выбери сам. Локально в папке {t3} подготовь содержимое проекта: "
            f"сам датасет для обучения, Jupyter-ноутбук (.ipynb) с небольшим разведочным анализом данных (EDA) "
            f"и обучением модели, а также README.md с описанием проекта и всеми необходимыми ссылками. "
            f"Закоммить и запушь всё содержимое в созданный репозиторий. Все файлы храни в {t3}. "
            f"В конце проверь, что репозиторий создан и пуш прошёл успешно.",
        ),
    ]


# ── Запись транскрипта (консоль + history.md) ────────────────────────────────
class Recorder:
    """Печатает поток графа в консоль (с цветом) и параллельно пишет plain-text в файл.
    Один и тот же экземпляр обрабатывает и токены стрима, и события инструментов,
    поэтому порядок в файле совпадает с реальным ходом выполнения."""

    def __init__(self, path: Path, task_prompt: str):
        self.fh = path.open("w", encoding="utf-8")
        self.cur_node = None
        self.cur_type = None
        self.fh.write(f"# Транскрипт задачи\n\n**Запущено:** {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
        self.fh.write(f"## Задача\n{task_prompt}\n")
        self.fh.flush()

    def _w(self, text: str) -> None:
        self.fh.write(text)
        self.fh.flush()

    def _node_header(self, node: str) -> None:
        color, label = M.NODE_STYLES.get(node, (C.CYAN, node.upper()))
        print(f"\n\n{color}{C.BOLD}━━━ {label} {'━' * max(4, 50 - len(label))}{C.RESET}")
        self._w(f"\n\n## {label}\n")

    def stream_chunk(self, node: str, chunk) -> None:
        if node != self.cur_node:
            self.cur_node, self.cur_type = node, None
            self._node_header(node)
        if chunk.type != self.cur_type:
            self.cur_type = chunk.type
            color = M.NODE_STYLES.get(node, (C.CYAN, node))[0]
            tag = "💭 размышляет" if chunk.type == "thinking" else "💬 отвечает"
            sub = C.GRAY if chunk.type == "thinking" else color
            print(f"\n{sub}{C.BOLD}  {tag}:{C.RESET}")
            self._w(f"\n### {tag}\n")
        body = C.GRAY if chunk.type == "thinking" else C.RESET
        print(f"{body}{chunk.text}{C.RESET}", end="", flush=True)
        self._w(chunk.text)

    def tool_event(self, event) -> None:
        if self.cur_node != "tools":
            self.cur_node, self.cur_type = "tools", None
            self._node_header("tools")
        import textwrap
        if event.is_call:
            args = ", ".join(f"{k}={textwrap.shorten(str(v), 60, placeholder='…')}"
                             for k, v in event.args.items())
            print(f"\n{C.YELLOW}  ▶ {C.BOLD}{event.name}{C.RESET}{C.YELLOW}({args}){C.RESET}", flush=True)
            self._w(f"\n▶ **{event.name}**({args})\n")
        elif event.error:
            print(f"{C.RED}  ✖ {event.name}: {event.error}{C.RESET}", flush=True)
            self._w(f"✖ {event.name}: {event.error}\n")
        else:
            preview = textwrap.shorten(str(event.result), 200, placeholder="…")
            print(f"{C.GREEN}  ✔ {preview}{C.RESET}", flush=True)
            self._w(f"✔ {preview}\n")

    def finish(self, summary: dict) -> None:
        self._w("\n\n## ИТОГ\n")
        self._w(f"\n**Время выполнения:** {summary.get('seconds', 0)} с\n")
        verdict = "одобрено" if summary.get("approved") else "требует доработки"
        self._w(f"**Вердикт рефлектора:** {verdict}\n\n")
        self._w((summary.get("answer") or "(пустой ответ)") + "\n")
        if summary.get("reflection"):
            self._w(f"\n_Комментарий рефлектора:_ {summary['reflection']}\n")
        if summary.get("error"):
            self._w(f"\n**ОШИБКА ПРОГОНА:** {summary['error']}\n")

    def close(self) -> None:
        self.fh.close()


# ── Один запуск одной задачи ─────────────────────────────────────────────────
def run_task(orchestrator, reflector, tools, prompt: str, task_dir: Path) -> dict:
    task_dir.mkdir(parents=True, exist_ok=True)
    rec = Recorder(task_dir / "history.md", prompt)
    summary = {"approved": None, "answer": "", "reflection": "", "error": None, "seconds": 0.0}

    graph = M.build_graph(orchestrator, reflector, tools=tools, on_tool_event=rec.tool_event)
    started = time.time()
    try:
        result = graph.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            stream_mode="messages",
            recursion_limit=RECURSION_LIMIT,
        )
        for node, chunk in result:
            rec.stream_chunk(node, chunk)

        state = result.state or {}
        summary["approved"] = bool(state.get("approved"))
        summary["answer"] = M.final_answer(state)
        summary["reflection"] = state.get("reflection", "")
    except Exception as e:
        summary["error"] = f"{type(e).__name__}: {e}"
        print(f"\n{C.RED}{C.BOLD}  ОШИБКА: {summary['error']}{C.RESET}", flush=True)
        traceback.print_exc()
    finally:
        summary["seconds"] = round(time.time() - started, 1)
        rec.finish(summary)
        rec.close()
    return summary


# ── Сводка по всем прогонам ──────────────────────────────────────────────────
def write_summary(results: list[tuple[int, str, dict]]) -> None:
    total = len(results)
    ok = sum(1 for _, _, s in results if s["approved"] and not s["error"])
    errored = sum(1 for _, _, s in results if s["error"])

    lines = [
        "# Сводка тестового прогона",
        f"\n**Дата:** {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"\n**Итого задач:** {total} | ✅ одобрено: {ok} | ⚠️ не одобрено: {total - ok - errored} | 💥 ошибки: {errored}",
        "\n| Прогон | Задача | Результат | Время, с | Комментарий рефлектора |",
        "|---|---|---|---|---|",
    ]
    for run_idx, name, s in results:
        if s["error"]:
            status = "💥 ошибка"
            note = s["error"]
        elif s["approved"]:
            status = "✅ одобрено"
            note = s["reflection"] or ""
        else:
            status = "⚠️ не одобрено"
            note = s["reflection"] or ""
        note = note.replace("\n", " ").replace("|", "\\|")[:160]
        lines.append(f"| {run_idx} | {name} | {status} | {s['seconds']} | {note} |")

    report = "\n".join(lines) + "\n"
    (BASE_DIR / "summary.md").write_text(report, encoding="utf-8")

    # Консольная версия — «расскажи как успехи»
    print(f"\n\n{C.GREEN}{C.BOLD}{'═' * 64}{C.RESET}")
    print(f"{C.GREEN}{C.BOLD}  📊 КАК УСПЕХИ: {ok}/{total} задач одобрено{C.RESET}")
    print(f"{C.GREEN}{C.BOLD}{'═' * 64}{C.RESET}")
    for run_idx, name, s in results:
        if s["error"]:
            mark, color = "💥", C.RED
        elif s["approved"]:
            mark, color = "✅", C.GREEN
        else:
            mark, color = "⚠️", C.YELLOW
        print(f"{color}  {mark} run {run_idx} / {name}  ({s['seconds']}с){C.RESET}")
        note = (s["error"] or s["reflection"] or "").replace("\n", " ")[:140]
        if note:
            print(f"{C.GRAY}      {note}{C.RESET}")
    print(f"\nПодробные транскрипты и файлы: {BASE_DIR}")
    print(f"Сводка сохранена в: {BASE_DIR / 'summary.md'}")


def main() -> None:
    M._enable_ansi()
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    orchestrator, reflector = M.make_clients()
    tools = M.TOOLS

    results: list[tuple[int, str, dict]] = []
    for run_idx in range(1, RUNS + 1):
        run_dir = BASE_DIR / f"run_{run_idx}"
        for name, task_dir, prompt in task_specs(run_idx, run_dir):
            print(f"\n\n{C.MAGENTA}{C.BOLD}{'#' * 64}{C.RESET}")
            print(f"{C.MAGENTA}{C.BOLD}#  ПРОГОН {run_idx}/{RUNS} — {name}{C.RESET}")
            print(f"{C.MAGENTA}{C.BOLD}{'#' * 64}{C.RESET}")
            summary = run_task(orchestrator, reflector, tools, prompt, task_dir)
            results.append((run_idx, name, summary))

    write_summary(results)


if __name__ == "__main__":
    main()
