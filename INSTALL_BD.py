"""
INSTALL_BD.py

Создает SQLite-базу database.db, скачивает PDF-справки по бенз(а)пирену
с сайта НПО «Тайфун», очищает данные и загружает их в таблицы months и air.

Запуск:
    python INSTALL_BD.py
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.rpatyphoon.ru/products/pollution-media.php"
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
PDF_DIR = DATA_DIR / "pdf"
DB_PATH = PROJECT_DIR / "database.db"
MAX_YEAR = 2020
MIN_YEAR = 2008

MONTHS = [
    (1, "Январь"),
    (2, "Февраль"),
    (3, "Март"),
    (4, "Апрель"),
    (5, "Май"),
    (6, "Июнь"),
    (7, "Июль"),
    (8, "Август"),
    (9, "Сентябрь"),
    (10, "Октябрь"),
    (11, "Ноябрь"),
    (12, "Декабрь"),
]

MONTH_COLUMNS = [f"month_{i}" for i in range(1, 13)]
NUM_RE = re.compile(r"^(?:-|н/?д|[<>]?[0-9]+(?:[,.][0-9]+)?)$", re.IGNORECASE)


def normalize_value(value: str | float | int | None) -> float | None:
    """Преобразует значения из PDF: '1,2', '-', '<0,01' -> float или None."""
    if value is None:
        return None
    value = str(value).strip().replace(" ", "")
    if value in {"", "-", "—", "н/д", "Н/Д"}:
        return None
    value = value.replace(",", ".")
    value = value.lstrip("<>")
    try:
        return float(value)
    except ValueError:
        return None


def normalize_city(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" .,:;–-")


def request_soup(url: str) -> BeautifulSoup:
    headers = {"User-Agent": "Mozilla/5.0 air-crud-student-project/1.0"}
    response = requests.get(url, timeout=30, headers=headers)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return BeautifulSoup(response.text, "html.parser")


def find_annual_pdf_links() -> list[dict]:
    """Ищет годовые PDF-ссылки в разделе справок по воздуху."""
    soup = request_soup(BASE_URL)
    links: list[dict] = []

    for a in soup.find_all("a"):
        text = " ".join(a.get_text(" ", strip=True).split())
        href = a.get("href") or ""
        match = re.search(r"Справка\s+за\s+(\d{4})\s+год", text, re.IGNORECASE)
        if not match:
            continue
        year = int(match.group(1))
        if not (MIN_YEAR <= year <= MAX_YEAR):
            continue
        if "первое полугодие" in text.lower() or "второе полугодие" in text.lower():
            continue
        url = urljoin(BASE_URL, href)
        if not url.lower().endswith(".pdf"):
            continue
        # Нужные ссылки находятся в подпапке benzapiren.
        if "benzapiren" not in url.lower():
            continue
        links.append({"year": year, "text": text, "url": url})

    # Убираем дубли и сортируем по году.
    unique = {item["year"]: item for item in links}
    return [unique[year] for year in sorted(unique)]


def download_pdf(item: dict) -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    year = item["year"]
    path = PDF_DIR / f"bp_{year}.pdf"
    if path.exists() and path.stat().st_size > 0:
        return path

    headers = {"User-Agent": "Mozilla/5.0 air-crud-student-project/1.0"}
    response = requests.get(item["url"], timeout=60, headers=headers)
    response.raise_for_status()
    path.write_bytes(response.content)
    return path


def looks_like_number_token(token: str) -> bool:
    return bool(NUM_RE.match(token.strip()))


def parse_pdf_text_lines(pdf_path: Path, year: int, source_url: str) -> list[dict]:
    """
    Парсит строки PDF. В справках таблица обычно имеет формат:
    Город ПНЗ I II III IV V VI VII VIII IX X XI XII среднегодовое
    """
    rows: list[dict] = []
    last_city: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            for raw_line in text.splitlines():
                line = " ".join(raw_line.split())
                if not line:
                    continue

                parts = line.split()
                # Нужно минимум: город + ПНЗ + 12 месяцев + среднегодовое.
                if len(parts) < 15:
                    continue

                tail = parts[-14:]
                if not all(looks_like_number_token(token) for token in tail):
                    continue

                prefix = " ".join(parts[:-14])
                station_raw = tail[0]
                month_values = tail[1:13]
                annual_avg_raw = tail[13]

                city = normalize_city(prefix) if prefix else last_city
                if not city:
                    continue

                # Отсекаем служебные строки и заголовки.
                city_lower = city.lower()
                if any(bad in city_lower for bad in ["таблица", "город", "месяц", "угмс", "содержание"]):
                    continue

                last_city = city
                try:
                    station = int(float(station_raw.replace(",", ".")))
                except ValueError:
                    station = None

                row = {
                    "city": city,
                    "station": station,
                    "year": year,
                    "annual_avg": normalize_value(annual_avg_raw),
                    "source_url": source_url,
                }
                for idx, raw_value in enumerate(month_values, start=1):
                    row[f"month_{idx}"] = normalize_value(raw_value)
                rows.append(row)

    return rows


def remove_sparse_columns(df: pd.DataFrame, min_filled_percent: float = 0.60) -> pd.DataFrame:
    """Удаляет столбцы, где заполнено меньше 60% значений."""
    protected = {"city", "year", "source_url"}
    keep_cols: list[str] = []
    for col in df.columns:
        if col in protected:
            keep_cols.append(col)
            continue
        filled_ratio = df[col].notna().mean()
        if filled_ratio >= min_filled_percent:
            keep_cols.append(col)
    return df[keep_cols].copy()


def wide_to_long(df: pd.DataFrame) -> pd.DataFrame:
    available_months = [col for col in MONTH_COLUMNS if col in df.columns]
    id_vars = [col for col in ["city", "station", "year", "annual_avg", "source_url"] if col in df.columns]

    if not available_months:
        return pd.DataFrame(columns=["city", "station", "year", "month_id", "date", "value", "annual_avg", "source_url"])

    long_df = df.melt(
        id_vars=id_vars,
        value_vars=available_months,
        var_name="month_column",
        value_name="value",
    )
    long_df["month_id"] = long_df["month_column"].str.extract(r"(\d+)").astype(int)
    long_df["date"] = long_df.apply(lambda r: date(int(r["year"]), int(r["month_id"]), 1).isoformat(), axis=1)
    long_df = long_df.drop(columns=["month_column"])
    long_df = long_df.dropna(subset=["value"])

    columns = ["city", "station", "year", "month_id", "date", "value", "annual_avg", "source_url"]
    for col in columns:
        if col not in long_df.columns:
            long_df[col] = None
    return long_df[columns].copy()


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        DROP TABLE IF EXISTS air;
        DROP TABLE IF EXISTS months;

        CREATE TABLE months (
            id INTEGER PRIMARY KEY,
            month_number INTEGER NOT NULL UNIQUE,
            month_name TEXT NOT NULL
        );

        CREATE TABLE air (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            station INTEGER,
            year INTEGER NOT NULL,
            month_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            value REAL NOT NULL,
            annual_avg REAL,
            source_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (month_id) REFERENCES months(id)
        );

        CREATE INDEX idx_air_city ON air(city);
        CREATE INDEX idx_air_year ON air(year);
        CREATE INDEX idx_air_date ON air(date);
        """
    )
    conn.executemany(
        "INSERT INTO months (id, month_number, month_name) VALUES (?, ?, ?)",
        [(number, number, name) for number, name in MONTHS],
    )
    conn.commit()


