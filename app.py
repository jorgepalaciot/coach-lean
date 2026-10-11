import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date
import json

st.set_page_config(page_title="Coach Lean", page_icon="💪", layout="wide")

# --------------------------
# Conexión a Google Sheets
# --------------------------
@st.cache_resource
def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    client = gspread.authorize(creds)
    return client.open("CoachLeanHistorial").sheet1  # Nombre de tu hoja

# --------------------------
# Configuración inicial
# --------------------------
st.title("💪 Coach Lean")
st.caption("Postura • Abs • Cuerpo lean y musculoso")

# Sidebar
st.sidebar.header("Configuración")
dias_entreno = st.sidebar.multiselect(
    "Días que puedes entrenar",
    ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"],
    default=["Lunes", "Miércoles", "Viernes", "Sábado"]
)

# --------------------------
# Rutina base (Postura + Abs + Lean)
# --------------------------
rutinas = {
    "Upper A (Postura + Pecho)": [
        {"ejercicio": "Face Pulls", "series": 4, "reps": "12-15", "notas": "Prioridad postura"},
        {"ejercicio": "Press Banca o mancuernas", "series": 4, "reps": "6-10", "notas": ""},
        {"ejercicio": "Remo con barra o mancuerna", "series": 4, "reps": "8-12", "notas": "Espalda alta"},
        {"ejercicio": "Elevaciones laterales", "series": 3, "reps": "12-15", "notas": ""},
        {"ejercicio": "Dead Bug", "series": 3, "reps": "10/lado", "notas": "Core anti-extensión"},
        {"ejercicio": "Pallof Press", "series": 3, "reps": "10/lado", "notas": "Anti-rotación"},
    ],
    "Lower A (Glúteos + Core)": [
        {"ejercicio": "Sentadilla o Prensa", "series": 4, "reps": "6-10", "notas": ""},
        {"ejercicio": "Peso Muerto Rumano", "series": 3, "reps": "8-12", "notas": ""},
        {"ejercicio": "Hip Thrust", "series": 3, "reps": "8-12", "notas": "Glúteos + postura pélvica"},
        {"ejercicio": "Elevaciones de gemelos", "series": 3, "reps": "12-15", "notas": ""},
        {"ejercicio": "Plank", "series": 3, "reps": "30-60 seg", "notas": ""},
        {"ejercicio": "Ab Wheel o Rollout", "series": 3, "reps": "8-12", "notas": ""},
    ],
    "Upper B (Postura + Espalda)": [
        {"ejercicio": "Band Pull-Apart o Face Pull", "series": 4, "reps": "15", "notas": "Postura"},
        {"ejercicio": "Dominadas o Jalón al pecho", "series": 4, "reps": "6-10", "notas": ""},
        {"ejercicio": "Press Militar o mancuernas", "series": "3", "reps": "8-12", "notas": ""},
        {"ejercicio": "Remo invertido o Sears", "series": 3, "reps": "10-12", "notas": ""},
        {"ejercicio": "Hanging Knee Raises", "series": 3, "reps": "10-15", "notas": "Abs"},
        {"ejercicio": "Side Plank", "series": 3, "reps": "20-40 seg/lado", "notas": ""},
    ],
    "Lower B + Core intenso": [
        {"ejercicio": "Peso Muerto convencional o trampa", "series": 3, "reps": "5-8", "notas": ""},
        {"ejercicio": "Zancadas o Búlgaras", "series": 3, "reps": "8-10/pierna", "notas": ""},
        {"ejercicio": "Curl femoral", "series": 3, "reps": "10-12", "notas": ""},
        {"ejercicio": "Hollow Body Hold", "series": 3, "reps": "20-40 seg", "notas": ""},
        {"ejercicio": "Cable Crunch o Crunch en máquina", "series": 3, "reps": "12-15", "notas": ""},
        {"ejercicio": "Farmer Walk", "series": 3, "reps": "30-40 seg", "notas": "Postura + core"},
    ]
}

# --------------------------
# Pestañas principales
# --------------------------
tab1, tab2, tab3, tab4 = st.tabs(["Hoy me toca", "Registrar entrenamiento", "Historial", "Coach AI"])

with tab1:
    st.subheader("¿Qué me toca hoy?")
    dia = st.selectbox("Elige el tipo de sesión", list(rutinas.keys()))
    
    st.markdown(f"### Rutina: {dia}")
    for i, ej in enumerate(rutinas[dia], 1):
        st.markdown(f"**{i}. {ej['ejercicio']}**")
        st.write(f"Series: {ej['series']}  |  Reps: {ej['reps']}  |  {ej['notas']}")
        with st.expander("Ver técnica correcta"):
            st.write("• Mantén el core activado y costillas abajo (muy importante para postura).")
            st.write("• Escápulas retraídas y deprimidas en ejercicios de empuje/tracción.")
            st.write("• Movimiento controlado, especialmente en la fase excéntrica.")
            st.write("• Si sientes la zona lumbar o cuello, baja el peso y corrige.")

with tab2:
    st.subheader("Registrar entrenamiento")
    with st.form("registro_form"):
        fecha = st.date_input("Fecha", value=date.today())
        ejercicio = st.text_input("Ejercicio")
        peso = st.number_input("Peso (kg)", min_value=0.0, step=0.5)
        series = st.number_input("Series", min_value=1, step=1)
        reps = st.text_input("Repeticiones (ej: 8,8,7)")
        rpe = st.slider("RPE (esfuerzo)", 1, 10, 7)
        notas = st.text_area("Notas (técnica, postura, cómo te sentiste)")
        
        submitted = st.form_submit_button("Guardar en Google Sheets")
        
        if submitted:
            try:
                sheet = get_sheet()
                sheet.append_row([
                    str(fecha),
                    ejercicio,
                    peso,
                    series,
                    reps,
                    rpe,
                    notas
                ])
                st.success("✅ Guardado correctamente")
            except Exception as e:
                st.error(f"Error al guardar: {e}")

with tab3:
    st.subheader("Historial")
    try:
        sheet = get_sheet()
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
            
            # Progreso de un ejercicio
            ejercicios = df["Ejercicio"].unique() if "Ejercicio" in df.columns else []
            if len(ejercicios) > 0:
                ej_sel = st.selectbox("Ver progreso de:", ejercicios)
                df_ej = df[df["Ejercicio"] == ej_sel]
                st.line_chart(df_ej.set_index("Fecha")["Peso"])
        else:
            st.info("Aún no hay registros")
    except Exception as e:
        st.warning(f"No se pudo cargar el historial. Revisa la conexión con Google Sheets. Error: {e}")

with tab4:
    st.subheader("Coach Lean AI")
    st.info("Aquí puedes conectar una IA gratuita (Gemini o Groq). Por ahora es un placeholder.")
    user_input = st.text_area("Escribe tu pregunta al coach")
    if st.button("Preguntar"):
        st.write("Respuesta del coach (aquí se conectará la IA):")
        st.write("Por ahora responde usando el system prompt que diseñamos. En el siguiente paso te enseño a conectar Gemini gratis.")
