import os
import sqlite3
import pandas as pd
import streamlit as st
import requests

DB_FILE = "measurements.db"
# Klucz API do Gemini weźmiemy bezpiecznie ze Streamlit Secrets
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

st.set_page_config(page_title="Withings AI Dashboard", page_icon="📊", layout="centered")

st.title("⚖️ Withings Body Smart & AI Dashboard")
st.markdown("Panel analityczny działający w chmurze Streamlit.")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER UNIQUE,
            date TEXT,
            weight REAL,
            fat_mass REAL,
            muscle_mass REAL,
            hydration REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def load_data():
    if not os.path.exists(DB_FILE):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT timestamp, date, weight, fat_mass, muscle_mass, hydration FROM measurements ORDER BY timestamp ASC", conn)
    conn.close()
    if not df.empty:
        df['datetime'] = pd.to_datetime(df['date'])
    return df

df = load_data()

if df.empty:
    st.info("Brak pomiarów w bazie. Możesz dodać przykładowy pomiar lub zsynchronizować dane z Withings.")
    # Przycisk symulujący dodanie pomiaru testowego do bazy SQLite
    if st.button("Dodaj testowy pomiar"):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        import time
        now = int(time.time())
        cursor.execute("INSERT OR IGNORE INTO measurements (timestamp, date, weight, fat_mass, muscle_mass, hydration) VALUES (?, datetime('now'), ?, ?, ?, ?)", (now, 74.5, 18.2, 35.5, 55.0))
        conn.commit()
        conn.close()
        st.rerun()
else:
    st.subheader("📈 Trendy wagi i składu ciała")
    chart_data = df.set_index('datetime')[['weight']]
    st.line_chart(chart_data)
    
    latest = df.iloc[-1]
    col1, col2, col3 = st.columns(3)
    col1.metric("Ostatnia waga", f"{latest['weight']} kg")
    col2.metric("Masa tłuszczowa", f"{latest['fat_mass'] if latest['fat_mass'] else '-'} kg")
    col3.metric("Masa mięśniowa", f"{latest['muscle_mass'] if latest['muscle_mass'] else '-'} kg")

    st.markdown("---")
    st.subheader("🤖 Analiza ekspercka AI (Gemini)")
    
    if st.button("Wygeneruj analizę trendów"):
        if not GEMINI_API_KEY:
            st.error("Brak skonfigurowanego klucza GEMINI_API_KEY w Secrets Streamlit.")
        else:
            with st.spinner("Gemini analizuje dane..."):
                history_text = "\n".join([f"Data: {r['date']} | Waga: {r['weight']} kg" for _, r in df.tail(14).iterrows()])
                prompt = f"Oceń surowe dane pomiarowe z ostatnich 2 tygodni, odrzuć szumy i wskaż twardy trend:\n{history_text}"
                
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
                res = requests.post(gemini_url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}]})
                
                if res.status_code == 200:
                    analysis = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    st.success("Analiza gotowa:")
                    st.write(analysis)
                else:
                    st.error(f"Błąd API: {res.text}")

    with st.expander("Pełna historia pomiarów"):
        st.dataframe(df.sort_values(by='date', ascending=False))
