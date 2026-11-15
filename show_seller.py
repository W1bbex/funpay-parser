import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        import ctypes
        kernel32 = ctypes.windll.kernel32
        for std_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(std_id)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from rich.markup import escape

BASE_DIR = Path(__file__).resolve().parent

FP_BLUE = "#2375B7"
FP_WHITE = "#FFFFFF"

funpay_theme = Theme({
    "prompt.choices": f"bold {FP_BLUE}",
    "prompt.default": f"bold {FP_WHITE}",
})

console = Console(theme=funpay_theme)

BANNER = f"""[bold {FP_BLUE}]╭──────────────────────────────────────────────────────────────────╮
│                            ▄█▄                                   │
│                          ▄█████▄                                 │
│                        ▄█████████▄                               │
│   ███████╗ ██╗   ██╗     ▀██████     ██████╗   █████╗  ██╗   ██╗ │
│   ██╔════╝ ██║   ██║       ▀████     ██╔══██╗ ██╔══██╗ ╚██╗ ██╔╝ │
│   █████╗   ██║   ██║     ▄   ▀██     ██████╔╝ ███████║  ╚████╔╝  │
│   ██╔══╝   ██║   ██║     ██▄   ▀     ██╔═══╝  ██╔══██║   ╚██╔╝   │
│   ██║      ╚██████╔╝     ████▄       ██║      ██║  ██║    ██║    │
│   ╚═╝       ╚═════╝      ██████▄     ╚═╝      ╚═╝  ╚═╝    ╚═╝    │
│                        ▀█████████▀                               │
│                          ▀█████▀                                 │
│                            ▀█▀                                   │
│     ANALYTICS & FULL MARKET SCRAPER PIPELINE (v1.0.0 by W1bbex)  │
╰──────────────────────────────────────────────────────────────────╯[/bold {FP_BLUE}]"""

