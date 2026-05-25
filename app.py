"""
Streamlit-интерфейс для CRUD-операций с таблицами months и air.

Запуск:
    streamlit run app.py
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent / "database.db"


@st.cache_data(ttl=3)
def read_table(table_name: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)


def execute_sql(sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(sql, params)
        conn.commit()
    st.cache_data.clear()


def db_exists() -> bool:
    return DB_PATH.exists()


def show_months_crud() -> None:
    st.subheader("Таблица months")
    df = read_table("months")
    st.dataframe(df, use_container_width=True)

    action = st.radio("Операция", ["Добавить", "Изменить", "Удалить"], horizontal=True, key="months_action")

    if action == "Добавить":
        with st.form("add_month"):
            month_number = st.number_input("Номер месяца", 1, 12, 1)
            month_name = st.text_input("Название месяца")
            submitted = st.form_submit_button("Добавить")
        if submitted:
            execute_sql(
                "INSERT INTO months (id, month_number, month_name) VALUES (?, ?, ?)",
                (int(month_number), int(month_number), month_name.strip()),
            )
            st.success("Запись добавлена")
            st.rerun()

    elif action == "Изменить":
        ids = df["id"].tolist()
        selected_id = st.selectbox("ID записи", ids)
        selected = df[df["id"] == selected_id].iloc[0]
        with st.form("edit_month"):
            month_number = st.number_input("Номер месяца", 1, 12, int(selected["month_number"]))
            month_name = st.text_input("Название месяца", str(selected["month_name"]))
            submitted = st.form_submit_button("Сохранить")
        if submitted:
            execute_sql(
                "UPDATE months SET month_number = ?, month_name = ? WHERE id = ?",
                (int(month_number), month_name.strip(), int(selected_id)),
            )
            st.success("Запись изменена")
            st.rerun()

    else:
        ids = df["id"].tolist()
        selected_id = st.selectbox("ID записи", ids)
        if st.button("Удалить месяц"):
            try:
                execute_sql("DELETE FROM months WHERE id = ?", (int(selected_id),))
                st.success("Запись удалена")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Этот месяц используется в таблице air, поэтому удалить его нельзя.")


def show_air_crud() -> None:
    st.subheader("Таблица air")

    months_df = read_table("months")
    air_df = read_table("air")

    col1, col2, col3 = st.columns(3)
    with col1:
        city_filter = st.text_input("Фильтр по городу")
    with col2:
        years = sorted(air_df["year"].dropna().unique().tolist()) if not air_df.empty else []
        year_filter = st.selectbox("Год", ["Все"] + years)
    with col3:
        limit = st.number_input("Лимит строк", 10, 5000, 200)

    query = "SELECT * FROM air WHERE 1=1"
    params: list = []
    if city_filter:
        query += " AND city LIKE ?"
        params.append(f"%{city_filter}%")
    if year_filter != "Все":
        query += " AND year = ?"
        params.append(int(year_filter))
    query += " ORDER BY year DESC, city, month_id LIMIT ?"
    params.append(int(limit))

    with sqlite3.connect(DB_PATH) as conn:
        filtered_df = pd.read_sql_query(query, conn, params=params)
    st.dataframe(filtered_df, use_container_width=True)

    action = st.radio("Операция", ["Добавить", "Изменить", "Удалить"], horizontal=True, key="air_action")

    month_options = {f"{row.month_number} — {row.month_name}": int(row.id) for row in months_df.itertuples()}

    if action == "Добавить":
        with st.form("add_air"):
            city = st.text_input("Город")
            station = st.number_input("ПНЗ / станция", min_value=0, value=1)
            year = st.number_input("Год", min_value=1900, max_value=2100, value=2019)
            month_label = st.selectbox("Месяц", list(month_options.keys()))
            value = st.number_input("Значение", min_value=0.0, value=0.0, step=0.01)
            annual_avg = st.number_input("Среднегодовое", min_value=0.0, value=0.0, step=0.01)
            source_url = st.text_input("Источник")
            submitted = st.form_submit_button("Добавить")
        if submitted:
            month_id = month_options[month_label]
            row_date = date(int(year), int(month_id), 1).isoformat()
            execute_sql(
                """
                INSERT INTO air (city, station, year, month_id, date, value, annual_avg, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (city.strip(), int(station), int(year), int(month_id), row_date, float(value), float(annual_avg), source_url.strip()),
            )
            st.success("Запись добавлена")
            st.rerun()

    elif action == "Изменить":
        if air_df.empty:
            st.info("Нет данных для изменения")
            return
        selected_id = st.number_input("ID записи для изменения", min_value=1, value=int(air_df["id"].min()))
        selected_rows = air_df[air_df["id"] == selected_id]
        if selected_rows.empty:
            st.warning("Запись с таким ID не найдена")
            return
        selected = selected_rows.iloc[0]
        current_month_label = next(
            (label for label, mid in month_options.items() if mid == int(selected["month_id"])),
            list(month_options.keys())[0],
        )
        with st.form("edit_air"):
            city = st.text_input("Город", str(selected["city"]))
            station_value = 0 if pd.isna(selected["station"]) else int(selected["station"])
            station = st.number_input("ПНЗ / станция", min_value=0, value=station_value)
            year = st.number_input("Год", min_value=1900, max_value=2100, value=int(selected["year"]))
            month_label = st.selectbox("Месяц", list(month_options.keys()), index=list(month_options.keys()).index(current_month_label))
            value = st.number_input("Значение", min_value=0.0, value=float(selected["value"]), step=0.01)
            annual = 0.0 if pd.isna(selected["annual_avg"]) else float(selected["annual_avg"])
            annual_avg = st.number_input("Среднегодовое", min_value=0.0, value=annual, step=0.01)
            source_url = st.text_input("Источник", "" if pd.isna(selected["source_url"]) else str(selected["source_url"]))
            submitted = st.form_submit_button("Сохранить")
        if submitted:
            month_id = month_options[month_label]
            row_date = date(int(year), int(month_id), 1).isoformat()
            execute_sql(
                """
                UPDATE air
                SET city = ?, station = ?, year = ?, month_id = ?, date = ?, value = ?, annual_avg = ?, source_url = ?
                WHERE id = ?
                """,
                (city.strip(), int(station), int(year), int(month_id), row_date, float(value), float(annual_avg), source_url.strip(), int(selected_id)),
            )
            st.success("Запись изменена")
            st.rerun()

    else:
        if air_df.empty:
            st.info("Нет данных для удаления")
            return
        selected_id = st.number_input("ID записи для удаления", min_value=1, value=int(air_df["id"].min()))
        if st.button("Удалить запись"):
            execute_sql("DELETE FROM air WHERE id = ?", (int(selected_id),))
            st.success("Запись удалена")
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="CRUD: Месяц и Воздух", layout="wide")
    st.title("База данных: Месяц и Воздух")

    if not db_exists():
        st.error("Файл database.db не найден. Сначала запустите: python INSTALL_BD.py")
        return

    table = st.sidebar.radio("Выберите таблицу", ["air", "months"])
    if table == "air":
        show_air_crud()
    else:
        show_months_crud()


if __name__ == "__main__":
    main()
