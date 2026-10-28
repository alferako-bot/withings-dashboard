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
        "access_token": access_token
    }
    
    try:
        response = requests.post(url, data=payload)
        data = response.json()
        
        if data.get("status") == 0:
            measuregrps = data.get("body", {}).get("measuregrps", [])
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            updated_count = 0
            
            for group in measuregrps:
                ts = group.get("date")
                dt_utc = pd.to_datetime(ts, unit='s', utc=True)
                dt_local = dt_utc.tz_convert('Europe/Warsaw')
                date_str = dt_local.strftime('%Y-%m-%d %H:%M')
                
                weight = None
                fat_mass = None
                muscle_mass = None
                hydration = None
                
                for meas in group.get("measures", []):
                    val = meas.get("value") * (10 ** meas.get("unit"))
                    m_type = meas.get("type")
                    
                    # Rozszerzone mapowanie typów Withings API
                    if m_type == 1:
                        weight = round(val, 2)
                    elif m_type in [6, 8]:  # 6: Masa tłuszczowa / 8: woda (w niektórych wersjach)
                        if m_type == 6:
                            fat_mass = round(val, 2)
                    elif m_type == 76 or m_type == 88 or m_type == 7: 
                        muscle_mass = round(val, 2)
                    elif m_type == 8 or m_type == 77:
                        hydration = round(val, 2)
                    elif m_type == 5:
                        # Masa beztłuszczowa lub alternatywny tłuszcz
                        pass
                
                if weight is not None:
                    cursor.execute("SELECT id, fat_mass, muscle_mass, hydration FROM measurements WHERE timestamp = ?", (ts,))
                    row = cursor.fetchone()
                    
                    if row is None:
                        cursor.execute('''
                            INSERT INTO measurements (timestamp, date, weight, fat_mass, muscle_mass, hydration)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (ts, date_str, weight, fat_mass, muscle_mass, hydration))
                        updated_count += 1
                    else:
                        cursor.execute('''
                            UPDATE measurements 
                            SET weight = ?,
                                fat_mass = COALESCE(?, fat_mass),
                                muscle_mass = COALESCE(?, muscle_mass),
                                hydration = COALESCE(?, hydration)
                            WHERE timestamp = ?
                        ''', (weight, fat_mass, muscle_mass, hydration, ts))
                        updated_count += 1
                        
            conn.commit()
            conn.close()
            return updated_count
    except Exception as e:
        st.error(f"Błąd podczas pobierania pomiarów: {e}")
    return 0

# Przycisk synchronizacji w interfejsie
if st.button("🔄 Synchronizuj dane z Withings"):
    with st.spinner("Pobieram najnowsze pomiary i skład ciała..."):
        count = fetch_withings_data()
        if count > 0:
            st.success(f"Pomyślnie zsynchronizowano i zaktualizowano wpisy: {count}")
            st.rerun()
        else:
            st.info("Brak nowych danych do zsynchronizowania.")

def load_data():
    if not os.path.exists(DB_FILE):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT timestamp, date, weight, fat_mass, muscle_mass, hydration FROM measurements ORDER BY timestamp ASC", conn)
    conn.close()
    if not df.empty:
        dt_utc = pd.to_datetime(df['timestamp'], unit='s', utc=True)
        dt_local = dt_utc.dt.tz_convert('Europe/Warsaw')
        df['datetime'] = dt_local
        df['date'] = dt_local.dt.strftime('%Y-%m-%d %H:%M')
        
        df['weight'] = df['weight'].round(2)
        if 'fat_mass' in df.columns:
            df['fat_mass'] = df['fat_mass'].round(2)
        if 'muscle_mass' in df.columns:
            df['muscle_mass'] = df['muscle_mass'].round(2)
        if 'hydration' in df.columns:
            df['hydration'] = df['hydration'].round(2)
            
    return df

df = load_data()

if df.empty:
    st.info("Brak pomiarów w bazie. Kliknij powyższy przycisk synchronizacji lub dodaj testowy pomiar.")
    if st.button("Dodaj testowy pomiar"):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now = int(time.time())
        dt_local = pd.to_datetime(now, unit='s', utc=True).tz_convert('Europe/Warsaw')
        test_date_str = dt_local.strftime('%Y-%m-%d %H:%M')
        cursor.execute("INSERT OR IGNORE INTO measurements (timestamp, date, weight, fat_mass, muscle_mass, hydration) VALUES (?, ?, ?, ?, ?, ?)", (now, test_date_str, 74.50, 18.20, 35.50, 55.00))
        conn.commit()
        conn.close()
        st.rerun()
else:
    st.subheader("📈 Trendy wagi i składu ciała")
    chart_data = df.set_index('date')[['weight']]
    st.line_chart(chart_data)
    
    latest = df.iloc[-1]
    col1, col2, col3 = st.columns(3)
    col1.metric("Ostatnia waga", f"{latest['weight']:.2f} kg")
    col2.metric("Masa tłuszczowa", f"{latest['fat_mass']:.2f} kg" if pd.notna(latest['fat_mass']) else "- kg")
    col3.metric("Masa mięśniowa", f"{latest['muscle_mass']:.2f} kg" if pd.notna(latest['muscle_mass']) else "- kg")

    st.markdown("---")
    st.subheader("🤖 Analiza ekspercka AI (Gemini)")
    
    if st.button("Wygeneruj analizę trendów"):
        if not GEMINI_API_KEY:
            st.error("Brak skonfigurowanego klucza GEMINI_API_KEY w Secrets Streamlit.")
        else:
            with st.spinner("Gemini analizuje dane..."):
                history_text = "\n".join([f"Data: {r['date']} | Waga: {r['weight']:.2f} kg | Tłuszcz: {r.get('fat_mass', '-')} kg | Mięśnie: {r.get('muscle_mass', '-')} kg" for _, r in df.tail(14).iterrows()])
                prompt = f"Oceń surowe dane pomiarowe z ostatnich 2 tygodni, uwzględniając skład ciała, odrzuć szumy i wskaż twardy trend:\n{history_text}"
                
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
                res = requests.post(gemini_url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}]})
                
                if res.status_code == 200:
                    analysis = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    st.success("Analiza gotowa:")
                    st.write(analysis)
                else:
                    st.error(f"Błąd API Gemini: {res.text}")

    with st.expander("Pełna historia pomiarów"):
        history_table = df.sort_values(by='date', ascending=False)[['date', 'weight', 'fat_mass', 'muscle_mass', 'hydration']]
        st.dataframe(history_table.style.format({
            'weight': '{:.2f}',
            'fat_mass': lambda x: f"{x:.2f}" if pd.notna(x) else '-',
            'muscle_mass': lambda x: f"{x:.2f}" if pd.notna(x) else '-',
            'hydration': lambda x: f"{x:.2f}" if pd.notna(x) else '-'
        }), use_container_width=True)

    # --- PANEL DIAGNOSTYCZNY API ---
    with st.expander("🔍 Diagnostyka: Analiza typów pomiarów z Withings"):
        if st.button("Pokaż typy (m_type) z ostatniego pomiaru"):
            access_token = get_withings_access_token()
            if access_token:
                debug_res = requests.post("https://wbsapi.withings.net/measure", data={"action": "getmeas", "access_token": access_token})
                res_json = debug_res.json()
                if res_json.get("status") == 0:
                    grps = res_json.get("body", {}).get("measuregrps", [])
                    if grps:
                        latest_grp = grps[-1]
                        st.write("Wszystkie metryki w najnowszym wpisie pomiarowym:")
                        parsed_measures = []
                        for m in latest_grp.get("measures", []):
                            val = m.get("value") * (10 ** m.get("unit"))
                            parsed_measures.append({"type": m.get("type"), "value": val})
                        st.json(parsed_measures)
                    else:
                        st.warning("Brak grup pomiarowych.")
                else:
                    st.error(f"Błąd API: {res_json}")
