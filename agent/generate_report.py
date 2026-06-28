"""Генерирует самодостаточный HTML-отчёт по прогонам из test_runs/.
Графики — инлайн-SVG (без внешних зависимостей). Запуск: python -m agent.generate_report"""
import re
import html
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent / "test_runs"
OUT = BASE / "report.html"

TASK_LABELS = {"task1_weather": "Погода", "task2_snake": "Змейка", "task3_ml_repo": "ML-репозиторий"}
TASK_COLORS = {"task1_weather": "#3b82f6", "task2_snake": "#22c55e", "task3_ml_repo": "#a855f7"}

REPOS = {  # известные репозитории
    "run_1": "https://github.com/putyatam/rep_test_1",
    "run_2": "https://github.com/putyatam/rep_test_2",
    "run_3": "https://github.com/putyatam/rep_test_3",
    "run_4": "https://github.com/putyatam/rep_test_4",
    "run_5": "https://github.com/putyatam/rep_test_5",
}


def field(t, p, cast=str, default=None):
    m = re.search(p, t)
    return cast(m.group(1)) if m else default


def parse_tokens(t):
    m = re.search(
        r"Токены:\*\*\s*всего\s*(\d+).*?оркестратор\+рефлектор:\s*(\d+)\s*за\s*(\d+).*?кодер:\s*(\d+)\s*за\s*(\d+)",
        t, re.DOTALL)
    if not m:
        return None
    return {"total": int(m.group(1)), "graph": int(m.group(2)), "graph_calls": int(m.group(3)),
            "coder": int(m.group(4)), "coder_calls": int(m.group(5))}


def collect():
    rows = []
    for run in sorted(BASE.glob("run_*")):
        for task in sorted(run.glob("task*")):
            h = task / "history.md"
            files = [p.name for p in task.iterdir() if p.name not in ("history.md", "__pycache__")]
            rec = {"run": run.name, "task": task.name, "files": files,
                   "time": None, "tokens": None, "verdict": "—", "error": None, "history": ""}
            if h.exists():
                t = h.read_text(encoding="utf-8", errors="replace")
                rec["history"] = t
                rec["time"] = field(t, r"Время выполнения:\*\*\s*([\d.]+)", float)
                rec["verdict"] = field(t, r"Вердикт рефлектора:\*\*\s*([^\n]+)", str, "—").strip()
                rec["error"] = field(t, r"ОШИБКА ПРОГОНА:\*\*\s*([^\n]+)", str)
                rec["tokens"] = parse_tokens(t)
            rows.append(rec)
    return rows


