import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date
from collections import defaultdict

st.set_page_config(
    page_title="Coach Lean",
    page_icon="💪",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        height: 3.3em;
        font-size: 1.15em;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# --------------------------
# Conexión a Google Sheets
# --------------------------
@st.cache_resource
def get_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    return gspread.authorize(creds)

def get_sheet_historial():
    client = get_client()
    return client.open("CoachLeanHistorial").sheet1

def get_sheet_rutinas():
    client = get_client()
    return client.open("CoachLeanHistorial").worksheet("Rutinas")

def obtener_historial():
    columnas = ["Fecha", "Ejercicio", "Peso", "Series", "Reps", "RPE", "Notas"]
    try:
        sheet = get_sheet_historial()
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
        st.warning(f"Error leyendo historial: {e}")
        return pd.DataFrame(columns=columnas)

def obtener_rutinas_activas():
    """Lee las rutinas activas desde la pestaña Rutinas y las agrupa por grupo muscular"""
    try:
        sheet = get_sheet_rutinas()
        data = sheet.get_all_records()
        if not data:
            return {}
        
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        
        # Filtrar solo las activas
        if "Activo" in df.columns:
            df = df[df["Activo"].astype(str).str.strip().str.lower() == "sí"]
        
        # Ordenar por la columna Orden
        if "Orden" in df.columns:
            df["Orden"] = pd.to_numeric(df["Orden"], errors="coerce")
            df = df.sort_values(["Grupo", "Orden"])
        
        rutinas = defaultdict(list)
        for _, row in df.iterrows():
            grupo = str(row.get("Grupo", "")).strip()
            ejercicio = str(row.get("Ejercicio", "")).strip()
            if grupo and ejercicio:
                rutinas[grupo].append(ejercicio)
        
        return dict(rutinas)
    except Exception as e:
        st.error(f"Error leyendo rutinas: {e}")
        return {}

# Días de descanso recomendados
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

# --------------------------
# Estado de sesión (para el flujo del día)
# --------------------------
hoy = str(date.today())

if "fecha_sesion" not in st.session_state:
    st.session_state.fecha_sesion = None
if "grupo_elegido" not in st.session_state:
    st.session_state.grupo_elegido = None
if "sesion_iniciada" not in st.session_state:
    st.session_state.sesion_iniciada = False
if "ver_stats" not in st.session_state:
    st.session_state.ver_stats = False
if "ver_programa" not in st.session_state:
    st.session_state.ver_programa = False

# Reiniciar si cambió el día
if st.session_state.fecha_sesion != hoy:
    st.session_state.sesion_iniciada = False
    st.session_state.grupo_elegido = None
    st.session_state.fecha_sesion = hoy
    st.session_state.ver_stats = False
    st.session_state.ver_programa = False

# --------------------------
# Interfaz
# --------------------------
st.title("💪 Coach Lean")
st.caption("Postura • Abs • Cuerpo lean y musculoso • Programas flexibles")

rutinas = obtener_rutinas_activas()

# ===== PANTALLA DE INICIO DEL DÍA =====
if not st.session_state.sesion_iniciada:

    st.markdown("### ¿Qué quieres hacer hoy?")
    st.write("")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🏋️ Iniciar rutina de hoy", use_container_width=True):
            st.session_state.sesion_iniciada = True
            st.session_state.ver_stats = False
            st.session_state.ver_programa = False
            st.rerun()
    with col2:
        if st.button("📊 Revisar estadísticas", use_container_width=True):
            st.session_state.ver_stats = True
            st.session_state.ver_programa = False
            st.rerun()

    if st.button("📋 Ver mi programa completo", use_container_width=True):
        st.session_state.ver_programa = True
        st.session_state.ver_stats = False
        st.rerun()

    # Ver estadísticas
    if st.session_state.ver_stats:
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

    # Ver programa completo
    if st.session_state.ver_programa:
        st.divider()
        st.subheader("📋 Mi Programa Actual (3 meses)")
        if not rutinas:
            st.warning("No se encontraron rutinas activas. Revisa la pestaña 'Rutinas' en Google Sheets.")
        else:
            for grupo, ejercicios in rutinas.items():
                with st.expander(f"**{grupo}**"):
                    for i, ej in enumerate(ejercicios, 1):
                        st.write(f"{i}. {ej}")
        if st.button("← Volver al inicio"):
            st.session_state.ver_programa = False
            st.rerun()

# ===== SESIÓN INICIADA =====
else:
    if st.session_state.grupo_elegido is None:
        st.subheader("Elige el grupo muscular de hoy")
        st.caption("Ordenados por prioridad de recuperación")

        df_hist = obtener_historial()
        prioridad = []

        for grupo in rutinas.keys():
            descanso = REST_DAYS.get(grupo, 2)
            dias = 999
            if not df_hist.empty and "Ejercicio" in df_hist.columns:
                ejercicios_grupo = rutinas[grupo]
                mask = df_hist["Ejercicio"].isin(ejercicios_grupo)
                if mask.any():
                    df_temp = df_hist.copy()
                    df_temp["Fecha"] = pd.to_datetime(df_temp["Fecha"], errors="coerce")
                    ultima = df_temp.loc[mask, "Fecha"].max()
                    if not pd.isna(ultima):
                        dias = (date.today() - ultima.date()).days

            listo = dias >= descanso
            prioridad.append({
                "grupo": grupo,
                "dias": dias,
                "listo": listo,
                "descanso": descanso
            })

        prioridad = sorted(prioridad, key=lambda x: (-x["listo"], -x["dias"]))

        for item in prioridad:
            estado = "🟢 Listo" if item["listo"] else f"🟠 {item['dias']}d (mín {item['descanso']})"
            if st.button(f"{item['grupo']}  —  {estado}", key=item["grupo"]):
                st.session_state.grupo_elegido = item["grupo"]
                st.session_state.hora_inicio = datetime.now().strftime("%H:%M")
                st.rerun()

    else:
        grupo = st.session_state.grupo_elegido
        st.success(f"Sesión de **{grupo}** iniciada a las {st.session_state.get('hora_inicio', '')}")

        if st.button("🔄 Cambiar de grupo"):
            st.session_state.grupo_elegido = None
            st.rerun()

        st.divider()
        st.subheader(f"Ejercicios de {grupo}")

        ejercicios = rutinas.get(grupo, [])
        df = obtener_historial()

        if not ejercicios:
            st.warning("No hay ejercicios activos para este grupo.")
        else:
            for ejercicio in ejercicios:
                with st.expander(f"📌 {ejercicio}"):

# Mostrar último registro del ejercicio
            if not df.empty and "Ejercicio" in df.columns:
                coincidencias = df[df["Ejercicio"] == ejercicio].copy()
                if not coincidencias.empty:
                    try:
                        # Ordenamos por fecha para obtener el más reciente
                        coincidencias["Fecha"] = pd.to_datetime(coincidencias["Fecha"], errors="coerce")
                        ultimo_registro = coincidencias.sort_values("Fecha", ascending=False).iloc[0]
                        
                        st.markdown("### Último entrenamiento")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Peso", f"{ultimo_registro.get('Peso', '-')} kg")
                        with col2:
                            st.metric("Series", f"{ultimo_registro.get('Series', '-')}")
                        with col3:
                            st.metric("RPE", f"{ultimo_registro.get('RPE', '-')}")
                        
                        # Mostrar el detalle de las series si existe
                        detalle = ultimo_registro.get("Reps", "")
                        if detalle and str(detalle).strip() != "":
                            st.info(f"**Detalle de series:** {detalle}")
                        
                        st.caption(f"Fecha: {ultimo_registro.get('Fecha', '')}")
                        st.divider()
                    except Exception as e:
                        st.caption("No se pudo cargar el último registro")
                    
                    # Último peso
                    if not df.empty and "Ejercicio" in df.columns:
                        coincidencias = df[df["Ejercicio"] == ejercicio]
                        if not coincidencias.empty:
                            try:
                                ultimo = coincidencias["Peso"].iloc[-1]
                                st.caption(f"Última vez: **{ultimo} kg**")
                            except:
                                pass

                with st.form(key=f"form_{ejercicio}"):
                    st.markdown("**Registra cada serie:**")
                    
                    # Creamos 5 series posibles
                    series_data = []
                    cols = st.columns([1, 2, 2])
                    with cols[0]:
                        st.markdown("**Serie**")
                    with cols[1]:
                        st.markdown("**Peso (kg)**")
                    with cols[2]:
                        st.markdown("**Reps**")
                
                    for i in range(1, 6):
                        c1, c2, c3 = st.columns([1, 2, 2])
                        with c1:
                            st.markdown(f"**{i}**")
                        with c2:
                            peso = st.number_input(
                                f"Peso serie {i}", 
                                min_value=0.0, 
                                step=0.5, 
                                value=0.0,
                                label_visibility="collapsed",
                                key=f"peso_{ejercicio}_{i}"
                            )
                        with c3:
                            reps = st.number_input(
                                f"Reps serie {i}", 
                                min_value=0, 
                                step=1, 
                                value=0,
                                label_visibility="collapsed",
                                key=f"reps_{ejercicio}_{i}"
                            )
                        if peso > 0 or reps > 0:
                            series_data.append(f"{peso}kg x {reps}")
                
                    rpe = st.slider("RPE (esfuerzo percibido)", 1, 10, 7, key=f"rpe_{ejercicio}")
                    notas = st.text_area("Notas (opcional)", key=f"n_{ejercicio}")
                
                    if st.form_submit_button("💾 Guardar ejercicio"):
                        if not series_data:
                            st.warning("Registra al menos una serie")
                        else:
                            try:
                                # Resumen de las series
                                resumen_series = " | ".join(series_data)
                                num_series = len(series_data)
                                
                                # Guardamos el peso de la primera serie como referencia principal
                                primer_peso = series_data[0].split("kg")[0] if series_data else 0
                
                                sheet = get_sheet_historial()
                                sheet.append_row([
                                    str(date.today()),
                                    ejercicio,
                                    primer_peso,
                                    num_series,
                                    resumen_series,   # Aquí se guardan todas las series detalladas
                                    rpe,
                                    notas
                                ])
                                st.success("✅ Ejercicio guardado correctamente")
                                st.cache_resource.clear()
                            except Exception as e:
                                st.error(f"Error al guardar: {e}")
                            try:
                                sheet = get_sheet_historial()
                                sheet.append_row([
                                    str(date.today()),
                                    ejercicio,
                                    peso,
                                    series,
                                    reps,
                                    rpe,
                                    notas
                                ])
                                st.success("✅ Guardado")
                                st.cache_resource.clear()
                            except Exception as e:
                                st.error(f"Error: {e}")

st.markdown("---")
st.caption("Coach Lean • Programas flexibles de 3 meses • Cambia los ejercicios desde Google Sheets")