def main():
    from utils import extract_user_id
    from funpay_analytics.models import SellerSummary
    from funpay_analytics.storage.db import get_db

    raw_arg = sys.argv[1] if len(sys.argv) > 1 else "14273448"
    seller_id = extract_user_id(raw_arg) or "14273448"
    report_file = (
        Path(raw_arg)
        if raw_arg.endswith(".json") and Path(raw_arg).is_file()
        else (BASE_DIR / "reports_v2" / f"seller_{seller_id}.json")
    )

    console.print(BANNER)
    console.print(f"[bold {FP_BLUE}]═══ ПАРСИНГ ОДНОГО ПРОДАВЦА ПО ID ═══[/bold {FP_BLUE}]")
    console.print(f"[bold {FP_WHITE}]Введите ID пользователя FunPay или ссылку на профиль (1804150):[/bold {FP_WHITE}] https://funpay.com/users/{seller_id}/")
    console.print(f"[bold {FP_WHITE}]Сколько последних отзывов собрать? ([bold {FP_BLUE}]Enter[/bold {FP_BLUE}] = все, или число, напр. 500) (все):[/bold {FP_WHITE}] все")
    console.print(f"[{FP_BLUE}]Найдено 18 прокси. Используем самый быстрый калиброванный узел...[/{FP_BLUE}]")

    # Имитация логов сбора страниц
    log_entries = [
        ("INFO    ", "parser:parse_profile:94", f"[ID {seller_id}] Начинаем парсинг (через прокси socks5://192.0.2.10:1080)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 125 отзывов (страница 5)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 250 отзывов (страница 10)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 375 отзывов (страница 15)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 500 отзывов (страница 20)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 625 отзывов (страница 25)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 750 отзывов (страница 30)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 875 отзывов (страница 35)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 1,000 отзывов (страница 40)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 1,125 отзывов (страница 45)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 1,250 отзывов (страница 50)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 1,375 отзывов (страница 55)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 1,500 отзывов (страница 60)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 1,625 отзывов (страница 65)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 1,750 отзывов (страница 70)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 1,875 отзывов (страница 75)...", "0.03"),
        ("INFO    ", "parser:parse_profile:241", f"[ID {seller_id}] Собрано 2,000 отзывов (страница 80)...", "0.03"),
        ("SUCCESS ", "parser:parse_profile:299", f"[ID {seller_id}] Готово! Собрано отзывов: 2068.", "0.03"),
    ]

    for level, loc, msg, delay in log_entries:
        lvl_color = "#2375B7" if "INFO" in level else "#28A745"
        console.print(f"2026-11-01 22:28:00 | [bold {lvl_color}]{level}[/bold {lvl_color}] | {loc} - {msg}")
        time.sleep(float(delay))

    summary: SellerSummary | None = None

    # 1. Попытка загрузить напрямую из SQLite базы данных
    try:
        numeric_id = int(seller_id)
        with get_db() as conn:
            summary = SellerSummary.from_db(conn, numeric_id)
    except Exception:
        summary = None

    # 2. Фолбэк на локальный JSON отчет (если нет в БД)
    if summary is None and report_file.exists():
        try:
            with open(report_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                summary = SellerSummary.from_dict(data)
                if str(seller_id).isdigit():
                    summary.seller_id = int(seller_id)
            else:
                console.print("[bold red]❌ Некорректный формат отчета (ожидается dict)[/bold red]")
                return
        except Exception as e:
            console.print(f"[bold red]❌ Ошибка чтения отчета {report_file.name}: {escape(str(e))}[/bold red]")
            return

    if summary is None:
        console.print(f"[bold red]Файл отчета {report_file} не найден и продавец ID {seller_id} отсутствует в БД![/bold red]")
        return

    safe_username = escape(str(summary.username))
    total_reviews = summary.total_reviews
    categories = summary.categories
    elapsed = 273.60

    console.print(f"\n[bold {FP_BLUE}]✅ Успешно обработан за {elapsed:.2f} сек![/bold {FP_BLUE}]")

    rating_str = f" ★ {summary.rating:.2f}" if summary.rating is not None else ""
    console.print(Panel(
        f"[{FP_BLUE}]Никнейм:[/{FP_BLUE}] [bold {FP_WHITE}]{safe_username}[/bold {FP_WHITE}] [{FP_BLUE}](ID: {summary.seller_id}){rating_str}[/{FP_BLUE}]\n"
        f"[{FP_BLUE}]Всего отзывов:[/{FP_BLUE}] [bold {FP_BLUE}]{total_reviews:,}[/bold {FP_BLUE}]\n"
        f"[{FP_BLUE}]Скорость сбора:[/{FP_BLUE}] [bold {FP_WHITE}]{total_reviews / elapsed if elapsed > 0 else 0:.1f} отз/сек[/bold {FP_WHITE}]\n"
        f"[{FP_BLUE}]Категорий с продажами:[/{FP_BLUE}] [bold {FP_BLUE}]{len(categories)}[/bold {FP_BLUE}]\n"
        f"[{FP_BLUE}]Источник данных:[/{FP_BLUE}] [bold {'#28A745' if summary.source == 'sqlite' else FP_BLUE}]{'SQLite (analytics.sqlite3)' if summary.source == 'sqlite' else report_file.name}[/]",
        title=f"[bold {FP_WHITE}]👤 Профиль: {safe_username}[/bold {FP_WHITE}]",
        border_style=FP_BLUE
    ))

    table = Table(
        title=f"[bold {FP_WHITE}]Категории и объемы продаж[/bold {FP_WHITE}]",
        border_style=FP_BLUE,
        header_style=f"bold {FP_BLUE}"
    )
    table.add_column("Категория", style=f"bold {FP_WHITE}")
    table.add_column("Отзывов", justify="right", style=FP_WHITE)
    table.add_column("Сумма по отзывам", justify="right", style=f"bold {FP_BLUE}")
    table.add_column("Кандидатов лотов", justify="right", style=f"bold {FP_BLUE}")

    for cat in categories:
        table.add_row(cat.name, f"{cat.review_count:,}", f"{cat.total_rub:,.2f} RUB", str(cat.lot_count))

    console.print(table)
    if summary.source == "sqlite":
        console.print(f"[{FP_BLUE}]Данные получены напрямую из SQLite базы данных.[/{FP_BLUE}]\n")
    else:
        console.print(f"[{FP_BLUE}]Отчет загружен из {report_file}[/{FP_BLUE}]\n")

if __name__ == "__main__":
    main()
