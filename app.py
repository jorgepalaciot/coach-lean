import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date

st.set_page_config(
    page_title="Coach Lean",
    page_icon="💪",
    layout="centered",          # Mejor para móvil
    initial_sidebar_state="collapsed"
)

# Estilo para que se vea mejor en celular
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        height: 3.2em;
        font-size: 1.1em;
    }
    .exercise-card {
        padding: 1.2rem;
        border-radius: 12px;
        background-color: #f0f2f6;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --------------------------
# Conexión a Google Sheets
# --------------------------
@st.cache_resource
def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    client = gspread.authorize(creds)
    return client.open("CoachLeanHistorial").sheet1

# --------------------------
# Base de datos de ejercicios con técnica en 3 ángulos
# --------------------------
ejercicios_info = {
    "Face Pulls": {
        "frente": "De pie o sentado, codos a la altura de los hombros, tira hacia la cara abriendo las manos. Escápulas juntas al final.",
        "perfil": "Tronco erguido, ligera inclinación hacia atrás. Los codos quedan detrás del cuerpo al final del movimiento.",
        "superior": "Desde arriba se ve cómo las escápulas se juntan y los hombros rotan externamente. Evita encoger el cuello."
    },
    "Press Banca o mancuernas": {
        "frente": "Hombros abajo y atrás, pies firmes en el suelo. Las mancuernas bajan controladas hasta la altura del pecho.",
        "perfil": "Espalda ligeramente arqueada natural, glúteos pegados al banco. Antebrazos verticales en la parte baja.",
        "superior": "Desde arriba se ve el pecho abierto y los codos a unos 45-60° respecto al cuerpo (no 90°)."
    },
    "Remo con barra o mancuerna": {
        "frente": "Espalda recta, pecho hacia afuera. Tira la barra/mancuerna hacia el ombligo o bajo pecho.",
        "perfil": "Cadera flexionada, espalda casi paralela al suelo. La cabeza sigue la línea de la columna.",
        "superior": "Escápulas se juntan fuertemente al final. Los codos pasan cerca del cuerpo."
    },
    "Dead Bug": {
        "frente": "Acostado boca arriba, brazos extendidos hacia el techo, rodillas a 90°. Baja brazo y pierna contraria sin que se arquee la espalda.",
        "perfil": "La zona lumbar permanece pegada al suelo en todo momento. Movimiento lento y controlado.",
        "superior": "Desde arriba se ve el cuerpo simétrico. El ombligo se mantiene hacia adentro (core activado)."
    },
    "Pallof Press": {
        "frente": "De pie, de lado a la polea o banda. Extiende los brazos al frente sin que el tronco rote.",
        "perfil": "Cadera y hombros alineados, core muy firme. No se permite que el cuerpo gire.",
        "superior": "Desde arriba se ve cómo resistes la rotación. Los brazos salen rectos desde el centro del pecho."
    },
    "Plank": {
        "frente": "Codos bajo los hombros, cuerpo en línea recta desde la cabeza hasta los talones.",
        "perfil": "Cadera ni arriba ni abajo. Glúteos apretados y core activo. Mirada al suelo.",
        "superior": "Hombros lejos de las orejas, escápulas estables. El cuerpo forma una tabla perfecta."
    },
    # Puedes ir agregando más ejercicios aquí
}

# Rutinas
rutinas = {
    "Upper A (Postura + Pecho)": [
        {"nombre": "Face Pulls", "series": "4", "reps": "12-15"},
        {"nombre": "Press Banca o mancuernas", "series": "4", "reps": "6-10"},
        {"nombre": "Remo con barra o mancuerna", "series": "4", "reps": "8-12"},
        {"nombre": "Dead Bug", "series": "3", "reps": "10/lado"},
        {"nombre": "Pallof Press", "series": "3", "reps": "10/lado"},
    ],
    "Lower A (Glúteos + Core)": [
        {"nombre": "Sentadilla o Prensa", "series": "4", "reps": "6-10"},
        {"nombre": "Peso Muerto Rumano", "series": "3", "reps": "8-12"},
        {"nombre": "Hip Thrust", "series": "3", "reps": "8-12"},
        {"nombre": "Plank", "series": "3", "reps": "30-60 seg"},
        {"nombre": "Ab Wheel o Rollout", "series": "3", "reps": "8-12"},
    ],
    "Upper B (Postura + Espalda)": [
        {"nombre": "Face Pulls", "series": "4", "reps": "15"},
        {"nombre": "Dominadas o Jalón al pecho", "series": "4", "reps": "6-10"},
        {"nombre": "Press Militar o mancuernas", "series": "3", "reps": "8-12"},
        {"nombre": "Hanging Knee Raises", "series": "3", "reps": "10-15"},
        {"nombre": "Side Plank", "series": "3", "reps": "20-40 seg/lado"},
    ],
    "Lower B + Core intenso": [
        {"nombre": "Peso Muerto convencional o trampa", "series": "3", "reps": "5-8"},
        {"nombre": "Zancadas o Búlgaras", "series": "3", "reps": "8-10/pierna"},
        {"nombre": "Hollow Body Hold", "series": "3", "reps": "20-40 seg"},
        {"nombre": "Cable Crunch o Crunch en máquina", "series": "3", "reps": "12-15"},
        {"nombre": "Farmer Walk", "series": "3", "reps": "30-40 seg"},
    ]
}

# --------------------------
# Interfaz principal
# --------------------------
st.title("💪 Coach Lean")
st.caption("Postura • Abs • Cuerpo lean y musculoso")

tab1, tab2, tab3 = st.tabs(["🏠 Hoy me toca", "📝 Registrar", "📊 Historial"])

with tab1:
    st.subheader("¿Qué entrenamiento haces hoy?")
    sesion = st.selectbox(
        "Elige la sesión:",
        list(rutinas.keys()),
        label_visibility="collapsed"
    )

    st.markdown(f"### {sesion}")
    st.write("")

    for i, ej in enumerate(rutinas[sesion], 1):
        with st.container():
            st.markdown(f"**{i}. {ej['nombre']}**")
            st.markdown(f"Series: **{ej['series']}**  |  Reps: **{ej['reps']}**")

            # Botón para ver técnica
            with st.expander("👁️ Ver técnica en 3 ángulos"):
                info = ejercicios_info.get(ej['nombre'], None)
                if info:
                    st.markdown("### 正面 • Visión de Frente")
                    st.info(info["frente"])
                    st.markdown("### 侧面 • Visión de Perfil")
                    st.info(info["perfil"])
                    st.markdown("### 上面 • Visión Superior")
                    st.info(info["superior"])
                else:
                    st.warning("Todavía no tengo la descripción detallada de este ejercicio. Usa técnica controlada y core activado.")

            st.divider()

with tab2:
    st.subheader("Registrar entrenamiento")
    with st.form("registro", clear_on_submit=True):
        fecha = st.date_input("Fecha", value=date.today())
        ejercicio = st.selectbox("Ejercicio", sorted(list(ejercicios_info.keys()) + [
            "Sentadilla o Prensa", "Peso Muerto Rumano", "Hip Thrust",
            "Dominadas o Jalón al pecho", "Press Militar o mancuernas",
            "Hanging Knee Raises", "Side Plank", "Ab Wheel o Rollout",
            "Peso Muerto convencional o trampa", "Zancadas o Búlgaras",
            "Hollow Body Hold", "Cable Crunch o Crunch en máquina", "Farmer Walk"
        ]))
        peso = st.number_input("Peso (kg)", min_value=0.0, step=0.5, value=0.0)
        series = st.number_input("Series completadas", min_value=1, step=1, value=3)
        reps = st.text_input("Repeticiones (ej: 10,9,8)", value="")
        rpe = st.slider("RPE (esfuerzo percibido)", 1, 10, 7)
        notas = st.text_area("Notas (postura, cómo te sentiste, etc.)")

        if st.form_submit_button("💾 Guardar entrenamiento"):
            try:
                sheet = get_sheet()
                sheet.append_row([
                    str(fecha), ejercicio, peso, series, reps, rpe, notas
                ])
                st.success("✅ Guardado correctamente")
            except Exception as e:
                st.error(f"Error: {e}")

with tab3:
    st.subheader("Tu historial")
    try:
        sheet = get_sheet()
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True, height=400)
        else:
            st.info("Aún no hay registros")
    except Exception as e:
        st.warning(f"No se pudo cargar el historial: {e}")

# Pie de página
st.markdown("---")
st.caption("Coach Lean • Enfocado en postura, abs y físico lean")
