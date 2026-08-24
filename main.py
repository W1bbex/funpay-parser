# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import asyncio
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(str(BASE_DIR))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn

from curl_cffi import requests
from utils import get_browser_for_proxy, atomic_write_json, hide_proxy_credentials
from parser import parse_profile, ping_and_rank, load_proxies

console = Console(highlight=False)

def show_banner():
    console.clear()
    banner_text = """[bold purple]
  ███████╗██╗   ██╗███╗   ██╗██████╗  █████╗ ██╗   ██╗
  ██╔════╝██║   ██║████╗  ██║██╔══██╗██╔══██╗╚██╗ ██╔╝
  █████╗  ██║   ██║██╔██╗ ██║██████╔╝███████║ ╚████╔╝ 
  ██╔══╝  ██║   ██║██║╚██╗██║██╔═══╝ ██╔══██║  ╚██╔╝  
  ██║     ╚██████╔╝██║ ╚████║██║     ██║  ██║   ██║   
  ╚═╝      ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝  ╚═╝   ╚═╝   
    [bold cyan]ANALYTICS & MARKET INTELLIGENCE ENGINE[/bold cyan] [dim](v1.0.0 by W1bbex)[/dim]
    """
    console.print(Panel(banner_text, border_style="purple", expand=False))

def show_market_analytics():
    report_file = BASE_DIR / "market_report.json"
    if not report_file.exists():
        report_file = BASE_DIR / "examples" / "market_report.example.json"
        
    if not report_file.exists():
        console.print("[red]❌ Файл market_report.json не найден![/red]")
        input("\nНажмите Enter для возврата в меню...")
        return

    try:
        data = json.loads(report_file.read_text(encoding="utf-8"))
    except:
        console.print("[red]❌ Ошибка чтения отчета[/red]")
        input("\nНажмите Enter...")
        return
        
    total_sellers = len(data)
    total_reviews = sum(x.get("total_reviews", 0) for x in data)
    total_earned = sum(x.get("total_earned", 0.0) for x in data)

    categories = {}
    for s in data:
        for cat, c_data in s.get("categories", {}).items():
            if cat not in categories:
                categories[cat] = {"count": 0, "earned": 0.0}
            categories[cat]["count"] += c_data.get("count", 0)
            categories[cat]["earned"] += c_data.get("earned", 0.0)

    console.print(Panel(
        f"[bold green]Всего продавцов в базе:[/bold green] [bold white]{total_sellers}[/bold white]\n"
        f"[bold green]Собрано и обработано отзывов:[/bold green] [bold white]{total_reviews:,}[/bold white]\n"
        f"[bold green]Оцененный суммарный оборот:[/bold green] [bold yellow]{total_earned:,.2f} RUB[/bold yellow]",
        title="📊 Глобальная сводка маркетплейса",
        border_style="cyan"
    ))

    table = Table(title="🏆 Топ-12 категорий по обороту", border_style="purple")
    table.add_column("№", justify="right", style="dim")
    table.add_column("Категория", style="bold cyan")
    table.add_column("Отзывов", justify="right", style="white")
    table.add_column("Оборот (выручка)", justify="right", style="bold yellow")

    top_cats = sorted(categories.items(), key=lambda x: x[1]["earned"], reverse=True)[:12]
    for i, (c_name, c_stats) in enumerate(top_cats, 1):
        table.add_row(str(i), c_name, f"{c_stats['count']:,}", f"{c_stats['earned']:,.2f} RUB")

    console.print(table)
    input("\nНажмите Enter для возврата в меню...")

