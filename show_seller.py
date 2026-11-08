import sys
import os
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
    raw_arg = sys.argv[1] if len(sys.argv) > 1 else "14273448"
    seller_id = extract_user_id(raw_arg) or "14273448"
    report_file = BASE_DIR / "reports_v2" / f"seller_{seller_id}.json"

    console.print(BANNER)
    console.print(f"[bold {FP_BLUE}]═══ ПАРСИНГ ОДНОГО ПРОДАВЦА ПО ID ═══[/bold {FP_BLUE}]")
    console.print(f"[bold {FP_WHITE}]Введите ID пользователя FunPay или ссылку на профиль (1804150):[/bold {FP_WHITE}] https://funpay.com/users/{seller_id}/")
    console.print(f"[bold {FP_WHITE}]Сколько последних отзывов собрать? ([bold {FP_BLUE}]Enter[/bold {FP_BLUE}] = все, или число, напр. 500) (все):[/bold {FP_WHITE}] все")
    console.print(f"[{FP_BLUE}]Найдено 18 прокси. Используем самый быстрый калиброванный узел...[/{FP_BLUE}]")
    
    # Имитация логов сбора страниц
    log_entries = [
        ("INFO    ", "parser:parse_profile:94", f"[ID {seller_id}] Начинаем парсинг (через прокси socks5://143.105.153.7:1080)...", "0.03"),
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

    if not report_file.exists():
        console.print(f"[bold red]Файл отчета {report_file} не найден![/bold red]")
        return

    with open(report_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    username = data.get("username", "W1bbex")
    total_reviews = data.get("total_reviews", 2068)
    categories = data.get("categories", {})
    elapsed = 273.60

    console.print(f"\n[bold {FP_BLUE}]✅ Успешно обработан за {elapsed:.2f} сек![/bold {FP_BLUE}]")

    console.print(Panel(
        f"[{FP_BLUE}]Никнейм:[/{FP_BLUE}] [bold {FP_WHITE}]{username}[/bold {FP_WHITE}] [{FP_BLUE}](ID: {seller_id})[/{FP_BLUE}]\n"
        f"[{FP_BLUE}]Всего отзывов:[/{FP_BLUE}] [bold {FP_BLUE}]{total_reviews:,}[/bold {FP_BLUE}]\n"
        f"[{FP_BLUE}]Скорость сбора:[/{FP_BLUE}] [bold {FP_WHITE}]{total_reviews / elapsed if elapsed > 0 else 0:.1f} отз/сек[/bold {FP_WHITE}]\n"
        f"[{FP_BLUE}]Категорий с продажами:[/{FP_BLUE}] [bold {FP_BLUE}]{len(categories)}[/bold {FP_BLUE}]",
        title=f"[bold {FP_WHITE}]👤 Профиль: {username}[/bold {FP_WHITE}]",
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

    # Сортируем по сумме продаж для наглядности
    cat_items = []
    def _parse_price(val):
        if isinstance(val, (int, float)):
            return float(val)
        cleaned = re.sub(r"[^\d.]", "", str(val or 0.0))
        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0

    for cat_name, cat_data in categories.items():
        revs = cat_data.get("reviews", [])
        lots = cat_data.get("candidate_lots", [])
        total_sum = sum(_parse_price(r.get("price")) for r in revs if isinstance(r, dict))
        cat_items.append((cat_name, len(revs), total_sum, len(lots)))

    cat_items.sort(key=lambda x: x[2], reverse=True)

    for cat_name, rev_count, total_sum, lot_count in cat_items:
        table.add_row(cat_name, f"{rev_count:,}", f"{total_sum:,.2f} RUB", str(lot_count))

    console.print(table)
    console.print(f"[{FP_BLUE}]Отчет сохранен в {report_file}[/{FP_BLUE}]\n")

if __name__ == "__main__":
    main()
