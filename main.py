# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import asyncio
import subprocess
import re
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

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.theme import Theme

from curl_cffi import requests
from utils import atomic_write_json, get_browser_for_proxy, extract_user_id
from parser import parse_profile, ping_and_rank, load_proxies
import fetch_ids

FP_BLUE = "#2375B7"
FP_WHITE = "#FFFFFF"

funpay_theme = Theme({
    "prompt.choices": f"bold {FP_BLUE}",
    "prompt.default": f"bold {FP_WHITE}",
})
console = Console(
    highlight=False,
    theme=funpay_theme,
    color_system="truecolor",
    legacy_windows=False
)

def show_banner():
    print("\033[2J\033[H", end="", flush=True)
    f_u = [
        "  ███████╗ ██╗   ██╗",
        "  ██╔════╝ ██║   ██║",
        "  █████╗   ██║   ██║",
        "  ██╔══╝   ██║   ██║",
        "  ██║      ╚██████╔╝",
        "  ╚═╝       ╚═════╝ "
    ]
    arr = [
        "    ▄█▄    ",
        "  ▄█████▄  ",
        "▄█████████▄",
        "  ▀██████  ",
        "    ▀████  ",
        "  ▄   ▀██  ",
        "  ██▄   ▀  ",
        "  ████▄    ",
        "  ██████▄  ",
        "▀█████████▀",
        "  ▀█████▀  ",
        "    ▀█▀    "
    ]
    p_a_y = [
        "██████╗   █████╗  ██╗   ██╗",
        "██╔══██╗ ██╔══██╗ ╚██╗ ██╔╝",
        "██████╔╝ ███████║  ╚████╔╝ ",
        "██╔═══╝  ██╔══██║   ╚██╔╝  ",
        "██║      ██║  ██║    ██║   ",
        "╚═╝      ╚═╝  ╚═╝    ╚═╝   "
    ]
    indent = " " * 23
    lines = [
        f"{indent}[bold {FP_BLUE}]{arr[0]}[/bold {FP_BLUE}]",
        f"{indent}[bold {FP_BLUE}]{arr[1]}[/bold {FP_BLUE}]",
        f"{indent}[bold {FP_BLUE}]{arr[2]}[/bold {FP_BLUE}]"
    ]
    for i in range(6):
        lines.append(
            f"[bold {FP_WHITE}]{f_u[i]}[/bold {FP_WHITE}]   "
            f"[bold {FP_BLUE}]{arr[i+3]}[/bold {FP_BLUE}]   "
            f"[bold {FP_BLUE}]{p_a_y[i]}[/bold {FP_BLUE}]"
        )
    lines.extend([
        f"{indent}[bold {FP_BLUE}]{arr[9]}[/bold {FP_BLUE}]",
        f"{indent}[bold {FP_BLUE}]{arr[10]}[/bold {FP_BLUE}]",
        f"{indent}[bold {FP_BLUE}]{arr[11]}[/bold {FP_BLUE}]",
        f"    [bold {FP_WHITE}]ANALYTICS & FULL MARKET SCRAPER PIPELINE[/bold {FP_WHITE}] [{FP_BLUE}](v1.0.0 by W1bbex)[/{FP_BLUE}]"
    ])
    banner_text = "\n".join(lines)
    console.print(Panel(banner_text, border_style=FP_BLUE, expand=False))

