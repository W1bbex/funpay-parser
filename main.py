# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import asyncio
import subprocess
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
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn

from curl_cffi import requests
from utils import get_browser_for_proxy, atomic_write_json, hide_proxy_credentials
from parser import parse_profile, ping_and_rank, load_proxies, mass_parse
import fetch_ids

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
    [bold cyan]ANALYTICS & FULL MARKET SCRAPER PIPELINE[/bold cyan] [dim](v1.0.0 by W1bbex)[/dim]
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

async def run_full_pipeline():
    console.print("\n[bold purple]═══ ПОЛНЫЙ ЦИКЛ ПАРСИНГА РЫНКА (RMTHub ➔ FunPay ➔ Отчет) ═══[/bold purple]\n")
    
    has_queue = os.path.exists("queue.txt") and os.path.getsize("queue.txt") > 0
    refetch = True
    
    if has_queue:
        with open("queue.txt", "r", encoding="utf-8") as f:
            q_count = len([line for line in f if line.strip()])
        console.print(f"[bold green]Найдена готовая очередь: [bold white]{q_count}[/bold white] продавцов в queue.txt[/bold green]")
        refetch = not Confirm.ask("Использовать текущую очередь продавцов?", default=True)

    if refetch:
        console.print("\n[bold cyan]1. Сбор топа продавцов с RMTHub...[/bold cyan]")
        target = Prompt.ask("Сколько топ-продавцов собрать с RMTHub?", default="100")
        try:
            target_count = int(target)
        except:
            target_count = 100
            
        pages = max(1, (target_count + 19) // 20)
        console.print(f"Стягиваем {pages} страниц с rmthub.com...")
        await fetch_ids.main(target_count=target_count)

    console.print("\n[bold cyan]2. Запуск массового параллельного парсера FunPay...[/bold cyan]")
    from parser import main as run_mass_parser
    run_mass_parser()
    
    console.print("\n[bold green]✅ Массовый парсинг завершен! Отчет обновлен в market_report_v2.json[/bold green]")
    input("\nНажмите Enter для просмотра аналитики...")
    show_market_analytics()

async def run_single_seller_parse():
    console.print("\n[bold cyan]═══ ПАРСИНГ ОДНОГО ПРОДАВЦА ПО ID ═══[/bold cyan]")
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

async def run_proxy_manager():
    proxy_file = BASE_DIR / "proxies.txt"
    if not proxy_file.exists():
        proxy_file.write_text("# Формат: ip:port:user:pass ИЛИ ip:port ИЛИ http://user:pass@ip:port\n", encoding="utf-8")

    proxies = load_proxies()
    
    console.print(Panel(
        f"[bold white]Файл с прокси:[/bold white] [bold cyan]{proxy_file}[/bold cyan]\n"
        f"[bold white]Загружено в память:[/bold white] [bold green]{len(proxies)}[/bold green] прокси\n\n"
        f"[bold yellow]Поддерживаемые форматы (вставляйте построчно):[/bold yellow]\n"
        f"  • [cyan]ip:port:user:pass[/cyan]  (например: 185.220.101.5:8000:user123:pass123)\n"
        f"  • [cyan]ip:port[/cyan]            (например: 185.220.101.5:8080)\n"
        f"  • [cyan]socks5://user:pass@ip:port[/cyan]\n"
        f"  • [cyan]http://user:pass@ip:port[/cyan]",
        title="🌐 Управление прокси-серверами",
        border_style="purple"
    ))

    console.print("  [bold cyan]1.[/bold cyan] ⚡ Запустить проверку и калибровку пинга")
    console.print("  [bold cyan]2.[/bold cyan] 📝 Открыть proxies.txt в Блокноте для редактирования")
    console.print("  [bold red]0.[/bold red] ↩ Назад в меню\n")

    choice = Prompt.ask("[bold purple]Ввод[/bold purple]", choices=["0", "1", "2"], default="1")

    if choice == "2":
        if sys.platform == "win32":
            subprocess.Popen(["notepad.exe", str(proxy_file)])
            console.print("[green]Блокнот открыт! Сохраните файл после добавления прокси.[/green]")
        else:
            console.print(f"Откройте файл: {proxy_file}")
        input("\nНажмите Enter после сохранения...")
    elif choice == "1":
        with Progress(SpinnerColumn(style="cyan"), TextColumn("[bold cyan]Калибровка и проверка задержки прокси..."), transient=True) as progress:
            progress.add_task("ping", total=None)
            valid = await ping_and_rank(proxies)
            
        table = Table(title="Статус прокси-серверов", border_style="purple")
        table.add_column("№", justify="right", style="dim")
        table.add_column("Прокси / Узел", style="bold white")
        table.add_column("Задержка (Пинг)", justify="right", style="bold green")

        for i, v in enumerate(valid, 1):
            ping_str = f"{v['ping']:.2f}с" if v['ping'] < 900 else "Локальный IP"
            table.add_row(str(i), v['name'], ping_str)

        console.print(table)
        input("\nНажмите Enter для возврата в меню...")

def main_menu():
    while True:
        show_banner()
        console.print("[bold white]Выберите действие:[/bold white]\n")
        console.print("  [bold green]1.[/bold green] 🚀 [bold]ЗАПУСК ПОЛНОГО СБОРА РЫНКА[/bold] (RMTHub Топ ➔ FunPay Отзывы ➔ Отчет)")
        console.print("  [bold cyan]2.[/bold cyan] 📊 [bold]Глобальная аналитика рынка[/bold] (обороты, топ ниши, 108k+ отзывов)")
        console.print("  [bold cyan]3.[/bold cyan] 🔍 [bold]Быстрый парсинг одного продавца по ID[/bold]")
        console.print("  [bold cyan]4.[/bold cyan] 🌐 [bold]Прокси: добавить, открыть файл, проверить пинг[/bold]")
        console.print("  [bold red]0.[/bold red] 🚪 Выход\n")

        choice = Prompt.ask("[bold purple]Ввод[/bold purple]", choices=["0", "1", "2", "3", "4"], default="1")

        if choice == "1":
            asyncio.run(run_full_pipeline())
        elif choice == "2":
            show_market_analytics()
        elif choice == "3":
            asyncio.run(run_single_seller_parse())
        elif choice == "4":
            asyncio.run(run_proxy_manager())
        elif choice == "0":
            console.print("[dim]Выход...[/dim]")
            break

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main_menu()
