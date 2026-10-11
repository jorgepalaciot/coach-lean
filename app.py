import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date, timedelta

st.set_page_config(
    page_title="Coach Lean",
    page_icon="💪",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Estilo más amigable para celular
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        height: 3.3em;
        font-size: 1.15em;
        margin-bottom: 0.5rem;
    }
    .big-font { font-size: 1.3rem !important; }
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
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    client = gspread.authorize(creds)
    return client.open("CoachLeanHistorial").sheet1

def obtener_historial():
    columnas = ["Fecha", "Ejercicio", "Peso", "Series", "Reps", "RPE", "Notas"]
    try:
        sheet = get_sheet()
        data = sheet.get_all_records()
        if not data:
            return pd.DataFrame(columns=columnas)
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        for col in columnas:
            if col not in df.columns:
                df[col] = None
        return df[columnas]
    except Exception as e:
        st.warning(f"No se pudo leer el historial: {e}")
        return pd.DataFrame(columns=columnas)

# --------------------------
# Configuración de grupos y rutinas fijas
# --------------------------
REST_DAYS = {
    "Pecho": 2,
    "Espalda": 2,
    "Hombros": 2,
    "Bíceps": 1,
    "Tríceps": 3,
    "Piernas": 3,
    "Glúteos": 3,
    "Abs": 1
}

# Rutinas fijas (Opción A) - Postura integrada
RUTINAS = {
    "Pecho": [
        "Press Banca o mancuernas",
        "Press Inclinado mancuernas",
        "Aperturas",
        "Face Pulls"           # postura
    ],
    "Espalda": [
        "Dominadas o Jalón al pecho",
        "Remo con barra o mancuerna",
        "Face Pulls",          # postura
        "Remo invertido o Sears"
    ],
    "Hombros": [
        "Press Militar o mancuernas",
        "Elevaciones laterales",
        "Face Pulls",          # postura
        "Elevaciones posteriores"
    ],
    "Bíceps": [
        "Curl con barra o mancuernas",
        "Curl martillo",
        "Curl concentrado",
        "Curl en banco inclinado"
    ],
    "Tríceps": [
        "Fondos o Press cerrado",
        "Extensiones en polea",
        "Press francés",
        "Patadas de tríceps"
    ],
    "Piernas": [
        "Sentadilla o Prensa",
        "Peso Muerto Rumano",
        "Zancadas o Búlgaras",
        "Elevaciones de gemelos"
    ],
    "Glúteos": [
        "Hip Thrust",
        "Peso Muerto Rumano",
        "Patada de glúteo",
        "Puente de glúteo"
    ],
    "Abs": [
        "Dead Bug",            # postura + core
        "Pallof Press",        # postura + core
        "Plank",
        "Hanging Knee Raises"
    ]
}

# Técnica básica en 3 ángulos (se puede ir mejorando)
TECNICA = {
    "Face Pulls": {
        "frente": "Codos altos, tira hacia la cara con rotación externa. Escápulas juntas al final.",
        "perfil": "Tronco estable, codos terminan detrás del cuerpo.",
        "superior": "Se ve la retracción escapular y rotación externa de hombros."
    },
    "Dead Bug": {
        "frente": "Brazo y pierna contraria se extienden sin despegar la zona lumbar.",
        "perfil": "Lumbar siempre pegada al suelo. Movimiento lento y controlado.",
        "superior": "Cuerpo simétrico, ombligo hacia adentro."
    },
    "Pallof Press": {
        "frente": "Extiende los brazos al frente sin que el tronco rote.",
        "perfil": "Cadera y hombros alineados, core muy firme.",
        "superior": "Resistencia clara a la rotación."
    },
    "Plank": {
        "frente": "Cuerpo en línea recta, codos bajo los hombros.",
        "perfil": "Cadera neutra, glúteos apretados.",
        "superior": "Hombros lejos de las orejas."
    }
}

# --------------------------
# Estado de la sesión (para que no pregunte de nuevo el mismo día)
# --------------------------
hoy = str(date.today())

if "fecha_sesion" not in st.session_state:
    st.session_state.fecha_sesion = None
if "grupo_elegido" not in st.session_state:
    st.session_state.grupo_elegido = None
if "sesion_iniciada" not in st.session_state:
    st.session_state.sesion_iniciada = False

# Si cambió el día, reiniciamos
if st.session_state.fecha_sesion != hoy:
    st.session_state.sesion_iniciada = False
    st.session_state.grupo_elegido = None
    st.session_state.fecha_sesion = hoy