async def run_single_seller_parse():
    console.print("\n[bold cyan]═══ ПАРСИНГ ПРОДАВЦА ПО ID ═══[/bold cyan]")
    user_id = Prompt.ask("[bold yellow]Введите ID пользователя FunPay[/bold yellow]", default="1804150")
    
    if not user_id.isdigit():
        console.print("[red]ID должен состоять только из цифр![/red]")
        time.sleep(1.5)
        return

    console.print(f"\n[bold green]Подключаюсь через TLS-Impersonator (Chrome 120)...[/bold green]")
    
    start_time = time.time()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    async with requests.AsyncSession(impersonate="chrome120", timeout=25.0) as client:
        with Progress(SpinnerColumn(style="purple"), TextColumn("[bold purple]Сбор профиля, активных лотов и страниц отзывов..."), transient=True) as progress:
            progress.add_task("parse", total=None)
            res = await parse_profile(client, user_id, proxy=None, user_agent=headers['User-Agent'])

    elapsed = time.time() - start_time

    if not res:
        console.print(f"[red]❌ Не удалось спарсить пользователя {user_id}. Проверьте доступность профиля.[/red]")
        input("\nНажмите Enter...")
        return

    username = res.get("username", "Неизвестно")
    total_reviews = res.get("total_reviews", 0)
    categories = res.get("categories", {})

    console.print(f"\n[bold green]✅ Успешно обработан за {elapsed:.2f} сек![/bold green]")
    
    console.print(Panel(
        f"[bold white]Никнейм:[/bold white] [bold cyan]{username}[/bold cyan] (ID: {user_id})\n"
        f"[bold white]Всего отзывов:[/bold white] [bold yellow]{total_reviews:,}[/bold yellow]\n"
        f"[bold white]Скорость сбора:[/bold white] [bold green]{total_reviews / elapsed if elapsed > 0 else 0:.1f} отз/сек[/bold green]\n"
        f"[bold white]Категорий с продажами:[/bold white] [bold magenta]{len(categories)}[/bold magenta]",
        title=f"👤 Профиль: {username}",
        border_style="green"
    ))

    table = Table(title="Категории и объемы продаж", border_style="cyan")
    table.add_column("Категория", style="bold white")
    table.add_column("Отзывов", justify="right", style="cyan")
    table.add_column("Сумма по отзывам", justify="right", style="bold yellow")
    table.add_column("Кандидатов лотов", justify="right", style="dim")

    for cat_name, cat_data in categories.items():
        revs = cat_data.get("reviews", [])
        lots = cat_data.get("candidate_lots", [])
        total_sum = sum(r.get("price", 0.0) for r in revs)
        table.add_row(cat_name, str(len(revs)), f"{total_sum:,.2f} RUB", str(len(lots)))

    console.print(table)
    
    os.makedirs("reports_v2", exist_ok=True)
    out_file = f"reports_v2/seller_{user_id}.json"
    atomic_write_json(out_file, res)
    console.print(f"[dim]Отчет сохранен в {out_file}[/dim]")
    input("\nНажмите Enter для возврата в меню...")

async def run_proxy_test():
    console.print("\n[bold cyan]═══ КАЛИБРОВКА И ТЕСТ ПРОКСИ ═══[/bold cyan]")
    proxies = load_proxies()
    console.print(f"Загружено прокси из файлов: [bold yellow]{len(proxies)}[/bold yellow]")
    
    with Progress(SpinnerColumn(style="cyan"), TextColumn("[bold cyan]Замер задержки и проверка TLS рукопожатия..."), transient=True) as progress:
        progress.add_task("ping", total=None)
        valid = await ping_and_rank(proxies)
        
    table = Table(title="Статус прокси-серверов", border_style="purple")
    table.add_column("№", justify="right", style="dim")
    table.add_column("Прокси / Узел", style="bold white")
    table.add_column("Задержка (Пинг)", justify="right", style="bold green")

    for i, v in enumerate(valid, 1):
        ping_str = f"{v['ping']:.2f}с" if v['ping'] < 900 else "Локальный"
        table.add_row(str(i), v['name'], ping_str)

    console.print(table)
    input("\nНажмите Enter для возврата в меню...")

def main_menu():
    while True:
        show_banner()
        console.print("[bold white]Выберите действие:[/bold white]\n")
        console.print("  [bold cyan]1.[/bold cyan] 🚀 [bold]Быстрый парсинг продавца по ID[/bold] (лоты, отзывы, интервалы)")
        console.print("  [bold cyan]2.[/bold cyan] 📊 [bold]Глобальная аналитика рынка[/bold] (обороты, топ ниши, 108k+ отзывов)")
        console.print("  [bold cyan]3.[/bold cyan] ⚡ [bold]Калибровка и тест прокси-пула[/bold]")
        console.print("  [bold cyan]4.[/bold cyan] 👥 [bold]Запуск массового сбора очереди (queue.txt)[/bold]")
        console.print("  [bold red]0.[/bold red] 🚪 Выход\n")

        choice = Prompt.ask("[bold purple]Ввод[/bold purple]", choices=["0", "1", "2", "3", "4"], default="1")

        if choice == "1":
            asyncio.run(run_single_seller_parse())
        elif choice == "2":
            show_market_analytics()
        elif choice == "3":
            asyncio.run(run_proxy_test())
        elif choice == "4":
            from parser import main as mass_main
            mass_main()
            input("\nНажмите Enter...")
        elif choice == "0":
            console.print("[dim]Выход...[/dim]")
            break

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main_menu()