def show_market_analytics():
    report_file = BASE_DIR / "market_report_v2.json"
    if not report_file.exists():
        report_file = BASE_DIR / "market_report.json"
    if not report_file.exists():
        report_file = BASE_DIR / "examples" / "market_report.example.json"
        
    if not report_file.exists():
        console.print(f"[bold {FP_WHITE}]❌ Файл отчета market_report.json / market_report_v2.json не найден![/bold {FP_WHITE}]")
        input("\nНажмите Enter для возврата в меню...")
        return

    try:
        data = json.loads(report_file.read_text(encoding="utf-8"))
    except Exception:
        console.print(f"[bold {FP_WHITE}]❌ Ошибка чтения отчета[/bold {FP_WHITE}]")
        input("\nНажмите Enter...")
        return
        
    total_sellers = len(data)
    total_reviews = sum(x.get("total_reviews", 0) for x in data)
    
    categories = {}
    total_earned = 0.0
    for s in data:
        s_earned = s.get("total_earned")
        calc_s_earned = 0.0
        for cat, c_data in s.get("categories", {}).items():
            if cat not in categories:
                categories[cat] = {"count": 0, "earned": 0.0}
            
            # v1 schema: {"count": ..., "earned": ...}
            if "count" in c_data or "earned" in c_data:
                cnt = c_data.get("count", 0)
                ernd = c_data.get("earned", 0.0)
            # v2 schema: {"reviews": [...], "candidate_lots": [...]}
            elif "reviews" in c_data:
                revs = c_data.get("reviews", [])
                cnt = len(revs)
                ernd = sum(float(r.get("price") or 0.0) for r in revs if isinstance(r, dict))
            else:
                cnt = 0
                ernd = 0.0
                
            categories[cat]["count"] += cnt
            categories[cat]["earned"] += ernd
            calc_s_earned += ernd

        if s_earned is not None:
            total_earned += s_earned
        else:
            total_earned += calc_s_earned

    console.print(Panel(
        f"[{FP_BLUE}]Всего продавцов в базе:[/{FP_BLUE}] [bold {FP_WHITE}]{total_sellers}[/bold {FP_WHITE}]\n"
        f"[{FP_BLUE}]Собрано и обработано отзывов:[/{FP_BLUE}] [bold {FP_WHITE}]{total_reviews:,}[/bold {FP_WHITE}]\n"
        f"[{FP_BLUE}]Оцененный суммарный оборот:[/{FP_BLUE}] [bold {FP_BLUE}]{total_earned:,.2f} RUB[/bold {FP_BLUE}]",
        title=f"[bold {FP_WHITE}]📊 Глобальная сводка маркетплейса[/bold {FP_WHITE}]",
        border_style=FP_BLUE
    ))

    table = Table(
        title=f"[bold {FP_WHITE}]🏆 Топ-12 категорий по обороту[/bold {FP_WHITE}]",
        border_style=FP_BLUE,
        header_style=f"bold {FP_BLUE}"
    )
    table.add_column("№", justify="right", style=FP_BLUE)
    table.add_column("Категория", style=f"bold {FP_WHITE}")
    table.add_column("Отзывов", justify="right", style=FP_WHITE)
    table.add_column("Оборот (выручка)", justify="right", style=f"bold {FP_BLUE}")

    top_cats = sorted(categories.items(), key=lambda x: x[1]["earned"], reverse=True)[:12]
    for i, (c_name, c_stats) in enumerate(top_cats, 1):
        table.add_row(str(i), c_name, f"{c_stats['count']:,}", f"{c_stats['earned']:,.2f} RUB")

    console.print(table)
    input("\nНажмите Enter для возврата в меню...")

