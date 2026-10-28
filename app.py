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
            timestamp INTEGER,
            date TEXT UNIQUE,
            weight REAL,
            fat_mass REAL,
            fat_ratio REAL,
            visceral_fat REAL,
            muscle_mass REAL,
            muscle_ratio REAL,
            hydration REAL,
            hydration_ratio REAL,
            bone_mass REAL,
            bone_ratio REAL,
            fat_free_mass REAL,
            fat_free_ratio REAL
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
            sessions = {}
            
            for group in measuregrps:
                ts = group.get("date")
                dt_utc = pd.to_datetime(ts, unit='s', utc=True)
                dt_local = dt_utc.tz_convert('Europe/Warsaw')
                date_str = dt_local.strftime('%Y-%m-%d %H:%M')
                
                if date_str not in sessions:
                    sessions[date_str] = {
                        "timestamp": ts,
                        "weight": None,
                        "fat_mass": None,
                        "fat_ratio": None,
                        "visceral_fat": None,
                        "muscle_mass": None,
                        "muscle_ratio": None,
                        "hydration": None,
                        "hydration_ratio": None,
                        "bone_mass": None,
                        "bone_ratio": None,
                        "fat_free_mass": None,
                        "fat_free_ratio": None
                    }
                
                for meas in group.get("measures", []):
                    val = meas.get("value") * (10 ** meas.get("unit"))
                    m_type = meas.get("type")
                    
                    if m_type == 1:
                        sessions[date_str]["weight"] = round(val, 2)
                    elif m_type == 6:
                        sessions[date_str]["fat_mass"] = round(val, 2)
                    elif m_type in [10, 12]:
                        sessions[date_str]["fat_ratio"] = round(val, 1)
                    elif m_type in [74, 27, 75]:
                        sessions[date_str]["visceral_fat"] = round(val, 2)
                    elif m_type in [76, 88]:
                        sessions[date_str]["muscle_mass"] = round(val, 2)
                    elif m_type == 8:
                        sessions[date_str]["hydration"] = round(val, 2)
                    elif m_type == 77:
                        sessions[date_str]["hydration_ratio"] = round(val, 1)
                    elif m_type == 5:
                        sessions[date_str]["bone_mass"] = round(val, 2)
                    elif m_type == 91:
                        sessions[date_str]["fat_free_mass"] = round(val, 2)

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            updated_count = 0
            
            for date_str, metrics in sessions.items():
                w = metrics["weight"]
                if w is not None:
                    # Automatyczne uzupełnienie brakujących procentów, jeśli mamy wartości w kg
                    if metrics["fat_mass"] and not metrics["fat_ratio"]:
                        metrics["fat_ratio"] = round((metrics["fat_mass"] / w) * 100, 1)
                    if metrics["bone_mass"] and not metrics["bone_ratio"]:
                        metrics["bone_ratio"] = round((metrics["bone_mass"] / w) * 100, 1)
                    if metrics["fat_free_mass"] and not metrics["fat_free_ratio"]:
                        metrics["fat_free_ratio"] = round((metrics["fat_free_mass"] / w) * 100, 1)

                    cursor.execute('''
                        INSERT INTO measurements (
                            timestamp, date, weight, fat_mass, fat_ratio, visceral_fat, 
                            muscle_mass, muscle_ratio, hydration, hydration_ratio, 
                            bone_mass, bone_ratio, fat_free_mass, fat_free_ratio
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(date) DO UPDATE SET
                            weight = COALESCE(excluded.weight, weight),
                            fat_mass = COALESCE(excluded.fat_mass, fat_mass),
                            fat_ratio = COALESCE(excluded.fat_ratio, fat_ratio),
                            visceral_fat = COALESCE(excluded.visceral_fat, visceral_fat),
                            muscle_mass = COALESCE(excluded.muscle_mass, muscle_mass),
                            muscle_ratio = COALESCE(excluded.muscle_ratio, muscle_ratio),
                            hydration = COALESCE(excluded.hydration, hydration),
                            hydration_ratio = COALESCE(excluded.hydration_ratio, hydration_ratio),
                            bone_mass = COALESCE(excluded.bone_mass, bone_mass),
                            bone_ratio = COALESCE(excluded.bone_ratio, bone_ratio),
                            fat_free_mass = COALESCE(excluded.fat_free_mass, fat_free_mass),
                            fat_free_ratio = COALESCE(excluded.fat_free_ratio, fat_free_ratio)
                    ''', (
                        metrics["timestamp"], date_str, w, 
                        metrics["fat_mass"], metrics["fat_ratio"], metrics["visceral_fat"],
                        metrics["muscle_mass"], metrics["muscle_ratio"], 
                        metrics["hydration"], metrics["hydration_ratio"],
                        metrics["bone_mass"], metrics["bone_ratio"], 
                        metrics["fat_free_mass"], metrics["fat_free_ratio"]
                    ))
                    updated_count += 1
                        
            conn.commit()
            conn.close()
            return updated_count
    except Exception as e:
        st.error(f"Błąd podczas pobierania pomiarów: {e}")
    return 0

# Panel sterowania w interfejsie
col_btn1, col_btn2 = st.columns(2)
with col_btn1:
    if st.button("🔄 Synchronizuj dane z Withings"):
        with st.spinner("Pobieram i scalam pełną historię składu ciała z Withings..."):
            count = fetch_withings_data()
            if count > 0:
                st.success(f"Pomyślnie zsynchronizowano i scalono wpisy: {count}")
                st.rerun()
            else:
                st.info("Brak danych do zsynchronizowania.")

