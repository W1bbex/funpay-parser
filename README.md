# FunPay Analytics & Market Intelligence

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python" alt="Python Version" />
  <img src="https://img.shields.io/badge/Engine-curl--cffi-orange?style=for-the-badge" alt="curl-cffi" />
  <img src="https://img.shields.io/badge/Storage-SQLite_%2B_SHA--256-blueviolet?style=for-the-badge" alt="Storage" />
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License" />
</p>

**FunPay Analytics** — это высокопроизводительный асинхронный ETL-пайплайн и аналитический движок для сбора, нормализации и интеллектуального анализа рыночных данных маркетплейса **FunPay**.

Фреймворк спроектирован для устойчивого парсинга больших объёмов данных в условиях строгой антибот-защиты, математического обратного матчинга отзывов к лотам и формирования отчётов о реальных продажах, оборотах и маржинальности продавцов.

---

## 🌟 Ключевые возможности

* 🥷 **TLS Fingerprint Impersonation (`curl_cffi`)**: Полный обход антибот-систем и Cloudflare за счёт эмуляции TLS-отпечатков (JA3/JA4, HTTP/2 Akamai) реальных браузеров (Chrome 120+, Safari).
* 🧠 **Reverse Lot Matching Engine**: Авторский алгоритм сопоставления отзывов с конкретными лотами продавца по суммам сделок, шагам округления и кратностям (`get_review_interval`), позволяющий точно узнать, какой товар был куплен.
* 📦 **Неизменяемый Raw-слой (SHA-256 Checksums)**: Сохранение исходных снапшотов страниц (MHTML/HTML.gz) с контрольными суммами для защиты от искажения исторических данных.
* 🔄 **Умный Proxy Pool & Rotator**: Автоматическая валидация прокси, адаптивные задержки (Smart Throttling) и маскирование учетных данных в логах.
* 📊 **Market Intelligence Reporting**: Генерация структурированных отчётов: оценка выручки продавцов, средний чек, статистика активности по часам и топ категорий.
* 🏗️ **Модульная архитектура**: Чистое разделение ответственности (`harvest`, `storage`, `normalize`, `matching`, `taxonomy`, `reporting`).

---

## 🏗️ Архитектура ETL-пайплайна

```mermaid
flowchart TD
    subgraph Harvest [1. Сбор данных (Harvest)]
        P[Proxy Pool / Health Checker] --> C[curl_cffi Async Engine]
        C -->|TLS Impersonation| FP[(FunPay Marketplace)]
        FP -->|HTML / Profiles / Reviews| S[Raw Snapshot Layer]
    end

    subgraph Storage [2. Хранение & Целостность]
        S -->|SHA-256 Hash Verification| DB[(SQLite Database)]
    end

    subgraph Processing [3. Анализ & Матчинг]
        DB --> N[Data Normalizer]
        N --> M[Reverse Lot Matching Engine]
        M --> T[Taxonomy Classifier]
    end

    subgraph Intelligence [4. Аналитика (Reporting)]
        T --> Rep[Market Intelligence Report]
        Rep --> JSON[JSON / Markdown Analytics]
    end
```

---

## 🚀 Быстрый старт

### 1. Установка зависимостей
```bash
git clone https://github.com/W1bbex/FunPay-Analytics.git
cd FunPay-Analytics
pip install -r requirements.txt
```

### 2. Настройка прокси
Создайте файл `proxies.txt` на основе шаблона `proxies.example.txt`:
```text
127.0.0.1:8080
http://user:pass@proxy.example.com:3128
```

### 3. Запуск сбора профиля продавца
```bash
python parser.py
```

### 4. Использование CLI аналитики
```bash
# Инициализация базы данных
python -m funpay_analytics.cli init-db

# Импорт собственных заказов из сохраненного HTML
python -m funpay_analytics.cli import-own-orders --html path/to/orders.html

# Импорт снимка продавца
python -m funpay_analytics.cli import-seller-json --file path/to/seller.json
```

---

## 📁 Структура проекта

```text
FunPay-Analytics/
├── src/
│   └── funpay_analytics/
│       ├── harvest/         # Асинхронные скраперы и загрузчики
│       ├── storage/         # SQLite схемы, транзакции, raw-слой
│       ├── normalize/       # Нормализация цен, валют и текста
│       ├── matching/        # Алгоритм обратного матчинга отзывов
│       ├── taxonomy/        # Классификатор категорий и товаров
│       ├── reporting/       # Генераторы рыночных отчетов
│       └── cli.py           # CLI интерфейс управления
├── parser.py                # Быстрый скрипт парсинга профилей
├── proxy_checker.py         # Проверка работоспособности прокси
├── utils.py                 # Атомарная запись, TLS-конфиги, логгер
├── examples/                # Примеры аналитических отчетов и JSON-схем
├── tests/                   # Модульные и интеграционные тесты
└── requirements.txt         # Зависимости проекта
```

---

## 👤 Автор

* Разработчик: **W1bbex** ([@w1bbex](https://t.me/w1bbex))
* Сайт: [https://w1bbex.ru](https://w1bbex.ru)
* GitHub: [@W1bbex](https://github.com/W1bbex)

## 📄 Лицензия

Проект распространяется под открытой лицензией [MIT License](LICENSE).
