import argparse
import sys
from funpay_analytics.storage.db import init_db
import funpay_analytics.normalize.extract_own_orders as extractor
import funpay_analytics.harvest.json_importer as json_importer

def main():
    parser = argparse.ArgumentParser(description="FunPay Analytics MVP CLI")
    subparsers = parser.add_subparsers(dest="command")

    # init-db
    init_parser = subparsers.add_parser("init-db", help="Инициализировать базу данных")

    # import-own-orders
    import_parser = subparsers.add_parser("import-own-orders", help="Импортировать собственные заказы из сохраненного HTML/MHTML")
    import_parser.add_argument("--html", required=True, help="Путь к файлу")

    # import-seller-json
    import_json_parser = subparsers.add_parser("import-seller-json", help="Импортировать seller_snapshot_v2 (JSON) в базу данных")
    import_json_parser.add_argument("--file", required=True, help="Путь к JSON файлу")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
        print("База данных успешно инициализирована.")
    elif args.command == "import-own-orders":
        try:
            inserted = extractor.import_orders(args.html)
            print(f"Импорт завершен. Извлечено/обновлено {inserted} заказов.")
        except Exception as e:
            print(f"Ошибка импорта: {e}")
            sys.exit(1)
    elif args.command == "import-seller-json":
        try:
            snapshot_id = json_importer.import_seller_json(args.file)
            print(f"Успешно импортирован snapshot ID {snapshot_id}")
        except Exception as e:
            print(f"Ошибка импорта JSON: {e}")
            sys.exit(1)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