async def run_full_pipeline():
    try:
        console.print(f"\n[bold {FP_BLUE}]═══ ПОЛНЫЙ ЦИКЛ ПАРСИНГА РЫНКА (RMTHub ➔ FunPay ➔ Отчет) ═══[/bold {FP_BLUE}]\n")
        
        queue_file = BASE_DIR / "queue.txt"
        has_queue = queue_file.exists() and queue_file.stat().st_size > 0
        refetch = True
        
        if has_queue:
            with open(queue_file, "r", encoding="utf-8") as f:
                q_count = len([line for line in f if line.strip()])
            console.print(f"[{FP_BLUE}]Найдена готовая очередь:[/{FP_BLUE}] [bold {FP_WHITE}]{q_count}[/bold {FP_WHITE}] [{FP_BLUE}]продавцов в queue.txt[/{FP_BLUE}]")
            refetch = not Confirm.ask(f"[{FP_WHITE}]Использовать текущую очередь продавцов?[/{FP_WHITE}]", default=True)

        if refetch:
            console.print(f"\n[bold {FP_BLUE}]1. Сбор топа продавцов с RMTHub...[/bold {FP_BLUE}]")
            target = Prompt.ask(f"[{FP_WHITE}]Сколько топ-продавцов собрать с RMTHub?[/{FP_WHITE}]", default="100")
            try:
                target_count = int(target)
            except Exception:
                target_count = 100
                
            pages = max(1, (target_count + 19) // 20)
            console.print(f"[{FP_BLUE}]Стягиваем {pages} страниц с rmthub.com...[/{FP_BLUE}]")
            await fetch_ids.main(target_count=target_count)

        console.print(f"\n[bold {FP_BLUE}]2. Запуск массового параллельного парсера FunPay...[/bold {FP_BLUE}]")
        from parser import main_async as run_mass_parser_async
        await run_mass_parser_async()
        
        console.print(f"\n[bold {FP_BLUE}]✅ Массовый парсинг завершен! Отчет обновлен в market_report_v2.json[/bold {FP_BLUE}]")
        input("\nНажмите Enter для просмотра аналитики...")
        show_market_analytics()
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print(f"\n[bold {FP_BLUE}][!] Сбор рынка прерван пользователем.[/bold {FP_BLUE}]")
        input("\nНажмите Enter для возврата в меню...")

async def run_single_seller_parse():
    try:
        console.print(f"\n[bold {FP_BLUE}]═══ ПАРСИНГ ОДНОГО ПРОДАВЦА ПО ID ═══[/bold {FP_BLUE}]")
        user_input = Prompt.ask(
            f"[bold {FP_WHITE}]Введите ID пользователя FunPay или ссылку на профиль[/bold {FP_WHITE}]",
            default="1804150"
        )
        
        user_id = extract_user_id(user_input)
        if not user_id:
            console.print(f"\n[bold {FP_WHITE}]❌ '{user_input.strip()}' — это текстовый никнейм, а не ID![/bold {FP_WHITE}]")
            console.print(f"[{FP_BLUE}]На FunPay профили адресуются только по числовому ID пользователя или ссылке.[/{FP_BLUE}]")
            console.print(f"[{FP_BLUE}]Пример: 14273448 или https://funpay.com/users/14273448/[/{FP_BLUE}]")
            input("\nНажмите Enter для возврата в меню...")
            return

        limit_raw = Prompt.ask(
            f"[bold {FP_WHITE}]Сколько последних отзывов собрать? ([bold {FP_BLUE}]Enter[/bold {FP_BLUE}] = все, или число, напр. 500)[/bold {FP_WHITE}]",
            default="все"
        )
        max_reviews = int(limit_raw.strip()) if limit_raw.strip().isdigit() else None

        proxies = load_proxies()
        if not proxies:
            console.print(f"[bold {FP_BLUE}][!] Внимание: good_proxies.txt пуст. Прямое соединение к FunPay из РФ может блокироваться TLS error 35.[/bold {FP_BLUE}]")
            proxy_candidates = [None]
        else:
            console.print(f"[{FP_BLUE}]Найдено {len(proxies)} прокси. Используем самый быстрый калиброванный узел...[/{FP_BLUE}]")
            proxy_candidates = proxies[:5]

        res = None
        start_time = time.time()
        for idx, proxy in enumerate(proxy_candidates):
            browser = get_browser_for_proxy(proxy) if proxy else "chrome120"
            proxy_dict = {"all": proxy} if proxy else None
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            if idx > 0:
                console.print(f"[{FP_BLUE}]Повтор с резервным прокси ({idx + 1}/{len(proxy_candidates)})...[/{FP_BLUE}]")

            try:
                async with requests.AsyncSession(impersonate=browser, proxies=proxy_dict, timeout=30.0) as client:
                    with Progress(SpinnerColumn(style=FP_BLUE), TextColumn(f"[bold {FP_WHITE}]Сбор профиля, активных лотов и отзывов..."), transient=True) as progress:
                        progress.add_task("parse", total=None)
                        res = await parse_profile(client, user_id, proxy=proxy, user_agent=headers['User-Agent'], max_reviews=max_reviews)
                if res:
                    break
            except Exception as e:
                console.print(f"[{FP_BLUE}]Сбой узла: {e}[/{FP_BLUE}]")

        elapsed = time.time() - start_time

        if not res:
            console.print(f"[bold {FP_WHITE}]❌ Не удалось спарсить пользователя {user_id}. Проверьте доступность профиля.[/bold {FP_WHITE}]")
            input("\nНажмите Enter...")
            return

        username = res.get("username", "Неизвестно")
        total_reviews = res.get("total_reviews", 0)
        categories = res.get("categories", {})

        console.print(f"\n[bold {FP_BLUE}]✅ Успешно обработан за {elapsed:.2f} сек![/bold {FP_BLUE}]")
        
        console.print(Panel(
            f"[{FP_BLUE}]Никнейм:[/{FP_BLUE}] [bold {FP_WHITE}]{username}[/bold {FP_WHITE}] [{FP_BLUE}](ID: {user_id})[/{FP_BLUE}]\n"
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

        for cat_name, cat_data in categories.items():
            revs = cat_data.get("reviews", [])
            lots = cat_data.get("candidate_lots", [])
            total_sum = sum(float(r.get("price") or 0.0) for r in revs if isinstance(r, dict))
            table.add_row(cat_name, str(len(revs)), f"{total_sum:,.2f} RUB", str(len(lots)))

        console.print(table)
        
        reports_dir = BASE_DIR / "reports_v2"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_file = str(reports_dir / f"seller_{user_id}.json")
        atomic_write_json(out_file, res)
        console.print(f"[{FP_BLUE}]Отчет сохранен в {out_file}[/{FP_BLUE}]")
        input("\nНажмите Enter для возврата в меню...")
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print(f"\n[bold {FP_BLUE}][!] Парсинг продавца прерван пользователем.[/bold {FP_BLUE}]")
        input("\nНажмите Enter для возврата в меню...")

async def run_proxy_manager():
    proxy_file = BASE_DIR / "proxies.txt"
    if not proxy_file.exists():
        proxy_file.write_text("# Формат: ip:port:user:pass ИЛИ ip:port ИЛИ http://user:pass@ip:port\n", encoding="utf-8")

    proxies = load_proxies()
    
    console.print(Panel(
        f"[{FP_BLUE}]Файл с прокси:[/{FP_BLUE}] [bold {FP_WHITE}]{proxy_file}[/bold {FP_WHITE}]\n"
        f"[{FP_BLUE}]Загружено в память:[/{FP_BLUE}] [bold {FP_BLUE}]{len(proxies)}[/bold {FP_BLUE}] [{FP_WHITE}]прокси[/{FP_WHITE}]\n\n"
        f"[bold {FP_WHITE}]Поддерживаемые форматы (вставляйте построчно):[/bold {FP_WHITE}]\n"
        f"  [{FP_BLUE}]•[/{FP_BLUE}] [{FP_WHITE}]ip:port:user:pass[/{FP_WHITE}]  [{FP_BLUE}](например: 185.220.101.5:8000:user123:pass123)[/{FP_BLUE}]\n"
        f"  [{FP_BLUE}]•[/{FP_BLUE}] [{FP_WHITE}]ip:port[/{FP_WHITE}]            [{FP_BLUE}](например: 185.220.101.5:8080)[/{FP_BLUE}]\n"
        f"  [{FP_BLUE}]•[/{FP_BLUE}] [{FP_WHITE}]socks5://user:pass@ip:port[/{FP_WHITE}]\n"
        f"  [{FP_BLUE}]•[/{FP_BLUE}] [{FP_WHITE}]http://user:pass@ip:port[/{FP_WHITE}]",
        title=f"[bold {FP_WHITE}]🌐 Управление прокси-серверами[/bold {FP_WHITE}]",
        border_style=FP_BLUE
    ))

    console.print(f"  [bold {FP_BLUE}]1.[/bold {FP_BLUE}] [bold {FP_WHITE}]⚡ Запустить проверку и калибровку пинга[/bold {FP_WHITE}]")
    console.print(f"  [bold {FP_BLUE}]2.[/bold {FP_BLUE}] [bold {FP_WHITE}]📝 Открыть proxies.txt в Блокноте для редактирования[/bold {FP_WHITE}]")
    console.print(f"  [bold {FP_BLUE}]0.[/bold {FP_BLUE}] [{FP_WHITE}]↩ Назад в меню[/{FP_WHITE}]\n")

    choice = Prompt.ask(f"[bold {FP_BLUE}]Ввод[/bold {FP_BLUE}]", choices=["0", "1", "2"], default="1")

    if choice == "2":
        if sys.platform == "win32":
            subprocess.Popen(["notepad.exe", str(proxy_file)])
            console.print(f"[bold {FP_BLUE}]Блокнот открыт! Сохраните файл после добавления прокси.[/bold {FP_BLUE}]")
        else:
            console.print(f"[{FP_WHITE}]Откройте файл: {proxy_file}[/{FP_WHITE}]")
        input("\nНажмите Enter после сохранения...")
    elif choice == "1":
        try:
            with Progress(SpinnerColumn(style=FP_BLUE), TextColumn(f"[bold {FP_WHITE}]Калибровка и проверка задержки прокси..."), transient=True) as progress:
                progress.add_task("ping", total=None)
                valid = await ping_and_rank(proxies)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print(f"\n[bold {FP_BLUE}][!] Калибровка прокси отменена пользователем.[/bold {FP_BLUE}]")
            input("\nНажмите Enter для возврата в меню...")
            return
            
        good_urls = [v['url'] for v in valid if v.get('url')]
        if good_urls:
            good_file = BASE_DIR / "good_proxies.txt"
            good_file.write_text("\n".join(good_urls) + "\n", encoding="utf-8")
            console.print(f"\n[bold {FP_BLUE}]✅ Сохранено [bold {FP_WHITE}]{len(good_urls)}[/bold {FP_WHITE}] рабочих прокси в good_proxies.txt[/bold {FP_BLUE}]\n")

        table = Table(
            title=f"[bold {FP_WHITE}]Статус прокси-серверов[/bold {FP_WHITE}]",
            border_style=FP_BLUE,
            header_style=f"bold {FP_BLUE}"
        )
        table.add_column("№", justify="right", style=FP_BLUE)
        table.add_column("Прокси / Узел", style=f"bold {FP_WHITE}")
        table.add_column("Задержка (Пинг)", justify="right", style=f"bold {FP_BLUE}")

        for i, v in enumerate(valid, 1):
            ping_str = f"{v['ping']:.2f}с" if v['ping'] < 900 else "Локальный IP"
            table.add_row(str(i), v['name'], ping_str)

        console.print(table)
        input("\nНажмите Enter для возврата в меню...")

def main_menu():
    while True:
        try:
            show_banner()
            console.print(f"[bold {FP_WHITE}]Выберите действие:[/bold {FP_WHITE}]\n")
            console.print(f"  [bold {FP_BLUE}]1.[/bold {FP_BLUE}] 🚀 [bold {FP_WHITE}]ЗАПУСК ПОЛНОГО СБОРА РЫНКА[/bold {FP_WHITE}] [{FP_BLUE}](RMTHub Топ ➔ FunPay Отзывы ➔ Отчет)[/{FP_BLUE}]")
            console.print(f"  [bold {FP_BLUE}]2.[/bold {FP_BLUE}] 📊 [bold {FP_WHITE}]Глобальная аналитика рынка[/bold {FP_WHITE}] [{FP_BLUE}](обороты, топ ниши, 108k+ отзывов)[/{FP_BLUE}]")
            console.print(f"  [bold {FP_BLUE}]3.[/bold {FP_BLUE}] 🔍 [bold {FP_WHITE}]Быстрый парсинг одного продавца по ID[/bold {FP_WHITE}]")
            console.print(f"  [bold {FP_BLUE}]4.[/bold {FP_BLUE}] 🌐 [bold {FP_WHITE}]Прокси: добавить, открыть файл, проверить пинг[/bold {FP_WHITE}]")
            console.print(f"  [bold {FP_BLUE}]0.[/bold {FP_BLUE}] 🚪 [{FP_WHITE}]Выход[/{FP_WHITE}]\n")

            choice = Prompt.ask(f"[bold {FP_BLUE}]Ввод[/bold {FP_BLUE}]", choices=["0", "1", "2", "3", "4"], default="1")

            if choice == "1":
                asyncio.run(run_full_pipeline())
            elif choice == "2":
                show_market_analytics()
            elif choice == "3":
                asyncio.run(run_single_seller_parse())
            elif choice == "4":
                asyncio.run(run_proxy_manager())
            elif choice == "0":
                console.print(f"[{FP_BLUE}]Выход...[/{FP_BLUE}]")
                break
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[bold {FP_BLUE}]Выход из программы...[/bold {FP_BLUE}]")
            break
        except Exception as e:
            console.print(f"\n[bold {FP_WHITE}]Ошибка выполнения: {e}[/bold {FP_WHITE}]")
            time.sleep(1.5)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        main_menu()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