def insert_air_rows(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict("records")
    conn.executemany(
        """
        INSERT INTO air (city, station, year, month_id, date, value, annual_avg, source_url)
        VALUES (:city, :station, :year, :month_id, :date, :value, :annual_avg, :source_url)
        """,
        records,
    )
    conn.commit()


def main() -> None:
    print("Ищу годовые PDF-справки по воздуху...")
    links = find_annual_pdf_links()
    if not links:
        raise RuntimeError("Не удалось найти PDF-ссылки по бенз(а)пирену на сайте.")

    print(f"Найдено файлов: {len(links)}")
    all_rows: list[dict] = []
    for item in links:
        year = item["year"]
        print(f"Скачиваю/читаю {year}: {item['url']}")
        try:
            pdf_path = download_pdf(item)
            rows = parse_pdf_text_lines(pdf_path, year, item["url"])
            print(f"  строк из PDF: {len(rows)}")
            all_rows.extend(rows)
        except Exception as exc:
            print(f"  ВНИМАНИЕ: файл за {year} год пропущен из-за ошибки чтения PDF: {exc}")
            continue

    if not all_rows:
        raise RuntimeError("PDF-файлы скачаны, но таблицы не распознаны. Проверьте формат справок.")

    raw_df = pd.DataFrame(all_rows)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_df.to_csv(DATA_DIR / "raw_air_wide.csv", index=False, encoding="utf-8-sig")

    cleaned_wide = remove_sparse_columns(raw_df, min_filled_percent=0.60)
    cleaned_wide.to_csv(DATA_DIR / "cleaned_air_wide.csv", index=False, encoding="utf-8-sig")

    air_df = wide_to_long(cleaned_wide)
    air_df.to_csv(DATA_DIR / "air_long.csv", index=False, encoding="utf-8-sig")

    with sqlite3.connect(DB_PATH) as conn:
        create_schema(conn)
        insert_air_rows(conn, air_df)
        count = conn.execute("SELECT COUNT(*) FROM air").fetchone()[0]

    print("Готово.")
    print(f"База данных: {DB_PATH}")
    print(f"Загружено записей в air: {count}")
    print(f"Промежуточные CSV-файлы: {DATA_DIR}")


if __name__ == "__main__":
    main()
