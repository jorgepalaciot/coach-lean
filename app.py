import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date, timedelta
from collections import defaultdict

st.set_page_config(
    page_title="Coach Lean",
    page_icon="💪",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Estilo móvil
st.markdown("""
<style>
    .stButton>button { width: 100%; height: 3.1em; font-size: 1.05em; }
    div[data-testid="stExpander"] { margin-bottom: 0.8rem; }
</style>
""", unsafe_allow_html=True)

# --------------------------
# Conexión Google Sheets
# --------------------------
@st.cache_resource
def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    client = gspread.authorize(creds)
    return client.open("CoachLeanHistorial").sheet1

# --------------------------
# Configuración por defecto de descansos (puedes cambiarlos en la app)
# --------------------------
DEFAULT_REST = {
    "Pecho": 2,
    "Espalda": 2,
    "Hombros": 2,
    "Bíceps": 1,
    "Tríceps": 3,
    "Piernas": 3,
    "Glúteos": 3,
    "Abs": 1,
    "Postura": 1   # Face pulls, etc.
}

# Información de ejercicios + músculos principales + técnica 3 ángulos
EJERCICIOS = {
    "Face Pulls": {
        "musculos": ["Postura", "Hombros", "Espalda"],
        "frente": "Codos altos, tira hacia la cara, rotación externa al final. Escápulas juntas.",
        "perfil": "Tronco estable, ligera inclinación atrás. Codos terminan detrás del cuerpo.",
        "superior": "Se ve claramente la retracción escapular y rotación externa de hombros."
    },
    "Press Banca o mancuernas": {
        "musculos": ["Pecho", "Tríceps", "Hombros"],
        "frente": "Hombros abajo y atrás, pies firmes. Mancuernas bajan controladas al pecho.",
        "perfil": "Arco natural en la espalda, glúteos pegados. Antebrazos verticales abajo.",
        "superior": "Codos a 45-60° del cuerpo. Pecho abierto."
    },
    "Remo con barra o mancuerna": {
        "musculos": ["Espalda", "Bíceps", "Postura"],
        "frente": "Pecho afuera, tira hacia el ombligo/bajo pecho.",
        "perfil": "Espalda casi paralela al suelo, cabeza neutra.",
        "superior": "Escápulas se juntan fuerte. Codos cerca del cuerpo."
    },
    "Dead Bug": {
        "musculos": ["Abs", "Postura"],
        "frente": "Brazo y pierna contraria se extienden sin que se despegue la lumbar.",
        "perfil": "Zona lumbar siempre pegada al suelo. Movimiento lento.",
        "superior": "Cuerpo simétrico, ombligo hacia adentro."
    },
    "Pallof Press": {
        "musculos": ["Abs", "Postura"],
        "frente": "Brazos se extienden al frente sin rotar el tronco.",
        "perfil": "Cadera y hombros alineados, core muy firme.",
        "superior": "Se observa la resistencia anti-rotación."
    },
    "Plank": {
        "musculos": ["Abs", "Postura"],
        "frente": "Cuerpo en línea recta, codos bajo hombros.",
        "perfil": "Cadera neutra, glúteos apretados.",
        "superior": "Hombros lejos de las orejas, tabla perfecta."
    },
    "Hip Thrust": {
        "musculos": ["Glúteos", "Piernas"],
        "frente": "Mentón metido, empuja con los talones hasta alinear cadera.",
        "perfil": "Tibia vertical arriba, extensión completa de cadera.",
        "superior": "Cadera sube recta, sin inclinarse a un lado."
    },
    "Peso Muerto Rumano": {
        "musculos": ["Piernas", "Glúteos", "Espalda"],
        "frente": "Barra cerca de las piernas, espalda neutra.",
        "perfil": "Cadera hacia atrás, ligera flexión de rodilla.",
        "superior": "Escápulas estables, barra sigue la línea media."
    },
    # Puedes seguir agregando más
}

# Rutinas predefinidas (se pueden expandir)
RUTINAS = {
    "Upper Postura + Pecho": ["Face Pulls", "Press Banca o mancuernas", "Remo con barra o mancuerna", "Dead Bug", "Pallof Press"],
    "Lower + Glúteos + Core": ["Hip Thrust", "Peso Muerto Rumano", "Plank", "Dead Bug"],
    "Enfocado Abs + Postura": ["Face Pulls", "Dead Bug", "Pallof Press", "Plank"],
    "Full Body Ligero": ["Face Pulls", "Remo con barra o mancuerna", "Hip Thrust", "Pallof Press"]
}

# --------------------------
# Funciones auxiliares
# --------------------------
def obtener_historial():
    try:
        sheet = get_sheet()
        data = sheet.get_all_records()
        return pd.DataFrame(data) if data else pd.DataFrame()
    except:
        return pd.DataFrame()

def ultimo_entrenamiento_por_musculo(df):
    if df.empty:
        return {}
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    ultimo = {}
    for musculo in DEFAULT_REST.keys():
        # Buscamos ejercicios que contengan ese músculo
        mask = df["Ejercicio"].apply(lambda x: musculo in EJERCICIOS.get(x, {}).get("musculos", []))
        if mask.any():
            ultimo[musculo] = df.loc[mask, "Fecha"].max().date()
        else:
            ultimo[musculo] = None
    return ultimo

def dias_desde(fecha):
    if fecha is None:
        return 999
    return (date.today() - fecha).days

# --------------------------
# Interfaz
# --------------------------
st.title("💪 Coach Lean")
st.caption("Postura • Abs • Cuerpo lean • Recuperación inteligente")

tab1, tab2, tab3, tab4 = st.tabs(["🏠 Hoy", "📝 Registrar", "📊 Historial", "⚙️ Configuración"])

# ===== TAB 1: HOY =====
with tab1:
    st.subheader("Estado de recuperación")

    df = obtener_historial()
    ultimos = ultimo_entrenamiento_por_musculo(df)

    # Mostrar estado de cada músculo
    cols = st.columns(2)
    listos = []
    for i, (musculo, descanso) in enumerate(DEFAULT_REST.items()):
        dias = dias_desde(ultimos.get(musculo))
        listo = dias >= descanso
        if listo:
            listos.append(musculo)
        with cols[i % 2]:
            color = "🟢" if listo else "🟠"
            st.write(f"{color} **{musculo}**: {dias} días (mín. {descanso})")

    st.divider()

    if listos:
        st.success(f"**Músculos listos hoy:** {', '.join(listos)}")
    else:
        st.info("Todos los músculos principales están en recuperación. Puedes hacer movilidad o abs suaves.")

    st.subheader("Recomendación de hoy")
    # Lógica simple de recomendación
    if "Pecho" in listos or "Postura" in listos:
        recomendacion = "Upper Postura + Pecho"
    elif "Piernas" in listos or "Glúteos" in listos:
        recomendacion = "Lower + Glúteos + Core"
    else:
        recomendacion = "Enfocado Abs + Postura"

    st.write(f"👉 Rutina recomendada: **{recomendacion}**")

    sesion = st.selectbox("O elige otra rutina:", list(RUTINAS.keys()), index=list(RUTINAS.keys()).index(recomendacion))

    st.markdown(f"### {sesion}")
    for nombre in RUTINAS[sesion]:
        info = EJERCICIOS.get(nombre, {})
        st.markdown(f"**• {nombre}**")
        with st.expander("👁️ Ver técnica en 3 ángulos"):
            if info:
                st.markdown("**Frente**")
                st.info(info.get("frente", ""))
                st.markdown("**Perfil**")
                st.info(info.get("perfil", ""))
                st.markdown("**Superior**")
                st.info(info.get("superior", ""))
            else:
                st.write("Descripción no disponible todavía.")

# ===== TAB 2: REGISTRAR =====
with tab2:
    st.subheader("Registrar entrenamiento")
    df = obtener_historial()

    with st.form("registro", clear_on_submit=True):
        fecha = st.date_input("Fecha", value=date.today())
        ejercicio = st.selectbox("Ejercicio", sorted(EJERCICIOS.keys()))
        
        # Mostrar último peso
        if not df.empty and ejercicio in df["Ejercicio"].values:
            ultimo_peso = df[df["Ejercicio"] == ejercicio]["Peso"].iloc[-1]
            st.caption(f"Última vez: {ultimo_peso} kg")
        
        peso = st.number_input("Peso (kg)", min_value=0.0, step=0.5)
        series = st.number_input("Series", min_value=1, value=3)
        reps = st.text_input("Reps (ej: 10,9,8)")
        rpe = st.slider("RPE", 1, 10, 7)
        notas = st.text_area("Notas")

        if st.form_submit_button("💾 Guardar"):
            try:
                sheet = get_sheet()
                sheet.append_row([str(fecha), ejercicio, peso, series, reps, rpe, notas])
                st.success("✅ Guardado correctamente")
                st.cache_resource.clear()  # limpiar cache
            except Exception as e:
                st.error(f"Error: {e}")

# ===== TAB 3: HISTORIAL =====
with tab3:
    st.subheader("Historial completo")
    df = obtener_historial()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Aún no hay registros")

# ===== TAB 4: CONFIGURACIÓN =====
with tab4:
    st.subheader("Días mínimos de descanso")
    st.write("Cambia estos valores según tu recuperación real. Se aplicarán en la recomendación.")
    st.info("Por ahora estos valores están fijos en el código. En la próxima versión los haremos editables y guardables en Sheets.")

    for musculo, dias in DEFAULT_REST.items():
        st.write(f"**{musculo}**: {dias} días de descanso")

    st.divider()
    st.write("Próximamente aquí podrás:")
    st.write("- Editar los días de descanso")
    st.write("- Crear y guardar tus propias rutinas")
    st.write("- Ajustar la prioridad de postura y abs")