# --------------------------
# Funciones de recuperación
# --------------------------
def obtener_prioridad():
    df = obtener_historial()
    prioridad = []
    
    for grupo, descanso in REST_DAYS.items():
        if df.empty or "Ejercicio" not in df.columns:
            dias = 999
        else:
            # Buscamos la última vez que se entrenó un ejercicio de este grupo
            ejercicios_grupo = RUTINAS.get(grupo, [])
            mask = df["Ejercicio"].isin(ejercicios_grupo)
            if mask.any():
                df_temp = df.copy()
                df_temp["Fecha"] = pd.to_datetime(df_temp["Fecha"], errors="coerce")
                ultima = df_temp.loc[mask, "Fecha"].max()
                if pd.isna(ultima):
                    dias = 999
                else:
                    dias = (date.today() - ultima.date()).days
            else:
                dias = 999
        
        listo = dias >= descanso
        prioridad.append({
            "grupo": grupo,
            "dias": dias,
            "listo": listo,
            "descanso": descanso
        })
    
    # Ordenamos: primero los que están listos y llevan más días
    prioridad = sorted(prioridad, key=lambda x: (-x["listo"], -x["dias"]))
    return prioridad

# --------------------------
# INTERFAZ PRINCIPAL
# --------------------------
st.title("💪 Coach Lean")
st.caption("Postura • Abs • Cuerpo lean y musculoso")

# ===== PANTALLA DE INICIO DEL DÍA =====
if not st.session_state.sesion_iniciada:
    st.markdown("### ¿Qué quieres hacer hoy?")
    st.write("")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🏋️ Iniciar rutina de hoy", use_container_width=True):
            st.session_state.sesion_iniciada = True
            st.rerun()
    with col2:
        if st.button("📊 Revisar estadísticas", use_container_width=True):
            st.session_state.ver_stats = True
            st.rerun()

    if st.session_state.get("ver_stats", False):
        st.divider()
        st.subheader("Tu historial")
        df = obtener_historial()
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Aún no hay registros")
        if st.button("← Volver"):
            st.session_state.ver_stats = False
            st.rerun()

# ===== SESIÓN YA INICIADA =====
else:
    # Si todavía no eligió grupo
    if st.session_state.grupo_elegido is None:
        st.subheader("Elige el grupo muscular de hoy")
        st.write("Ordenados por prioridad de recuperación:")

        prioridad = obtener_prioridad()

        for item in prioridad:
            estado = "🟢 Listo" if item["listo"] else f"🟠 {item['dias']} días (mín. {item['descanso']})"
            if st.button(f"{item['grupo']}  —  {estado}", key=item["grupo"]):
                st.session_state.grupo_elegido = item["grupo"]
                st.session_state.hora_inicio = datetime.now().strftime("%H:%M")
                st.rerun()

    # Ya eligió grupo → mostrar ejercicios
    else:
        grupo = st.session_state.grupo_elegido
        st.success(f"Sesión de **{grupo}** iniciada a las {st.session_state.get('hora_inicio', '')}")
        
        if st.button("🔄 Cambiar de grupo muscular"):
            st.session_state.grupo_elegido = None
            st.rerun()

        st.divider()
        st.subheader(f"Ejercicios de {grupo}")

        df = obtener_historial()

        for ejercicio in RUTINAS[grupo]:
            with st.expander(f"📌 {ejercicio}", expanded=False):
                # Mostrar último peso
                if not df.empty and "Ejercicio" in df.columns:
                    coincidencias = df[df["Ejercicio"] == ejercicio]
                    if not coincidencias.empty:
                        try:
                            ultimo = coincidencias["Peso"].iloc[-1]
                            st.caption(f"Última vez: **{ultimo} kg**")
                        except:
                            pass

                # Técnica en 3 ángulos
                if ejercicio in TECNICA:
                    st.markdown("**Técnica en 3 ángulos**")
                    st.info(f"**Frente:** {TECNICA[ejercicio]['frente']}")
                    st.info(f"**Perfil:** {TECNICA[ejercicio]['perfil']}")
                    st.info(f"**Superior:** {TECNICA[ejercicio]['superior']}")

                # Formulario de registro
                with st.form(key=f"form_{ejercicio}"):
                    peso = st.number_input("Peso (kg)", min_value=0.0, step=0.5, key=f"peso_{ejercicio}")
                    series = st.number_input("Series", min_value=1, value=3, key=f"series_{ejercicio}")
                    reps = st.text_input("Reps (ej: 10,9,8)", key=f"reps_{ejercicio}")
                    rpe = st.slider("RPE", 1, 10, 7, key=f"rpe_{ejercicio}")
                    notas = st.text_area("Notas", key=f"notas_{ejercicio}")

                    if st.form_submit_button("💾 Guardar este ejercicio"):
                        try:
                            sheet = get_sheet()
                            sheet.append_row([
                                str(date.today()),
                                ejercicio,
                                peso,
                                series,
                                reps,
                                rpe,
                                notas
                            ])
                            st.success("✅ Guardado correctamente")
                            st.cache_resource.clear()
                        except Exception as e:
                            st.error(f"Error al guardar: {e}")

# Pie
st.markdown("---")
st.caption("Coach Lean • Enfocado en progresar sin perder recuperación")
