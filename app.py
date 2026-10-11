import re
import time
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

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
    [data-testid="stMetric"] {
        background: rgba(128,128,128,0.08);
        border-radius: 10px;
        padding: 8px 12px;
    }
</style>
""", unsafe_allow_html=True)

# --------------------------
# Hora de Lima (el servidor usa UTC; Lima es UTC-5 todo el año)
# --------------------------
TZ_LIMA = timezone(timedelta(hours=-5))

def ahora_lima():
    return datetime.now(TZ_LIMA)

def hoy_lima():
    return ahora_lima().date()

# --------------------------
# Configuración
# --------------------------
NOMBRE_LIBRO = "CoachLeanHistorial"

HISTORIAL_COLUMNAS = ["Fecha", "Ejercicio", "Peso", "Series", "Reps", "RPE", "Notas"]

MEDIDAS_COLUMNAS = [
    "Fecha", "Peso", "Cuello", "Hombros", "Pecho", "Cintura", "Cadera",
    "Brazo D", "Brazo I", "Muslo", "Pantorrilla", "Notas"
]

CHECKIN_COLUMNAS = ["Fecha", "Energia", "Sueno", "Cuello", "Hombros", "EspaldaBaja", "Notas"]

REST_DAYS = {
    "Pecho": 2, "Espalda": 2, "Hombros": 2, "Bíceps": 1,
    "Tríceps": 3, "Piernas": 3, "Glúteos": 3, "Abs": 1
}
DESCANSO_POR_DEFECTO = 2

TOTAL_SEMANAS = 12
SEMANAS_DESCARGA = {4, 8, 12}
FASES = {
    1: {"nombre": "Base y técnica", "semanas": "1-4", "rpe": "6-7",
        "foco": "Aprender patrones, control postural y core"},
    2: {"nombre": "Hipertrofia", "semanas": "5-8", "rpe": "7-8",
        "foco": "Más volumen y pausas en los ejercicios de postura"},
    3: {"nombre": "Intensificación", "semanas": "9-12", "rpe": "8",
        "foco": "Más carga y core más difícil"},
}
SEMANA_TIPO = [
    ("Lunes", "Día 1 · Upper A (empuje + postura)"),
    ("Martes", "Día 2 · Lower A (cuádriceps + core)"),
    ("Miércoles", "Descanso activo: caminata + movilidad"),
    ("Jueves", "Día 3 · Upper B (tirón + postura)"),
    ("Viernes", "Día 4 · Lower B (glúteo/isquios + core)"),
    ("Sábado", "Opcional: caminata + core ligero"),
    ("Domingo", "Descanso"),
]
NIVELES_DOLOR = ["Nada", "Leve", "Moderado", "Fuerte"]

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

@st.cache_resource
def get_libro():
    return get_client().open(NOMBRE_LIBRO)

@st.cache_resource
def get_sheet(nombre):
    """Devuelve la pestaña pedida; la crea con encabezados si no existe."""
    libro = get_libro()
    if nombre == "Historial":
        return libro.sheet1
    try:
        return libro.worksheet(nombre)
    except gspread.WorksheetNotFound:
        ws = libro.add_worksheet(title=nombre, rows=1000, cols=20)
        if nombre == "Medidas":
            ws.append_row(MEDIDAS_COLUMNAS)
        elif nombre == "Rutinas":
            ws.append_row(["Grupo", "Ejercicio", "Orden", "Activo"])
        elif nombre == "Checkin":
            ws.append_row(CHECKIN_COLUMNAS)
        elif nombre == "Config":
            ws.append_row(["Clave", "Valor"])
            ws.append_row(["fecha_inicio", str(hoy_lima())])
        return ws

def guardar_fila(pestana, fila):
    get_sheet(pestana).append_row(fila)
    obtener_historial.clear()
    obtener_medidas.clear()
    obtener_checkin.clear()

# --------------------------
# Lectura de datos (con caché)
# --------------------------
def _leer_tabla(pestana, columnas):
    try:
        data = get_sheet(pestana).get_all_records()
        if not data:
            return pd.DataFrame(columns=columnas)
        df = pd.DataFrame(data)
        df.columns = df.columns.astype(str).str.strip()
        for col in columnas:
            if col not in df.columns:
                df[col] = None
        return df[columnas]
    except Exception as e:
        st.warning(f"Error leyendo {pestana.lower()}: {e}")
        return pd.DataFrame(columns=columnas)

@st.cache_data(ttl=120, show_spinner=False)
def obtener_historial():
    return _leer_tabla("Historial", HISTORIAL_COLUMNAS)

@st.cache_data(ttl=120, show_spinner=False)
def obtener_medidas():
    return _leer_tabla("Medidas", MEDIDAS_COLUMNAS)

@st.cache_data(ttl=120, show_spinner=False)
def obtener_checkin():
    return _leer_tabla("Checkin", CHECKIN_COLUMNAS)

@st.cache_data(ttl=120, show_spinner=False)
def cargar_programa():
    """Lee 'Rutinas' una sola vez. Devuelve (rutinas por grupo, guía por ejercicio)."""
    try:
        data = get_sheet("Rutinas").get_all_records()
    except Exception as e:
        st.error(f"Error leyendo rutinas: {e}")
        return {}, {}
    if not data:
        return {}, {}
    df = pd.DataFrame(data)
    df.columns = df.columns.astype(str).str.strip()
    if "Activo" in df.columns:
        df = df[df["Activo"].astype(str).str.strip().str.lower().isin(["sí", "si", "s", "yes", "1", "true"])]
    if "Grupo" not in df.columns or "Ejercicio" not in df.columns:
        return {}, {}
    df["_orden_grupo"] = df.groupby("Grupo", sort=False).ngroup()
    if "Orden" in df.columns:
        df["Orden"] = pd.to_numeric(df["Orden"], errors="coerce")
        df = df.sort_values(["_orden_grupo", "Orden"], kind="stable")
    rutinas = defaultdict(list)
    guias = {}
    for _, row in df.iterrows():
        grupo = str(row.get("Grupo", "")).strip()
        ejercicio = str(row.get("Ejercicio", "")).strip()
        if grupo and ejercicio:
            rutinas[grupo].append(ejercicio)
            guias[ejercicio] = {
                str(k).strip(): ("" if pd.isna(v) else str(v).strip())
                for k, v in row.items() if not str(k).startswith("_")
            }
    return dict(rutinas), guias

def parse_fecha(texto):
    s = str(texto).strip().lstrip("'")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

@st.cache_data(ttl=120, show_spinner=False)
def obtener_fecha_inicio():
    try:
        for fila in get_sheet("Config").get_all_values()[1:]:
            if len(fila) >= 2 and fila[0].strip() == "fecha_inicio":
                f = parse_fecha(fila[1])
                if f:
                    return f
    except Exception as e:
        st.warning(f"Error leyendo configuración: {e}")
    return hoy_lima()

def guardar_fecha_inicio(fecha):
    ws = get_sheet("Config")
    valores = ws.get_all_values()
    for i, fila in enumerate(valores, start=1):
        if fila and fila[0].strip() == "fecha_inicio":
            ws.update_cell(i, 2, "'" + str(fecha))
            break
    else:
        ws.append_row(["fecha_inicio", str(fecha)])
    obtener_fecha_inicio.clear()

# --------------------------
# Helpers: texto de series / reps
# --------------------------
def es_tiempo(reps_txt):
    """True si el objetivo está en segundos (ej. '30–45 s', '20 s por lado')."""
    return bool(re.match(r"\s*\d+(\s*[-–]\s*\d+)?\s*s\b", str(reps_txt or "")))

def tope_reps(reps_txt):
    """Número más alto del rango objetivo ('10–12' -> 12, '30–45 s' -> 45)."""
    base = re.split(r"\(|\bx\b", str(reps_txt or ""))[0]
    nums = [int(n) for n in re.findall(r"\d+", base)]
    return max(nums) if nums else None

def parsear_series(texto):
    """'40.0kg x 12 | 40.0kg x 10' -> [(40.0, 12, False), (40.0, 10, False)]"""
    salida = []
    for peso, valor, unidad in re.findall(r"(\d+(?:[.,]\d+)?)\s*kg\s*x\s*(\d+)\s*(s?)", str(texto or "")):
        salida.append((float(peso.replace(",", ".")), int(valor), unidad == "s"))
    return salida

def calidad_postura(notas):
    m = re.search(r"\[Postura\s*(\d)/5\]", str(notas or ""))
    return int(m.group(1)) if m else None

def objetivo_fase(info, fase):
    """(series, reps) objetivo para la fase. Si faltan columnas F2/F3 usa Series/Reps."""
    if not info:
        return None, None
    if fase == 2:
        s, r = info.get("Series_F2"), info.get("Reps_F2")
    elif fase == 3:
        s, r = info.get("Series_F3"), info.get("Reps_F3")
    else:
        s, r = None, None
    s = s or info.get("Series")
    r = r or info.get("Reps")
    return (s or None), (r or None)

def series_con_descarga(series_txt, semana):
    if series_txt and semana in SEMANAS_DESCARGA and str(series_txt).strip().isdigit():
        return str(max(int(series_txt) - 1, 1))
    return series_txt

def calcular_semana(inicio):
    dias = (hoy_lima() - inicio).days
    return 1 if dias < 0 else dias // 7 + 1

def fase_de_semana(semana):
    return min(3, (min(max(semana, 1), TOTAL_SEMANAS) - 1) // 4 + 1)

# --------------------------
# Helpers: historial y sugerencias
# --------------------------
def ultimo_registro(df, ejercicio, antes_de=None):
    if df.empty or "Ejercicio" not in df.columns:
        return None
    c = df[df["Ejercicio"] == ejercicio].copy()
    if c.empty:
        return None
    c["Fecha_dt"] = pd.to_datetime(c["Fecha"], errors="coerce")
    if antes_de is not None:
        c = c[c["Fecha_dt"] < pd.Timestamp(antes_de)]
        if c.empty:
            return None
    c = c.sort_values("Fecha_dt", kind="stable")
    return c.iloc[-1]

def registros_de_hoy(df, ejercicio, hoy):
    if df.empty:
        return df
    t = df[df["Ejercicio"] == ejercicio].copy()
    t["Fecha_d"] = pd.to_datetime(t["Fecha"], errors="coerce").dt.date
    return t[t["Fecha_d"] == hoy]

def sugerencia(ult, reps_obj, semana, cuidado):
    """Devuelve (peso_sugerido o None, motivo). Doble progresión: primero reps, luego peso."""
    try:
        series = parsear_series(ult.get("Reps"))
        peso_ult = pd.to_numeric(pd.Series([ult.get("Peso")]), errors="coerce").iloc[0]
        if series:
            peso_max = max(s[0] for s in series)
        elif not pd.isna(peso_ult):
            peso_max = float(peso_ult)
        else:
            return None, ""
        rpe = pd.to_numeric(pd.Series([ult.get("RPE")]), errors="coerce").iloc[0]
        calidad = calidad_postura(ult.get("Notas"))
        tope = tope_reps(reps_obj)
        unidad = " s" if es_tiempo(reps_obj) else " reps"
        trabajo = [s for s in series if s[0] == peso_max] or series
        completo = bool(tope and trabajo and all(s[1] >= tope for s in trabajo))

        if peso_max == 0:
            if completo:
                return None, f"Llegaste a {tope}{unidad} en todas las series: pasa a una variante más difícil o añade lastre."
            if tope:
                return None, f"Meta: llegar a {tope}{unidad} en todas las series."
            return None, ""

        nuevo = peso_max
        if calidad is not None and calidad <= 2:
            nuevo = max(peso_max - 2.5, 0)
            motivo = "tu postura/técnica quedó floja la última vez: baja y domina el movimiento"
        elif not pd.isna(rpe) and rpe >= 9:
            nuevo = max(peso_max - 2.5, 0)
            motivo = "el esfuerzo fue muy alto (RPE 9-10)"
        elif completo and (pd.isna(rpe) or rpe <= 8):
            nuevo = peso_max + 2.5
            motivo = f"completaste {tope}{unidad} en todas las series con buen control"
        elif tope:
            motivo = f"mantén el peso y busca llegar a {tope}{unidad} en todas las series"
        else:
            motivo = "mantén el peso"

        if semana in SEMANAS_DESCARGA:
            nuevo = round(peso_max * 0.9 * 2) / 2
            motivo = "semana de descarga (-10%)"
        if cuidado:
            nuevo = round(nuevo * 0.8 * 2) / 2
            motivo += " · ajustado -20% por tu check-in de hoy"
        return nuevo, motivo
    except Exception:
        return None, ""

def dias_desde_ultimo(df, ejercicios):
    if df.empty:
        return 999
    temp = df.copy()
    temp["Fecha_dt"] = pd.to_datetime(temp["Fecha"], errors="coerce")
    mask = temp["Ejercicio"].isin(ejercicios)
    if not mask.any():
        return 999
    ultima = temp.loc[mask, "Fecha_dt"].max()
    if pd.isna(ultima):
        return 999
    return (hoy_lima() - ultima.date()).days

def checkin_de_hoy(df, hoy):
    if df.empty:
        return None
    f = pd.to_datetime(df["Fecha"], errors="coerce").dt.date
    fil = df[f == hoy]
    return fil.iloc[-1] if not fil.empty else None

def evaluar_checkin(row):
    """Devuelve (cuidado, lista de avisos)."""
    if row is None:
        return False, []
    def n(col):
        v = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
        return None if pd.isna(v) else float(v)
    avisos, cuidado = [], False
    for col, nombre in (("Cuello", "el cuello"), ("Hombros", "los hombros"), ("EspaldaBaja", "la espalda baja")):
        v = n(col)
        if v is not None and v >= 3:
            avisos.append(f"Dolor fuerte en {nombre}: lo más sensato hoy es movilidad suave o descansar. Si persiste, consulta a un profesional.")
            cuidado = True
        elif v is not None and v >= 2:
            avisos.append(f"Molestia moderada en {nombre}: baja la carga ~20%, prioriza técnica y evita lo que la empeore.")
            cuidado = True
    energia, sueno = n("Energia"), n("Sueno")
    if (energia is not None and energia <= 2) or (sueno is not None and 0 < sueno < 5):
        avisos.append("Poca energía o sueño: baja ~20% la carga y una serie por ejercicio. Mejor técnica limpia que récords hoy.")
        cuidado = True
    return cuidado, avisos

# --------------------------
# Helpers: interfaz
# --------------------------
def mostrar_imagen(url):
    try:
        st.image(url, use_container_width=True)
    except TypeError:
        st.image(url, use_column_width=True)
    except Exception:
        st.caption("⚠️ No se pudo cargar la imagen de este ejercicio.")

def mostrar_guia(info, series_obj, reps_obj, fase, semana):
    if not info:
        return
    if info.get("Imagen"):
        mostrar_imagen(info["Imagen"])
    if info.get("Video"):
        try:
            st.video(info["Video"])
        except Exception:
            st.caption("⚠️ No se pudo cargar el video.")
    if series_obj or reps_obj:
        desc = info.get("Descanso", "")
        extra = f" · descanso {desc}" if desc and desc != "-" else ""
        nota = " · 🔻 descarga" if semana in SEMANAS_DESCARGA else ""
        st.markdown(f"🎯 **Objetivo Fase {fase}:** {series_obj or '-'} series x {reps_obj or '-'}{extra}{nota}")
    if info.get("Tecnica"):
        st.markdown(f"**Técnica:** {info['Tecnica']}")
    if info.get("Respiracion"):
        st.markdown(f"**Respiración:** {info['Respiracion']}")
    if info.get("Errores"):
        st.warning(f"**Errores comunes:** {info['Errores']}")

def banner_programa(semana, fase):
    datos = FASES[fase]
    if semana > TOTAL_SEMANAS:
        st.success("🏁 ¡Completaste las 12 semanas! Haz tus medidas y fotos finales y pide tu nueva rutina.")
        return
    extra = " · 🔻 **Semana de descarga**: una serie menos y ~10% menos de peso" if semana in SEMANAS_DESCARGA else ""
    st.info(f"📅 **Semana {semana} de {TOTAL_SEMANAS}** · Fase {fase}: {datos['nombre']} · RPE {datos['rpe']}{extra}")

# --------------------------
# Estado de sesión
# --------------------------
hoy = hoy_lima()

for clave, valor in [("fecha_sesion", None), ("grupo_elegido", None),
                     ("sesion_iniciada", False), ("checkin_saltado", False)]:
    if clave not in st.session_state:
        st.session_state[clave] = valor

if st.session_state.fecha_sesion != str(hoy):
    st.session_state.sesion_iniciada = False
    st.session_state.grupo_elegido = None
    st.session_state.checkin_saltado = False
    st.session_state.fecha_sesion = str(hoy)

# --------------------------
# Datos
# --------------------------
rutinas, guias = cargar_programa()
df_hist = obtener_historial()
df_m = obtener_medidas()
df_check = obtener_checkin()
fecha_inicio = obtener_fecha_inicio()
semana = calcular_semana(fecha_inicio)
fase = fase_de_semana(semana)
checkin_hoy = checkin_de_hoy(df_check, hoy)
cuidado, avisos_checkin = evaluar_checkin(checkin_hoy)

# --------------------------
# Interfaz
# --------------------------
st.title("💪 Coach Lean")
st.caption("Postura • Abs • Cuerpo lean y musculoso • Programa de 12 semanas")

tab_entrenar, tab_medidas, tab_stats, tab_programa = st.tabs(
    ["🏋️ Entrenar", "📏 Medidas", "📊 Estadísticas", "📋 Programa"]
)

# ==================================================
# TAB: ENTRENAR
# ==================================================
with tab_entrenar:
    # ---------- Pantalla inicial ----------
    if not st.session_state.sesion_iniciada:
        st.markdown("### ¿Qué quieres hacer hoy?")
        banner_programa(semana, fase)

        if df_hist.empty:
            st.info("Aún no tienes registros. ¡Inicia tu primera rutina! 💪")
        else:
            temp = df_hist.copy()
            temp["Fecha_dt"] = pd.to_datetime(temp["Fecha"], errors="coerce").dt.date
            dias_entrenados = sorted(set(temp["Fecha_dt"].dropna()))
            recientes = [d for d in dias_entrenados if (hoy - d).days <= 30]
            c1, c2 = st.columns(2)
            c1.metric("Días entrenados (30 días)", len(recientes))
            if dias_entrenados:
                c2.metric("Último entrenamiento", max(dias_entrenados).strftime("%d %b"))

        # Recordatorio de medidas y fotos cada 4 semanas
        ultima_medida = None
        if not df_m.empty:
            f_m = pd.to_datetime(df_m["Fecha"], errors="coerce").dropna()
            if not f_m.empty:
                ultima_medida = f_m.max().date()
        if ultima_medida is None or (hoy - ultima_medida).days >= 28:
            st.info("📸 Toca actualizar medidas y fotos (frente, perfil y espalda): hazlo en la pestaña Medidas.")

        st.write("")
        if st.button("🏋️ Iniciar rutina de hoy"):
            st.session_state.sesion_iniciada = True
            st.rerun()

    # ---------- Check-in ----------
    elif checkin_hoy is None and not st.session_state.checkin_saltado:
        st.subheader("¿Cómo llegas hoy?")
        st.caption("30 segundos: así ajusto la carga a tu estado real.")
        with st.form("form_checkin"):
            energia = st.slider("Energía (1 = agotado, 5 = excelente)", 1, 5, 3)
            sueno = st.number_input("Horas de sueño anoche", min_value=0.0, max_value=14.0, value=7.0, step=0.5)
            st.markdown("**Molestias o dolor hoy**")
            d_cuello = st.select_slider("Cuello", options=NIVELES_DOLOR, value="Nada")
            d_hombros = st.select_slider("Hombros", options=NIVELES_DOLOR, value="Nada")
            d_espalda = st.select_slider("Espalda baja", options=NIVELES_DOLOR, value="Nada")
            notas_ck = st.text_area("Notas (opcional)")
            if st.form_submit_button("✅ Guardar y continuar"):
                try:
                    guardar_fila("Checkin", [
                        str(hoy), energia, sueno,
                        NIVELES_DOLOR.index(d_cuello),
                        NIVELES_DOLOR.index(d_hombros),
                        NIVELES_DOLOR.index(d_espalda),
                        notas_ck
                    ])
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar el check-in: {e}")
        if st.button("Saltar check-in"):
            st.session_state.checkin_saltado = True
            st.rerun()
        if st.button("⬅️ Volver al inicio"):
            st.session_state.sesion_iniciada = False
            st.rerun()

    # ---------- Elegir sesión ----------
    elif st.session_state.grupo_elegido is None:
        st.subheader("Elige la sesión de hoy")
        banner_programa(semana, fase)
        for aviso in avisos_checkin:
            st.warning(aviso)
        if not rutinas:
            st.warning("No hay rutinas activas. Revisa la pestaña 'Rutinas' de tu Google Sheet.")
        st.caption("Ordenadas por prioridad de recuperación")

        prioridad = []
        for grupo in rutinas.keys():
            descanso = REST_DAYS.get(grupo, DESCANSO_POR_DEFECTO)
            dias = dias_desde_ultimo(df_hist, rutinas[grupo])
            prioridad.append({"grupo": grupo, "dias": dias,
                              "listo": dias >= descanso, "descanso": descanso})
        prioridad = sorted(prioridad, key=lambda x: (-x["listo"], -x["dias"]))

        for idx, item in enumerate(prioridad):
            if item["dias"] == 999:
                estado = "🟢 Nueva"
            elif item["listo"]:
                estado = "🟢 Lista"
            else:
                estado = f"🟠 {item['dias']}d (mín {item['descanso']})"
            marca = "⭐ " if idx == 0 else ""
            if st.button(f"{marca}{item['grupo']}  —  {estado}", key=f"grp_{item['grupo']}"):
                st.session_state.grupo_elegido = item["grupo"]
                st.session_state.hora_inicio = ahora_lima().strftime("%H:%M")
                st.rerun()

        if st.button("⬅️ Volver al inicio"):
            st.session_state.sesion_iniciada = False
            st.rerun()

    # ---------- Sesión en curso ----------
    else:
        grupo = st.session_state.grupo_elegido
        st.success(f"Sesión **{grupo}** iniciada a las {st.session_state.get('hora_inicio', '')}")
        if semana in SEMANAS_DESCARGA and semana <= TOTAL_SEMANAS:
            st.info("🔻 Semana de descarga: una serie menos y ~10% menos de peso. Prioriza técnica.")
        for aviso in avisos_checkin:
            st.warning(aviso)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Cambiar de sesión"):
                st.session_state.grupo_elegido = None
                st.rerun()
        with c2:
            if st.button("🏁 Terminar sesión"):
                ej_grupo = rutinas.get(grupo, [])
                temp = df_hist.copy()
                temp["Fecha_dt"] = pd.to_datetime(temp["Fecha"], errors="coerce").dt.date
                hoy_rows = temp[(temp["Fecha_dt"] == hoy) & (temp["Ejercicio"].isin(ej_grupo))]
                n_ej = hoy_rows["Ejercicio"].nunique()
                n_series = pd.to_numeric(hoy_rows["Series"], errors="coerce").sum()
                hechos = set(hoy_rows["Ejercicio"])
                bloques = {guias.get(e, {}).get("Bloque", "") for e in hechos}
                st.balloons()
                st.success(f"¡Sesión completada! {n_ej} ejercicios y {int(n_series)} series 💪")
                if "Core" in bloques and "Postura" in bloques:
                    st.success("🧍 Hoy cumpliste postura y core. Eso se nota con el tiempo.")
                elif "Core" not in bloques or "Postura" not in bloques:
                    st.info("Recuerda: postura y core son tu prioridad; la próxima sesión no los saltes.")
                st.session_state.sesion_iniciada = False
                st.session_state.grupo_elegido = None
                time.sleep(2)
                st.rerun()

        with st.expander("⏱️ Temporizador de descanso"):
            descanso_t = st.number_input("Segundos de descanso", min_value=15, max_value=600, value=90, step=15)
            if st.button("▶️ Iniciar"):
                placeholder = st.empty()
                barra = st.progress(0)
                fin = time.time() + descanso_t
                while time.time() < fin:
                    restante = max(0, int(fin - time.time()))
                    placeholder.metric("Tiempo restante", f"{restante // 60:02d}:{restante % 60:02d}")
                    barra.progress(min(1.0, 1 - restante / descanso_t))
                    time.sleep(1)
                placeholder.success("💪 ¡Descanso terminado, a darle!")
                barra.progress(1.0)

        st.divider()
        st.subheader(f"Ejercicios · {grupo}")

        ejercicios = rutinas.get(grupo, [])
        if not ejercicios:
            st.warning("No hay ejercicios activos para esta sesión. Agrégalos en la pestaña 'Rutinas' de tu Google Sheet.")

        bloque_anterior = None
        for ejercicio in ejercicios:
            info = guias.get(ejercicio, {})
            bloque = info.get("Bloque", "")
            if bloque and bloque != bloque_anterior:
                st.markdown(f"##### {bloque}")
                bloque_anterior = bloque

            series_obj, reps_obj = objetivo_fase(info, fase)
            series_obj = series_con_descarga(series_obj, semana)
            tiempo = es_tiempo(reps_obj)
            hechos_hoy = registros_de_hoy(df_hist, ejercicio, hoy)

            if bloque == "Movilidad":
                with st.expander(f"🧘 {ejercicio}", expanded=False):
                    mostrar_guia(info, series_obj, reps_obj, fase, semana)
                    st.caption("Movilidad: no necesitas registrarla, solo hazla antes de empezar.")
                continue

            icono = "✅" if not hechos_hoy.empty else "📌"
            with st.expander(f"{icono} {ejercicio}", expanded=False):
                mostrar_guia(info, series_obj, reps_obj, fase, semana)

                ult = ultimo_registro(df_hist, ejercicio, antes_de=hoy)
                peso_sug = None
                if ult is not None:
                    st.markdown("**Última vez**")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Peso", f"{ult.get('Peso', '-')} kg")
                    c2.metric("Series", f"{ult.get('Series', '-')}")
                    c3.metric("RPE", f"{ult.get('RPE', '-')}")
                    detalle = ult.get("Reps", "")
                    if detalle and str(detalle).strip():
                        st.info(f"**Series:** {detalle}")
                    fecha_ult = pd.to_datetime(ult.get("Fecha"), errors="coerce")
                    fecha_txt = fecha_ult.strftime("%d %b %Y") if not pd.isna(fecha_ult) else str(ult.get("Fecha", ""))
                    st.caption(f"Fecha: {fecha_txt}")
                    peso_sug, motivo = sugerencia(ult, reps_obj, semana, cuidado)
                    if peso_sug is not None:
                        st.markdown(f"💡 **Sugerencia hoy: {peso_sug:g} kg** — {motivo}")
                    elif motivo:
                        st.markdown(f"💡 {motivo}")
                else:
                    st.caption("Primera vez con este ejercicio. ¡Establece tu base con técnica limpia! 🎯")

                if not hechos_hoy.empty:
                    st.success("Ya registraste hoy: " + " · ".join(
                        f"{r['Reps']} (RPE {r['RPE']})" for _, r in hechos_hoy.iterrows()))

                clave_cnt = f"cnt_{grupo}_{ejercicio}"
                if clave_cnt not in st.session_state:
                    st.session_state[clave_cnt] = 0
                base = f"{grupo}_{ejercicio}_{st.session_state[clave_cnt]}"

                with st.form(key=f"form_{base}"):
                    st.markdown("**Registra cada serie:**")
                    h1, h2, h3 = st.columns([1, 2, 2])
                    h1.markdown("**Serie**")
                    h2.markdown("**Lastre (kg)**" if tiempo else "**Peso (kg)**")
                    h3.markdown("**Segundos**" if tiempo else "**Reps**")

                    series_data = []
                    for i in range(1, 6):
                        c1, c2, c3 = st.columns([1, 2, 2])
                        c1.markdown(f"**{i}**")
                        peso = c2.number_input(
                            f"Peso {ejercicio} {i}", min_value=0.0, step=0.5,
                            value=float(peso_sug) if peso_sug else 0.0,
                            label_visibility="collapsed", key=f"peso_{base}_{i}"
                        )
                        valor = c3.number_input(
                            f"{'Seg' if tiempo else 'Reps'} {ejercicio} {i}", min_value=0, step=1,
                            label_visibility="collapsed", key=f"reps_{base}_{i}"
                        )
                        if valor > 0:
                            series_data.append((peso, int(valor)))

                    rpe = st.slider("RPE (esfuerzo percibido)", 1, 10, 7, key=f"rpe_{base}")
                    calidad = st.slider("Calidad de postura / técnica (1 = floja, 5 = perfecta)", 1, 5, 4, key=f"cal_{base}")
                    notas = st.text_area("Notas (opcional)", key=f"nota_{base}")

                    if st.form_submit_button("💾 Guardar ejercicio"):
                        if not series_data:
                            st.warning("Registra al menos una serie")
                        else:
                            try:
                                unidad = "s" if tiempo else ""
                                texto_series = [f"{p:g}kg x {v}{unidad}" for p, v in series_data]
                                peso_top = max(p for p, _ in series_data)
                                guardar_fila("Historial", [
                                    str(hoy),
                                    ejercicio,
                                    peso_top,
                                    len(series_data),
                                    " | ".join(texto_series),
                                    rpe,
                                    f"[Postura {calidad}/5] {notas}".strip()
                                ])
                                st.session_state[clave_cnt] += 1
                                st.toast("✅ Guardado")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al guardar: {e}")

# ==================================================
# TAB: MEDIDAS
# ==================================================
with tab_medidas:
    st.subheader("📏 Seguimiento de medidas corporales")
    st.caption("Registra solo lo que midas; los cambios se grafican automáticamente. Cada 4 semanas, toma también fotos de frente, perfil y espalda con la misma luz.")

    with st.form("form_medidas"):
        campos = [c for c in MEDIDAS_COLUMNAS if c not in ("Fecha", "Notas")]
        valores = {}
        cols = st.columns(3)
        for i, campo in enumerate(campos):
            with cols[i % 3]:
                valores[campo] = st.number_input(
                    campo, min_value=0.0, step=0.5, format="%.1f",
                    key=f"med_{campo}"
                )
        notas_med = st.text_area("Notas (ayuno, hora del día, etc.)", key="notas_medidas")
        if st.form_submit_button("💾 Guardar medidas de hoy"):
            fila = [str(hoy)] + ["" if valores[c] == 0 else valores[c] for c in campos] + [notas_med]
            if all(v == "" for v in fila[1:-1]):
                st.warning("Registra al menos una medida")
            else:
                guardar_fila("Medidas", fila)
                st.toast("✅ Medidas guardadas")
                st.rerun()

    if not df_m.empty:
        st.divider()
        opciones = [c for c in MEDIDAS_COLUMNAS if c not in ("Fecha", "Notas")]
        medida_sel = st.selectbox("¿Qué medida quieres ver?", opciones)
        unidad_m = "kg" if medida_sel == "Peso" else "cm"

        d = df_m.copy()
        d["Fecha_dt"] = pd.to_datetime(d["Fecha"], errors="coerce")
        d[medida_sel] = pd.to_numeric(d[medida_sel], errors="coerce")
        d.loc[d[medida_sel] == 0, medida_sel] = pd.NA
        d = d.dropna(subset=["Fecha_dt"]).sort_values("Fecha_dt")
        reg = d.dropna(subset=[medida_sel])

        if not reg.empty:
            ultimo = reg[medida_sel].iloc[-1]
            if len(reg) >= 2:
                previo = reg[medida_sel].iloc[-2]
                st.metric(f"{medida_sel} (actual)", f"{ultimo:.1f} {unidad_m}",
                          delta=f"{ultimo - previo:+.1f} {unidad_m} vs registro anterior")
            else:
                st.metric(f"{medida_sel} (actual)", f"{ultimo:.1f} {unidad_m}")
            st.line_chart(reg.set_index("Fecha_dt")[[medida_sel]])
            c1, c2 = st.columns(2)
            c1.metric("Primera medición", f"{reg[medida_sel].iloc[0]:.1f} {unidad_m}")
            c2.metric("Cambio total", f"{ultimo - reg[medida_sel].iloc[0]:+.1f} {unidad_m}")
        st.divider()
        st.markdown("**Historial completo**")
        st.dataframe(df_m.iloc[::-1], use_container_width=True, hide_index=True)
    else:
        st.info("Todavía no hay medidas registradas.")

# ==================================================
# TAB: ESTADÍSTICAS
# ==================================================
with tab_stats:
    st.subheader("📊 Tu progreso")

    if df_hist.empty:
        st.info("Aún no hay registros de entrenamiento.")
    else:
        temp = df_hist.copy()
        temp["Fecha_dt"] = pd.to_datetime(temp["Fecha"], errors="coerce")
        temp["Peso_num"] = pd.to_numeric(temp["Peso"], errors="coerce")
        temp = temp.dropna(subset=["Fecha_dt"])
        temp["Dia"] = temp["Fecha_dt"].dt.date
        temp["Bloque"] = temp["Ejercicio"].map(lambda e: guias.get(e, {}).get("Bloque", ""))

        dias = sorted(set(temp["Dia"]))
        recientes = [x for x in dias if (hoy - x).days <= 30]
        c1, c2, c3 = st.columns(3)
        c1.metric("Sesiones (30 días)", len(recientes))
        c2.metric("Ejercicios distintos", temp["Ejercicio"].nunique())
        c3.metric("Registros totales", len(temp))

        # Meta semanal: postura y core 3-4 veces
        lunes = hoy - timedelta(days=hoy.weekday())
        sem_df = temp[temp["Dia"] >= lunes]
        st.markdown("**Esta semana** (meta: postura y core 3-4 veces)")
        w1, w2, w3 = st.columns(3)
        w1.metric("Sesiones de fuerza", sem_df["Dia"].nunique())
        w2.metric("Días con postura", sem_df[sem_df["Bloque"] == "Postura"]["Dia"].nunique())
        w3.metric("Días con core", sem_df[sem_df["Bloque"] == "Core"]["Dia"].nunique())

        st.divider()
        st.markdown("**Sesiones por semana**")
        temp["Semana"] = temp["Fecha_dt"] - pd.to_timedelta(temp["Fecha_dt"].dt.weekday, unit="D")
        temp["Semana"] = temp["Semana"].dt.normalize()
        por_semana = temp.groupby("Semana")["Dia"].nunique().rename("Sesiones")
        st.bar_chart(por_semana)

        st.divider()
        ejercicios_registrados = sorted(temp["Ejercicio"].dropna().unique())
        ej_sel = st.selectbox("Progreso por ejercicio", ejercicios_registrados)
        sub = temp[temp["Ejercicio"] == ej_sel].sort_values("Fecha_dt")
        sub_p = sub.dropna(subset=["Peso_num"])
        if not sub_p.empty and sub_p["Peso_num"].max() > 0:
            st.line_chart(sub_p.set_index("Fecha_dt")[["Peso_num"]].rename(columns={"Peso_num": "Peso (kg)"}))
            st.metric("🏆 Peso máximo registrado", f"{sub_p['Peso_num'].max():g} kg")
        st.dataframe(
            sub[["Fecha", "Peso", "Series", "Reps", "RPE", "Notas"]].iloc[::-1],
            use_container_width=True, hide_index=True
        )

        st.divider()
        st.markdown("**🏆 Marcas personales (peso máximo)**")
        prs = (temp.dropna(subset=["Peso_num"])
                   .query("Peso_num > 0")
                   .groupby("Ejercicio")["Peso_num"].max()
                   .sort_values(ascending=False))
        st.dataframe(prs.rename("Peso máx (kg)"), use_container_width=True)

    if not df_check.empty:
        st.divider()
        with st.expander("🩺 Check-ins recientes"):
            st.caption("Dolor: 0 = nada, 1 = leve, 2 = moderado, 3 = fuerte")
            st.dataframe(df_check.iloc[::-1].head(14), use_container_width=True, hide_index=True)

# ==================================================
# TAB: PROGRAMA
# ==================================================
with tab_programa:
    st.subheader("📋 Mi programa (12 semanas)")
    banner_programa(semana, fase)
    st.progress(min(semana, TOTAL_SEMANAS) / TOTAL_SEMANAS)

    datos_fase = pd.DataFrame([
        {"Fase": f, "Semanas": d["semanas"], "Nombre": d["nombre"], "RPE": d["rpe"], "Foco": d["foco"]}
        for f, d in FASES.items()
    ])
    st.dataframe(datos_fase, use_container_width=True, hide_index=True)
    st.caption("Semanas 4, 8 y 12 son de descarga: una serie menos y ~10% menos de peso.")

    if not rutinas:
        st.warning("No se encontraron rutinas activas. Revisa la pestaña 'Rutinas' en Google Sheets.")
    else:
        hay_f2 = any("Series_F2" in i for i in guias.values())
        if fase >= 2 and not hay_f2:
            st.warning("Faltan las columnas Series_F2, Reps_F2, Series_F3 y Reps_F3 en la pestaña 'Rutinas'. Mientras tanto uso los valores de la Fase 1.")
        for grupo, ejercicios in rutinas.items():
            with st.expander(f"**{grupo}** ({len(ejercicios)} ejercicios)"):
                for i, ej in enumerate(ejercicios, 1):
                    info = guias.get(ej, {})
                    s, r = objetivo_fase(info, fase)
                    s = series_con_descarga(s, semana)
                    objetivo = f" — {s} x {r}" if (s or r) else ""
                    bloque = f" · {info['Bloque']}" if info.get("Bloque") else ""
                    st.write(f"{i}. {ej}{objetivo}{bloque}")

    st.divider()
    st.markdown("**Semana tipo**")
    st.dataframe(pd.DataFrame(SEMANA_TIPO, columns=["Día", "Sesión"]), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("**Fecha de inicio del programa**")
    st.caption("La semana y la fase se calculan desde esta fecha. Cámbiala cuando empieces una rutina nueva.")
    nueva_fecha = st.date_input("Inicio", value=fecha_inicio, key="fecha_inicio_input")
    if st.button("💾 Guardar fecha de inicio"):
        try:
            guardar_fecha_inicio(nueva_fecha)
            st.toast("✅ Fecha guardada")
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

    st.caption("Para cambiar ejercicios, edita la pestaña 'Rutinas' de tu Google Sheet.")

st.markdown("---")
st.caption("Coach Lean • Programa de 12 semanas • Cambia los ejercicios desde Google Sheets")