# ── SVG столбчатая диаграмма ──────────────────────────────────────────────────
def bar_chart(labels, values, colors, unit="", w=860, h=340, pad=70):
    if not values:
        return "<p>нет данных</p>"
    vmax = max(values) or 1
    n = len(values)
    plot_w = w - pad * 2
    plot_h = h - pad - 50
    bw = plot_w / n * 0.62
    gap = plot_w / n
    parts = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" class="chart">']
    # ось Y (4 деления)
    for i in range(5):
        y = pad + plot_h - plot_h * i / 4
        val = vmax * i / 4
        parts.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w-pad}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{pad-8}" y="{y+4:.1f}" text-anchor="end" class="ax">{val:,.0f}</text>')
    for i, (lab, val, col) in enumerate(zip(labels, values, colors)):
        x = pad + gap * i + (gap - bw) / 2
        bh = plot_h * (val / vmax)
        y = pad + plot_h - bh
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="{col}"><title>{lab}: {val:,.0f}{unit}</title></rect>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{y-6:.1f}" text-anchor="middle" class="val">{val:,.0f}</text>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{pad+plot_h+18:.1f}" text-anchor="middle" class="lab" transform="rotate(20 {x+bw/2:.1f} {pad+plot_h+18:.1f})">{html.escape(lab)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def main():
    rows = collect()
    delivered = sum(1 for r in rows if r["files"])
    total_tasks = len(rows)
    tok_total = sum(r["tokens"]["total"] for r in rows if r["tokens"])

    # успешность по типам
    types = ["task1_weather", "task2_snake", "task3_ml_repo"]
    type_delivered = {tt: sum(1 for r in rows if r["task"] == tt and r["files"]) for tt in types}
    type_count = {tt: sum(1 for r in rows if r["task"] == tt) for tt in types}

    # данные графиков
    time_rows = [r for r in rows if r["time"]]
    chart_time = bar_chart(
        [f'{r["run"].replace("run_","R")}·{TASK_LABELS[r["task"]]}' for r in time_rows],
        [round(r["time"] / 60, 1) for r in time_rows],
        [TASK_COLORS[r["task"]] for r in time_rows], unit=" мин")

    tok_rows = [r for r in rows if r["tokens"]]
    chart_tok = bar_chart(
        [f'{r["run"].replace("run_","R")}·{TASK_LABELS[r["task"]]}' for r in tok_rows],
        [r["tokens"]["total"] for r in tok_rows],
        [TASK_COLORS[r["task"]] for r in tok_rows], unit=" tok")

    chart_succ = bar_chart(
        [f'{TASK_LABELS[tt]} ({type_delivered[tt]}/{type_count[tt]})' for tt in types],
        [type_delivered[tt] for tt in types],
        [TASK_COLORS[tt] for tt in types], unit=" задач")

    def vbadge(v, files):
        if "одобрено" in v:
            return '<span class="b ok">одобрено</span>'
        if not files:
            return '<span class="b err">пусто</span>'
        return '<span class="b warn">требует доработки</span>'

    # ── сводная таблица ──
    trows = ""
    for r in rows:
        tok = f'{r["tokens"]["total"]:,}'.replace(",", " ") if r["tokens"] else "—"
        tm = f'{r["time"]/60:.1f} мин' if r["time"] else "—"
        files = ", ".join(html.escape(f) for f in r["files"]) or '<i>пусто</i>'
        deliv = "✅" if r["files"] else "❌"
        trows += (f"<tr><td>{r['run'].replace('run_','run ')}</td><td>{TASK_LABELS[r['task']]}</td>"
                  f"<td style='text-align:center'>{deliv}</td><td>{vbadge(r['verdict'], r['files'])}</td>"
                  f"<td style='text-align:right'>{tm}</td><td style='text-align:right'>{tok}</td>"
                  f"<td class='files'>{files}</td></tr>")

    # ── таблица токенов (раунд 2) ──
    tokrows = ""
    for r in tok_rows:
        d = r["tokens"]
        tokrows += (f"<tr><td>{r['run'].replace('run_','run ')}</td><td>{TASK_LABELS[r['task']]}</td>"
                    f"<td style='text-align:right'>{d['graph']:,}</td><td style='text-align:right'>{d['graph_calls']}</td>"
                    f"<td style='text-align:right'>{d['coder']:,}</td><td style='text-align:right'>{d['coder_calls']}</td>"
                    f"<td style='text-align:right'><b>{d['total']:,}</b></td></tr>").replace(",", " ")

    # ── история сообщений ──
    hist = ""
    for run in sorted({r["run"] for r in rows}):
        repo = REPOS.get(run, "")
        repo_link = f' · <a href="{repo}" target="_blank">{repo.split("/")[-1]}</a>' if repo else ""
        hist += f'<h3 class="runh">{run.replace("run_","Прогон ")}{repo_link}</h3>'
        for r in [x for x in rows if x["run"] == run]:
            size = len(r["history"])
            hist += (f'<details><summary>{TASK_LABELS[r["task"]]} '
                     f'<span class="muted">— {vbadge(r["verdict"], r["files"])} · {size//1024} КБ истории</span></summary>'
                     f'<pre class="hist">{html.escape(r["history"])}</pre></details>')

    note = ("Достоверны только вердикты <b>run_5</b> (исправленный код). "
            "run_1–3 искажены старым парсером JSON, run_4 — багом рефлектора (tools+format). "
            "Поэтому успех оценивается по <b>дедлайвереблам</b> (созданным файлам/репозиториям).")

    html_doc = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отчёт по тестированию агента</title>
<style>
 :root {{ --bg:#0f172a; --card:#1e293b; --txt:#e2e8f0; --mut:#94a3b8; --line:#334155; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; font-family:system-ui,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--txt); line-height:1.5; }}
 .wrap {{ max-width:1100px; margin:0 auto; padding:32px 20px 80px; }}
 h1 {{ font-size:28px; margin:0 0 4px; }}
 h2 {{ font-size:20px; margin:40px 0 14px; border-bottom:1px solid var(--line); padding-bottom:8px; }}
 h3.runh {{ font-size:17px; margin:26px 0 10px; color:#cbd5e1; }}
 .sub {{ color:var(--mut); margin:0 0 24px; }}
 .cards {{ display:flex; gap:14px; flex-wrap:wrap; margin:18px 0; }}
 .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 20px; flex:1; min-width:150px; }}
 .kpi .n {{ font-size:30px; font-weight:700; }}
 .kpi .l {{ color:var(--mut); font-size:13px; }}
 table {{ width:100%; border-collapse:collapse; background:var(--card); border-radius:10px; overflow:hidden; font-size:14px; }}
 th,td {{ padding:9px 12px; border-bottom:1px solid var(--line); text-align:left; }}
 th {{ background:#273449; font-weight:600; }}
 td.files {{ color:var(--mut); font-size:12px; max-width:260px; }}
 .b {{ padding:2px 9px; border-radius:20px; font-size:12px; font-weight:600; white-space:nowrap; }}
 .b.ok {{ background:#14532d; color:#86efac; }}
 .b.warn {{ background:#713f12; color:#fde68a; }}
 .b.err {{ background:#7f1d1d; color:#fca5a5; }}
 .chartbox {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; margin:14px 0; }}
 .chart {{ width:100%; height:auto; }}
 .chart .ax {{ fill:var(--mut); font-size:11px; }}
 .chart .val {{ fill:var(--txt); font-size:11px; font-weight:600; }}
 .chart .lab {{ fill:var(--mut); font-size:11px; }}
 .note {{ background:#1e293b; border-left:3px solid #f59e0b; padding:12px 16px; border-radius:6px; color:#cbd5e1; font-size:14px; }}
 details {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin:8px 0; }}
 summary {{ cursor:pointer; padding:10px 14px; font-weight:600; }}
 .muted {{ color:var(--mut); font-weight:400; }}
 pre.hist {{ max-height:480px; overflow:auto; margin:0; padding:14px; background:#0b1220; font-size:12px; line-height:1.45; white-space:pre-wrap; word-break:break-word; border-top:1px solid var(--line); }}
 a {{ color:#60a5fa; }}
</style></head><body><div class="wrap">
<h1>Отчёт по тестированию автономного агента</h1>
<p class="sub">Сформирован {datetime.now():%Y-%m-%d %H:%M} · 5 прогонов × 3 задачи (погода / змейка / ML-репозиторий)</p>

<div class="cards">
  <div class="kpi"><div class="n">{delivered}/{total_tasks}</div><div class="l">задач выдали результат</div></div>
  <div class="kpi"><div class="n">{type_delivered['task3_ml_repo']}/5</div><div class="l">репозиториев на GitHub</div></div>
  <div class="kpi"><div class="n">{tok_total:,}</div><div class="l">токенов (учёт в раунде 2)</div></div>
  <div class="kpi"><div class="n">{sum(r['time'] or 0 for r in rows)/3600:.1f} ч</div><div class="l">суммарное время</div></div>
</div>

<div class="note">{note}</div>

<h2>Сводная таблица</h2>
<table><thead><tr><th>Прогон</th><th>Задача</th><th>Файлы</th><th>Вердикт</th><th>Время</th><th>Токены</th><th>Созданные файлы</th></tr></thead>
<tbody>{trows}</tbody></table>

<h2>Диаграммы</h2>
<div class="chartbox"><b>Успешность по типам задач (создан результат)</b>{chart_succ}</div>
<div class="chartbox"><b>Время выполнения каждой задачи, мин</b>{chart_time}</div>
<div class="chartbox"><b>Расход токенов по задачам (раунд 2), tok</b>{chart_tok}</div>

<h2>Расходы токенов (раунд 2)</h2>
<table><thead><tr><th>Прогон</th><th>Задача</th><th>Оркестр.+рефлектор</th><th>вызовов</th><th>Кодер</th><th>вызовов</th><th>Всего</th></tr></thead>
<tbody>{tokrows}</tbody></table>
<p class="sub">Учёт токенов добавлен начиная с раунда 2 (run_4, run_5); в раунде 1 он ещё не велся. Самые дорогие — задачи-«змейки» (циклы рефлексий).</p>

<h2>История сообщений по прогонам</h2>
<p class="sub">Полный транскрипт каждой задачи (размышления, вызовы инструментов, ответы). Разверни нужную.</p>
{hist}

</div></body></html>"""

    OUT.write_text(html_doc, encoding="utf-8")
    print(f"Отчёт сохранён: {OUT}")
    print(f"Задач: {total_tasks}, с результатом: {delivered}, токенов (раунд 2): {tok_total:,}")


if __name__ == "__main__":
    main()