with col_btn2:
    if st.button("🗑️ Resetuj i wyczyść bazę"):
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            st.success("Baza danych została wyczyszczona!")
            st.rerun()
        else:
            st.info("Baza danych nie istnieje.")

def load_data():
    if not os.path.exists(DB_FILE):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM measurements ORDER BY timestamp ASC", conn)
    conn.close()
    if not df.empty:
        dt_utc = pd.to_datetime(df['timestamp'], unit='s', utc=True)
        dt_local = dt_utc.dt.tz_convert('Europe/Warsaw')
        df['datetime'] = dt_local
        
        # Zaokrąglenia
        for col in ['weight', 'fat_mass', 'visceral_fat', 'muscle_mass', 'hydration', 'bone_mass', 'fat_free_mass']:
            if col in df.columns:
                df[col] = df[col].round(2)
        for col in ['fat_ratio', 'muscle_ratio', 'hydration_ratio', 'bone_ratio', 'fat_free_ratio']:
            if col in df.columns:
                df[col] = df[col].round(1)
            
    return df

df = load_data()

if df.empty:
    st.info("Brak pomiarów w bazie. Kliknij przycisk synchronizacji powyżej.")
else:
    st.subheader("📈 Trendy wagi i składu ciała")
    
    metric_labels = {
        'weight': 'Waga (kg)',
        'fat_mass': 'Masa tłuszczowa (kg)',
        'fat_ratio': 'Procent tłuszczu (%)',
        'visceral_fat': 'Tłuszcz trzewny',
        'muscle_mass': 'Masa mięśniowa (kg)',
        'muscle_ratio': 'Procent mięśni (%)',
        'hydration': 'Hydratacja (kg)',
        'hydration_ratio': 'Procent wody (%)',
        'bone_mass': 'Masa kości (kg)',
        'bone_ratio': 'Procent kości (%)',
        'fat_free_mass': 'Masa beztłuszczowa (kg)',
        'fat_free_ratio': 'Procent masy beztłuszczowej (%)'
    }
    
    selected_metrics = st.multiselect(
        "Wybierz serie danych do wyświetlenia na wykresie:",
        options=list(metric_labels.keys()),
        default=['weight'],
        format_func=lambda x: metric_labels[x]
    )
    
    if selected_metrics:
        chart_data = df.set_index('date')[selected_metrics]
        st.line_chart(chart_data)
    else:
        st.warning("Wybierz przynajmniej jedną serię danych do wykresu.")
    
    latest = df.iloc[-1]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ostatnia waga", f"{latest['weight']:.2f} kg")
    col2.metric("Tłuszcz", f"{latest.get('fat_mass', 0):.2f} kg ({latest.get('fat_ratio', 0)}%)" if pd.notna(latest.get('fat_mass')) else "-")
    col3.metric("Tłuszcz trzewny", f"{latest.get('visceral_fat', 0):.2f}" if pd.notna(latest.get('visceral_fat')) else "-")
    col4.metric("M. beztłuszczowa", f"{latest.get('fat_free_ratio', 0)}%" if pd.notna(latest.get('fat_free_ratio')) else "-")

    st.markdown("---")
    st.subheader("🤖 Analiza ekspercka AI (Gemini)")
    
    if st.button("Wygeneruj analizę trendów"):
        if not GEMINI_API_KEY:
            st.error("Brak skonfigurowanego klucza GEMINI_API_KEY w Secrets Streamlit.")
        else:
            with st.spinner("Gemini analizuje dane..."):
                history_text = "\n".join([
                    f"Data: {r['date']} | Waga: {r['weight']:.2f} kg | Tłuszcz: {r.get('fat_mass', '-')} kg ({r.get('fat_ratio', '-')}%) | Tłuszcz trzewny: {r.get('visceral_fat', '-')} | Beztłuszczowa: {r.get('fat_free_ratio', '-f')}% | Kości: {r.get('bone_ratio', '-f')}%" 
                    for _, r in df.tail(14).iterrows()
                ])
                prompt = f"Oceń surowe dane pomiarowe z ostatnich 2 tygodni, uwzględniając pełny skład ciała (waga, tłuszcz kg/%, tłuszcz trzewny, masa beztłuszczowa %, kości %), odrzuć szumy i wskaż twardy trend:\n{history_text}"
                
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
                res = requests.post(gemini_url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}]})
                
                if res.status_code == 200:
                    analysis = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    st.success("Analiza gotowa:")
                    st.write(analysis)
                else:
                    st.error(f"Błąd API Gemini: {res.text}")

    with st.expander("Pełna historia pomiarów"):
        history_table = df.sort_values(by='date', ascending=False)[[
            'date', 'weight', 'fat_mass', 'fat_ratio', 'visceral_fat', 
            'muscle_mass', 'muscle_ratio', 'bone_mass', 'bone_ratio', 'fat_free_ratio'
        ]]
        st.dataframe(history_table.style.format({
            'weight': '{:.2f}',
            'fat_mass': lambda x: f"{x:.2f} kg" if pd.notna(x) else '-',
            'fat_ratio': lambda x: f"{x:.1f}%" if pd.notna(x) else '-',
            'visceral_fat': lambda x: f"{x:.2f}" if pd.notna(x) else '-',
            'muscle_mass': lambda x: f"{x:.2f} kg" if pd.notna(x) else '-',
            'muscle_ratio': lambda x: f"{x:.1f}%" if pd.notna(x) else '-',
            'bone_mass': lambda x: f"{x:.2f} kg" if pd.notna(x) else '-',
            'bone_ratio': lambda x: f"{x:.1f}%" if pd.notna(x) else '-',
            'fat_free_ratio': lambda x: f"{x:.1f}%" if pd.notna(x) else '-'
        }), use_container_width=True)
