import os
import sqlite3
import pandas as pd
import streamlit as st
import requests
import time

DB_FILE = "measurements.db"

# Pobieranie sekretów ze Streamlit Secrets
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
WITHINGS_CLIENT_ID = st.secrets.get("WITHINGS_CLIENT_ID", "")
WITHINGS_CLIENT_SECRET = st.secrets.get("WITHINGS_CLIENT_SECRET", "")
WITHINGS_REFRESH_TOKEN = st.secrets.get("WITHINGS_REFRESH_TOKEN", "")

st.set_page_config(page_title="Withings AI Dashboard", page_icon="📊", layout="centered")

st.title("⚖️ Withings Body Smart & AI Dashboard")
st.markdown("Panel analityczny z automatyczną synchronizacją z Withings i AI.")

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

def get_withings_access_token():
    url = "https://wbsapi.withings.net/v2/oauth2"
    payload = {
        "action": "requesttoken",
        "grant_type": "refresh_token",
        "client_id": WITHINGS_CLIENT_ID,
        "client_secret": WITHINGS_CLIENT_SECRET,
        "refresh_token": WITHINGS_REFRESH_TOKEN
    }
    try:
        response = requests.post(url, data=payload)
        data = response.json()
        
        # Wyświetlimy status i odpowiedź w razie błędu
        if data.get("status") == 0:
            return data["body"].get("access_token")
        else:
            st.error(f"Szczegóły błędu Withings API: {data}")
    except Exception as e:
        st.error(f"Błąd krytyczny połączenia z Withings: {e}")
    return None

def fetch_withings_data():
    access_token = get_withings_access_token()
    if not access_token:
        st.warning("Nie udało się uzyskać dostępu do API Withings (sprawdź tokeny w Secrets).")
        return 0

    url = "https://wbsapi.withings.net/measure"
    payload = {
        "action": "getmeas",
        "access_token": access_token,
        "meastype": 1  # 1 = Waga (weight)
    }
    
    try:
        response = requests.post(url, data=payload)
        data = response.json()
        
        if data.get("status") == 0:
            measuregrps = data.get("body", {}).get("measuregrps", [])
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            added_count = 0
            
            for group in measuregrps:
                ts = group.get("date")
                date_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                
                weight = None
                fat_mass = None
                muscle_mass = None
                hydration = None
                
                for meas in group.get("measures", []):
                    val = meas.get("value") * (10 ** meas.get("unit"))
                    m_type = meas.get("type")
                    if m_type == 1:
                        weight = val
                    elif m_type == 6:
                        fat_mass = val
                    elif m_type == 76:
                        muscle_mass = val
                    elif m_type == 8:
                        hydration = val
                
                if weight:
                    cursor.execute('''
                        INSERT OR IGNORE INTO measurements (timestamp, date, weight, fat_mass, muscle_mass, hydration)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (ts, date_str, weight, fat_mass, muscle_mass, hydration))
                    if cursor.rowcount > 0:
                        added_count += 1
                        
            conn.commit()
            conn.close()
            return added_count
    except Exception as e:
        st.error(f"Błąd podczas pobierania pomiarów: {e}")
    return 0

# Przycisk synchronizacji w interfejsie
if st.button("🔄 Synchronizuj dane z Withings"):
    with st.spinner("Pobieram najnowsze pomiary z wagi..."):
        new_records = fetch_withings_data()
        if new_records > 0:
            st.success(f"Pomyślnie zsynchronizowano! Dodano nowych pomiarów: {new_records}")
            st.rerun()
        else:
            st.info("Brak nowych pomiarów do pobrania lub dane są aktualne.")

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
    st.info("Brak pomiarów w bazie. Kliknij powyższy przycisk synchronizacji lub dodaj testowy pomiar.")
    if st.button("Dodaj testowy pomiar"):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
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
    col2.metric("Masa tłuszczowa", f"{latest['fat_mass'] if pd.notna(latest['fat_mass']) else '-'} kg")
    col3.metric("Masa mięśniowa", f"{latest['muscle_mass'] if pd.notna(latest['muscle_mass']) else '-'} kg")

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
                    st.error(f"Błąd API Gemini: {res.text}")

    with st.expander("Pełna historia pomiarów"):
        st.dataframe(df.sort_values(by='date', ascending=False))

# --- TYMCZASOWY POMOCNIK DO WYMIANY KODU ---
st.divider()
st.subheader("🛠️ Panel pomocniczy: Generowanie Refresh Tokena")
temp_code = st.text_input("Wklej kod z paska adresu (to po code=):")
if st.button("Wygeneruj Refresh Token"):
    if temp_code:
        token_url = "https://wbsapi.withings.net/v2/oauth2"
        token_payload = {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": WITHINGS_CLIENT_ID,
            "client_secret": WITHINGS_CLIENT_SECRET,
            "code": temp_code.strip(),
            "redirect_uri": "http://127.0.0.1"
        }
        r = requests.post(token_url, data=token_payload)
        st.json(r.json())
    else:
        st.warning("Najpierw wklej kod!")
