import hashlib
import hmac
import re
import secrets as _secrets
import threading
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
# Recuperación por músculo
# --------------------------
# Horas que necesita cada músculo antes de volver a trabajarlo con carga.
# Puedes cambiar estos números si tu cuerpo necesita más o menos descanso.
RECUPERACION_H = {
    "Pecho": 60, "Espalda": 60, "Hombros": 48, "Bíceps": 48, "Tríceps": 48,
    "Cuádriceps": 72, "Isquios": 72, "Glúteos": 60, "Espalda baja": 72,
    "Gemelos": 36, "Core": 24, "Postura": 24,
}
# Postura y core se trabajan casi a diario (poco daño muscular): no bloquean una sesión.
NO_LIMITAN = {"Core", "Postura"}
UMBRAL_LISTO = 0.8   # >= 80% recuperado: listo
UMBRAL_CASI = 0.5    # entre 50% y 80%: casi listo; menos: descansando

# Músculos principales de cada ejercicio de tu rutina. Si agregas ejercicios nuevos,
# la app los deduce por el nombre, o puedes poner una columna 'Musculos' en la pestaña Rutinas.
MUSCULOS_EJERCICIO = {
    "Press de pecho en máquina": "Pecho, Tríceps",
    "Jalón al pecho agarre neutro": "Espalda, Bíceps",
    "Press de hombros en máquina": "Hombros, Tríceps",
    "Face pull en polea": "Postura",
    "Pájaros en máquina (deltoides posterior)": "Postura",
    "Plancha frontal": "Core",
    "Pallof press en polea": "Core",
    "Prensa de piernas": "Cuádriceps, Glúteos",
    "Sentadilla en máquina (Hack squat o Smith)": "Cuádriceps, Glúteos",
    "Hip thrust en máquina (o puente de glúteo en Smith)": "Glúteos",
    "Extensión de cuádriceps en máquina": "Cuádriceps",
    "Bird dog": "Postura",
    "Dead bug": "Core",
    "Crunch inverso": "Core",
    "Remo sentado en máquina con soporte de pecho": "Espalda, Bíceps",
    "Dominadas asistidas en máquina": "Espalda, Bíceps",
    "Press inclinado en máquina": "Pecho, Hombros",
    "Elevaciones laterales en máquina": "Hombros",
    "Curl de bíceps en máquina": "Bíceps",
    "Extensión de tríceps en polea": "Tríceps",
    "Elevaciones Y en banco inclinado": "Postura",
    "Plancha lateral": "Core",
    "Crunch en polea de rodillas": "Core",
    "Curl femoral acostado": "Isquios",
    "Hiperextensión en banco 45°": "Espalda baja, Glúteos",
    "Abducción de cadera en máquina": "Glúteos",
    "Patada de glúteo en polea": "Glúteos",
    "Elevación de gemelos en máquina": "Gemelos",
    "Remo en polea baja sentado": "Postura",
    "Elevación de piernas colgado (silla romana)": "Core",
    "Plancha RKC": "Core",
}
# Palabras clave para deducir músculos de ejercicios nuevos (se revisa en orden).
INFERENCIA_MUSCULOS = [
    ("tríceps", "Tríceps"), ("bíceps", "Bíceps"),
    ("press de hombro", "Hombros, Tríceps"), ("lateral", "Hombros"),
    ("press", "Pecho, Tríceps"), ("pecho", "Pecho, Tríceps"),
    ("jalón", "Espalda, Bíceps"), ("dominada", "Espalda, Bíceps"), ("remo", "Espalda, Bíceps"),
    ("hiperextensión", "Espalda baja, Glúteos"),
    ("prensa", "Cuádriceps, Glúteos"), ("sentadilla", "Cuádriceps, Glúteos"),
    ("zancada", "Cuádriceps, Glúteos"), ("cuádriceps", "Cuádriceps"),
    ("hip thrust", "Glúteos"), ("glúteo", "Glúteos"), ("abducción", "Glúteos"), ("patada", "Glúteos"),
    ("femoral", "Isquios"), ("isquio", "Isquios"), ("peso muerto", "Isquios, Glúteos"),
    ("gemelo", "Gemelos"), ("pantorrilla", "Gemelos"),
    ("plancha", "Core"), ("crunch", "Core"), ("abdominal", "Core"), ("dead bug", "Core"),
    ("pallof", "Core"), ("elevación de piernas", "Core"),
    ("face pull", "Postura"), ("pájaro", "Postura"), ("bird dog", "Postura"),
]

CHECKS_COLUMNAS = ["Fecha", "Ejercicio", "Bloque", "Lugar", "Notas"]
BLOQUES_CHECK = ("Movilidad", "Postura", "Core")
EQUIPO_GIMNASIO = ("polea", "máquina", "maquina", "silla romana", "banco", "smith", "prensa", "pallof")
DIAS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

USUARIOS_COLUMNAS = ["Usuario", "Nombre", "Hash", "Rol", "Libro", "Activo", "Debe_cambiar", "Creado"]
VALORES_SI = ("sí", "si", "s", "yes", "1", "true")
MAX_FALLOS = 5
BLOQUEO_SEG = 300
ITERACIONES_HASH = 200_000

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

def libro_activo():
    """Libro de datos del usuario que se está viendo (se guarda por sesión, nunca global)."""
    return st.session_state.get("libro_activo", NOMBRE_LIBRO)

@st.cache_resource
def _get_libro(nombre):
    """Abre el libro; si es un cliente nuevo lo crea y lo comparte con el coach."""
    gc = get_client()
    try:
        return gc.open(nombre)
    except gspread.SpreadsheetNotFound:
        if nombre == NOMBRE_LIBRO:
            raise
        sh = gc.create(nombre)
        ws = sh.sheet1
        ws.update_title("Historial")
        ws.append_row(HISTORIAL_COLUMNAS)
        try:
            correo = st.secrets["app_auth"].get("admin_email", "")
            if correo:
                sh.share(correo, perm_type="user", role="writer", notify=False)
        except Exception:
            pass
        return sh

@st.cache_resource
def _get_sheet(libro_nombre, nombre):
    """Devuelve la pestaña pedida; la crea con encabezados si no existe."""
    libro = _get_libro(libro_nombre)
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
        elif nombre == "Checks":
            ws.append_row(CHECKS_COLUMNAS)
        elif nombre == "Usuarios":
            ws.append_row(USUARIOS_COLUMNAS)
        elif nombre == "Config":
            ws.append_row(["Clave", "Valor"])
            ws.append_row(["fecha_inicio", str(hoy_lima())])
            ws.append_row(["modo_avance", "sesiones"])
        return ws

def get_sheet(pestana):
    return _get_sheet(libro_activo(), pestana)

def _limpiar_caches():
    obtener_historial.clear()
    obtener_medidas.clear()
    obtener_checkin.clear()
    obtener_checks.clear()

def guardar_fila(pestana, fila):
    get_sheet(pestana).append_row(fila)
    _limpiar_caches()

def guardar_filas(pestana, filas):
    get_sheet(pestana).append_rows(filas)
    _limpiar_caches()

# --------------------------
# Lectura de datos (con caché)
# --------------------------
def _leer_tabla(libro, pestana, columnas):
    try:
        data = _get_sheet(libro, pestana).get_all_records()
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
def obtener_historial(libro):
    return _leer_tabla(libro, "Historial", HISTORIAL_COLUMNAS)

@st.cache_data(ttl=120, show_spinner=False)
def obtener_medidas(libro):
    return _leer_tabla(libro, "Medidas", MEDIDAS_COLUMNAS)

@st.cache_data(ttl=120, show_spinner=False)
def obtener_checkin(libro):
    return _leer_tabla(libro, "Checkin", CHECKIN_COLUMNAS)

@st.cache_data(ttl=120, show_spinner=False)
def obtener_checks(libro):
    return _leer_tabla(libro, "Checks", CHECKS_COLUMNAS)

@st.cache_data(ttl=120, show_spinner=False)
def cargar_programa(libro):
    """Lee 'Rutinas' una sola vez. Devuelve (rutinas por grupo, guía por ejercicio)."""
    try:
        data = _get_sheet(libro, "Rutinas").get_all_records()
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
def obtener_config(libro):
    cfg = {}
    try:
        for fila in _get_sheet(libro, "Config").get_all_values()[1:]:
            if len(fila) >= 2 and fila[0].strip():
                cfg[fila[0].strip()] = fila[1].strip()
    except Exception as e:
        st.warning(f"Error leyendo configuración: {e}")
    return cfg

def guardar_config(clave, valor):
    ws = get_sheet("Config")
    for i, fila in enumerate(ws.get_all_values(), start=1):
        if fila and fila[0].strip() == clave:
            ws.update_cell(i, 2, "'" + str(valor))
            break
    else:
        ws.append_row([clave, str(valor)])
    obtener_config.clear()

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

def contar_sesiones_previas(df, inicio, hoy):
    """Días distintos de entrenamiento desde la fecha de inicio, sin contar hoy."""
    if df.empty:
        return 0
    fechas = pd.to_datetime(df["Fecha"], errors="coerce").dt.date.dropna()
    return len({d for d in fechas if inicio <= d < hoy})

def calcular_semana(inicio, modo, sesiones_previas):
    """Por sesiones: cada 4 sesiones = 1 semana del programa. Por calendario: 7 días."""
    if modo == "calendario":
        dias = (hoy_lima() - inicio).days
        return 1 if dias < 0 else dias // 7 + 1
    return sesiones_previas // 4 + 1

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

def sugerencia(ult, reps_obj, semana, cuidado, dias_pausa=0):
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

        if dias_pausa >= 14:
            nuevo = min(nuevo, round(peso_max * 0.9 * 2) / 2)
            motivo = f"vuelves tras {dias_pausa} días sin este ejercicio: retoma ~10% más liviano"
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

def musculos_de(ejercicio, info):
    """Lista de músculos principales: columna 'Musculos' > tabla del programa > deducción por nombre."""
    info = info or {}
    col = info.get("Musculos", "")
    if col:
        return [m.strip() for m in col.split(",") if m.strip()]
    if ejercicio in MUSCULOS_EJERCICIO:
        return [m.strip() for m in MUSCULOS_EJERCICIO[ejercicio].split(",")]
    if info.get("Bloque") == "Movilidad":
        return []
    nombre = ejercicio.lower()
    for clave, musculos in INFERENCIA_MUSCULOS:
        if clave in nombre:
            return [m.strip() for m in musculos.split(",")]
    if info.get("Bloque") in ("Core", "Postura"):
        return [info["Bloque"]]
    return []

def ultimo_por_musculo(df, guias):
    """Última fecha en que se trabajó cada músculo según el historial."""
    ultimos = {}
    if df.empty:
        return ultimos
    t = df.copy()
    t["Dia"] = pd.to_datetime(t["Fecha"], errors="coerce").dt.date
    t = t.dropna(subset=["Dia"])
    for ej, grupo in t.groupby("Ejercicio"):
        dia = grupo["Dia"].max()
        for m in musculos_de(str(ej), guias.get(str(ej), {})):
            if m not in ultimos or dia > ultimos[m]:
                ultimos[m] = dia
    return ultimos

def estado_recuperacion(ultimos, hoy):
    """{músculo: (última fecha, días, fracción recuperada 0-1)}"""
    rec = {}
    for m, horas in RECUPERACION_H.items():
        d = ultimos.get(m)
        if d is None:
            rec[m] = (None, None, 1.0)
        else:
            dias = (hoy - d).days
            rec[m] = (d, dias, min(1.0, dias * 24 / horas))
    return rec

def preparacion_sesion(ejercicios, guias, rec):
    """(mínimo recuperado, promedio, músculos pendientes) de los músculos que limitan la sesión."""
    musculos = set()
    for ej in ejercicios:
        info = guias.get(ej, {})
        if info.get("Bloque") == "Movilidad":
            continue
        musculos.update(musculos_de(ej, info))
    musculos = {m for m in musculos if m in rec and m not in NO_LIMITAN}
    if not musculos:
        return 1.0, 1.0, []
    pcts = {m: rec[m][2] for m in musculos}
    pendientes = sorted([(m, p) for m, p in pcts.items() if p < UMBRAL_LISTO], key=lambda x: x[1])
    return min(pcts.values()), sum(pcts.values()) / len(pcts), pendientes

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

def se_puede_en_casa(ejercicio, info):
    """Columna 'Casa' (sí/no) si existe; si no, deduce por el nombre (polea, máquina, banco...)."""
    v = str((info or {}).get("Casa", "")).strip().lower()
    if v in VALORES_SI:
        return True
    if v in ("no", "n", "0", "false"):
        return False
    nombre = ejercicio.lower()
    return not any(palabra in nombre for palabra in EQUIPO_GIMNASIO)

def ejercicios_de_hoy(df, hoy):
    if df is None or df.empty:
        return set()
    f = pd.to_datetime(df["Fecha"], errors="coerce").dt.date
    return set(df.loc[f == hoy, "Ejercicio"].astype(str))

def dias_con_registros(df):
    if df is None or df.empty:
        return set()
    return set(pd.to_datetime(df["Fecha"], errors="coerce").dt.date.dropna())

def dias_por_bloque(df_hist, df_checks, guias, desde):
    """{bloque: {días}} combinando entrenos del gym y checks (casa o gym)."""
    res = defaultdict(set)
    for df, usa_bloque in ((df_hist, False), (df_checks, True)):
        if df is None or df.empty:
            continue
        bloques = df["Bloque"] if usa_bloque else [None] * len(df)
        for fecha, ej, bl in zip(df["Fecha"], df["Ejercicio"], bloques):
            dia = pd.to_datetime(fecha, errors="coerce")
            if pd.isna(dia) or dia.date() < desde:
                continue
            bloque = (bl.strip() if isinstance(bl, str) else "") or guias.get(str(ej), {}).get("Bloque", "")
            if bloque:
                res[bloque].add(dia.date())
    return res

def racha_dias(dias, hoy):
    d = hoy if hoy in dias else hoy - timedelta(days=1)
    n = 0
    while d in dias:
        n += 1
        d -= timedelta(days=1)
    return n

# --------------------------
# Helpers: interfaz
# --------------------------
def mostrar_imagen(url):
    for kw in ({"width": "stretch"}, {"use_container_width": True}, {"use_column_width": True}):
        try:
            st.image(url, **kw)
            return
        except TypeError:
            continue
        except Exception:
            st.caption("⚠️ No se pudo cargar la imagen de este ejercicio.")
            return

def mostrar_tabla(df, hide_index=True, **kw):
    """Tabla a todo el ancho, compatible con versiones nuevas y antiguas de Streamlit."""
    try:
        st.dataframe(df, width="stretch", hide_index=hide_index, **kw)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=hide_index, **kw)

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

def panel_recuperacion(rec):
    filas = []
    for m, (d, dias, pct) in rec.items():
        if pct >= UMBRAL_LISTO:
            estado = "🟢 Listo"
        elif pct >= UMBRAL_CASI:
            estado = "🟠 Casi"
        else:
            estado = "🔴 Descansando"
        filas.append({
            "Músculo": m,
            "Último entreno": d.strftime("%d %b") if d else "—",
            "Días": "—" if dias is None else str(dias),
            "Recuperación": int(round(pct * 100)),
            "Estado": estado,
        })
    df_rec = pd.DataFrame(filas)
    try:
        mostrar_tabla(df_rec, column_config={"Recuperación": st.column_config.ProgressColumn(
            "Recuperación", min_value=0, max_value=100, format="%d%%")})
    except Exception:
        mostrar_tabla(df_rec)
    st.caption("Postura y core se pueden trabajar casi a diario, por eso no bloquean una sesión.")

def banner_programa(semana, fase, detalle=""):
    datos = FASES[fase]
    if semana > TOTAL_SEMANAS:
        st.success("🏁 ¡Completaste las 12 semanas! Haz tus medidas y fotos finales y pide tu nueva rutina.")
        return
    extra = " · 🔻 **Semana de descarga**: una serie menos y ~10% menos de peso" if semana in SEMANAS_DESCARGA else ""
    det = f" · {detalle}" if detalle else ""
    st.info(f"📅 **Semana {semana} de {TOTAL_SEMANAS}** · Fase {fase}: {datos['nombre']} · RPE {datos['rpe']}{det}{extra}")

# --------------------------
# Autenticación y usuarios
# --------------------------
USUARIO_VALIDO = re.compile(r"^[a-z0-9_.-]{3,30}$")

def normalizar_usuario(texto):
    return re.sub(r"\s+", "", str(texto or "")).lower()

def hashear_password(password, sal=None, iteraciones=ITERACIONES_HASH):
    sal = sal or _secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(sal), iteraciones).hex()
    return f"pbkdf2${iteraciones}${sal}${h}"

def verificar_hash(password, almacenado):
    try:
        _, it, sal, h = str(almacenado).split("$")
        nuevo = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(sal), int(it)).hex()
        return hmac.compare_digest(nuevo, h)
    except Exception:
        return False

def config_auth():
    try:
        return dict(st.secrets["app_auth"])
    except Exception:
        return {}

def leer_usuarios():
    return _get_sheet(NOMBRE_LIBRO, "Usuarios").get_all_records()

@st.cache_data(ttl=60, show_spinner=False)
def listar_usuarios():
    try:
        return leer_usuarios()
    except Exception:
        return []

@st.cache_resource
def _registro_intentos():
    return {"lock": threading.Lock(), "fallos": {}}

def segundos_bloqueado(usuario):
    reg = _registro_intentos()
    with reg["lock"]:
        info = reg["fallos"].get(usuario)
        if info and info["hasta"] > time.time():
            return int(info["hasta"] - time.time())
    return 0

def registrar_fallo(usuario):
    reg = _registro_intentos()
    with reg["lock"]:
        if len(reg["fallos"]) > 5000:
            reg["fallos"].clear()
        info = reg["fallos"].setdefault(usuario, {"n": 0, "hasta": 0})
        info["n"] += 1
        if info["n"] >= MAX_FALLOS:
            info["hasta"] = time.time() + BLOQUEO_SEG
            info["n"] = 0

def limpiar_fallos(usuario):
    reg = _registro_intentos()
    with reg["lock"]:
        reg["fallos"].pop(usuario, None)

def verificar_login(usuario, password):
    """Devuelve los datos de sesión si las credenciales son correctas; si no, None."""
    cfg = config_auth()
    admin_u = normalizar_usuario(cfg.get("admin_usuario", ""))
    admin_p = str(cfg.get("admin_password", ""))
    if usuario and usuario == admin_u and admin_p:
        if hmac.compare_digest(password.encode("utf-8"), admin_p.encode("utf-8")):
            return {"usuario": admin_u, "nombre": cfg.get("admin_nombre", "Coach"),
                    "rol": "admin", "libro": NOMBRE_LIBRO, "debe_cambiar": False}
        return None
    try:
        filas = leer_usuarios()
    except Exception as e:
        st.error(f"No pude consultar los usuarios: {e}")
        return None
    for fila in filas:
        if normalizar_usuario(fila.get("Usuario")) == usuario:
            activo = str(fila.get("Activo", "")).strip().lower() in VALORES_SI
            if activo and verificar_hash(password, fila.get("Hash", "")):
                return {"usuario": usuario, "nombre": fila.get("Nombre") or usuario,
                        "rol": "cliente", "libro": fila.get("Libro") or f"CoachLean_{usuario}",
                        "debe_cambiar": str(fila.get("Debe_cambiar", "")).strip().lower() in VALORES_SI}
            return None
    verificar_hash(password, "pbkdf2$1$00$00")  # usuario inexistente: no revelar por tiempo de respuesta
    return None

def actualizar_usuario(usuario, **campos):
    ws = _get_sheet(NOMBRE_LIBRO, "Usuarios")
    valores = ws.get_all_values()
    if not valores:
        return False
    cabecera = [c.strip() for c in valores[0]]
    for i, fila in enumerate(valores[1:], start=2):
        if fila and normalizar_usuario(fila[0]) == usuario:
            for campo, valor in campos.items():
                ws.update_cell(i, cabecera.index(campo) + 1, valor)
            listar_usuarios.clear()
            return True
    return False

def validar_password_nueva(nueva, repetir):
    if len(nueva) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if nueva != repetir:
        return "Las contraseñas no coinciden."
    return None

def pantalla_login():
    st.title("💪 Coach Lean")
    cfg = config_auth()
    if not cfg.get("admin_usuario") or not cfg.get("admin_password"):
        st.error("Falta configurar el acceso. En Streamlit: Settings → Secrets, agrega este bloque:")
        st.code('[app_auth]\nadmin_usuario = "jorge"\nadmin_password = "una-contraseña-larga-y-única"\n'
                'admin_nombre = "Jorge"\nadmin_email = "tu-correo@gmail.com"', language="toml")
        st.stop()
    st.caption("Inicia sesión para continuar")
    with st.form("form_login"):
        u = st.text_input("Usuario")
        p = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar"):
            usuario = normalizar_usuario(u)
            espera = segundos_bloqueado(usuario)
            if espera:
                st.error(f"Demasiados intentos fallidos. Espera {espera // 60 + 1} min e inténtalo de nuevo.")
            else:
                datos = verificar_login(usuario, p)
                if datos:
                    limpiar_fallos(usuario)
                    st.session_state.auth = datos
                    st.rerun()
                else:
                    registrar_fallo(usuario)
                    time.sleep(1)
                    st.error("Usuario o contraseña incorrectos.")

def pantalla_cambio_obligatorio(auth):
    st.title("🔐 Crea tu contraseña")
    st.caption("Es tu primer ingreso (o tu coach reseteó tu clave). Elige una contraseña personal.")
    with st.form("form_cambio_obligatorio"):
        nueva = st.text_input("Nueva contraseña (mínimo 8 caracteres)", type="password")
        repetir = st.text_input("Repite la contraseña", type="password")
        if st.form_submit_button("Guardar y continuar"):
            error = validar_password_nueva(nueva, repetir)
            if error:
                st.error(error)
            else:
                actualizar_usuario(auth["usuario"], Hash=hashear_password(nueva), Debe_cambiar="no")
                st.session_state.auth["debe_cambiar"] = False
                st.rerun()

def cerrar_sesion():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

def cambiar_password(usuario, actual, nueva):
    for fila in leer_usuarios():
        if normalizar_usuario(fila.get("Usuario")) == usuario:
            if not verificar_hash(actual, fila.get("Hash", "")):
                return "La contraseña actual no es correcta."
            actualizar_usuario(usuario, Hash=hashear_password(nueva), Debe_cambiar="no")
            return None
    return "No encontré tu usuario."

def crear_cliente(usuario, nombre):
    """Crea el cliente y su libro de datos. Devuelve (contraseña temporal, error)."""
    cfg = config_auth()
    if not USUARIO_VALIDO.match(usuario):
        return None, "Usuario inválido: 3 a 30 caracteres con letras minúsculas, números, punto, guion o guion bajo."
    if usuario == normalizar_usuario(cfg.get("admin_usuario", "")) or \
            any(normalizar_usuario(f.get("Usuario")) == usuario for f in listar_usuarios()):
        return None, "Ese usuario ya existe."
    libro = f"CoachLean_{usuario}"
    try:
        _get_libro(libro)
    except Exception as e:
        return None, (f"No pude crear el libro del cliente: {e}. "
                      "Revisa que la API de Google Drive esté habilitada para tu cuenta de servicio.")
    password = _secrets.token_urlsafe(9)
    _get_sheet(NOMBRE_LIBRO, "Usuarios").append_row(
        [usuario, nombre, hashear_password(password), "cliente", libro, "sí", "sí", str(hoy_lima())])
    listar_usuarios.clear()
    return password, None

def copiar_rutina_a(libro_destino):
    origen = _get_sheet(NOMBRE_LIBRO, "Rutinas").get_all_values()
    destino = _get_sheet(libro_destino, "Rutinas")
    destino.clear()
    destino.append_rows(origen, value_input_option="RAW")
    cargar_programa.clear()

def panel_admin():
    st.markdown("### 👥 Administrar clientes")
    cred = st.session_state.get("credencial_nueva")
    if cred:
        st.success(f"Entrega estos datos a **{cred['usuario']}** (se muestran una sola vez):")
        st.code(f"Usuario: {cred['usuario']}\nContraseña temporal: {cred['password']}", language=None)
        st.caption("Deberá cambiarla al entrar por primera vez.")
        if st.button("Ocultar credenciales", key="ocultar_cred"):
            del st.session_state["credencial_nueva"]
            st.rerun()

    with st.form("form_nuevo_cliente"):
        nuevo_u = st.text_input("Usuario del cliente (minúsculas, sin espacios)")
        nuevo_n = st.text_input("Nombre")
        if st.form_submit_button("➕ Crear cliente"):
            usuario = normalizar_usuario(nuevo_u)
            password, error = crear_cliente(usuario, nuevo_n.strip() or usuario)
            if error:
                st.error(error)
            else:
                st.session_state["credencial_nueva"] = {"usuario": usuario, "password": password}
                st.rerun()

    usuarios = [u for u in listar_usuarios() if u.get("Usuario")]
    if not usuarios:
        st.info("Aún no tienes clientes.")
        return
    tabla = pd.DataFrame(usuarios).reindex(columns=["Usuario", "Nombre", "Activo", "Libro", "Creado"])
    mostrar_tabla(tabla)

    sel = st.selectbox("Gestionar cliente", [normalizar_usuario(u["Usuario"]) for u in usuarios], key="gest_cliente")
    fila_sel = next(u for u in usuarios if normalizar_usuario(u["Usuario"]) == sel)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔑 Resetear contraseña", key="btn_reset_pass"):
            nueva = _secrets.token_urlsafe(9)
            actualizar_usuario(sel, Hash=hashear_password(nueva), Debe_cambiar="sí")
            st.session_state["credencial_nueva"] = {"usuario": sel, "password": nueva}
            st.rerun()
    with c2:
        activo = str(fila_sel.get("Activo", "")).strip().lower() in VALORES_SI
        if st.button("⏸️ Desactivar" if activo else "▶️ Activar", key="btn_toggle_activo"):
            actualizar_usuario(sel, Activo="no" if activo else "sí")
            st.rerun()
    confirmar = st.checkbox(f"Confirmo reemplazar la rutina de {sel} por la mía", key="conf_copiar")
    if st.button("📋 Copiar mi rutina a este cliente", key="btn_copiar") and confirmar:
        try:
            copiar_rutina_a(fila_sel.get("Libro") or f"CoachLean_{sel}")
            st.success("Rutina copiada. El cliente la verá al recargar su app.")
        except Exception as e:
            st.error(f"No pude copiar la rutina: {e}")

# ---------- Puerta de entrada ----------
if "auth" not in st.session_state:
    st.session_state.auth = None
if st.session_state.auth is None:
    pantalla_login()
    st.stop()
auth = st.session_state.auth
if auth.get("debe_cambiar"):
    pantalla_cambio_obligatorio(auth)
    st.stop()
es_admin = auth["rol"] == "admin"

# ---------- Cabecera y cuenta que se está viendo ----------
st.title("💪 Coach Lean")
cab1, cab2 = st.columns([3, 1])
cab1.caption(f"👤 {auth['nombre']}" + (" · Coach" if es_admin else ""))
if cab2.button("Salir", key="btn_salir"):
    cerrar_sesion()
st.caption("Postura • Abs • Cuerpo lean y musculoso • Programa de 12 semanas")

cuenta_activa = auth["usuario"]
libro_cuenta = auth["libro"]
if es_admin:
    clientes = [c for c in listar_usuarios()
                if c.get("Usuario") and str(c.get("Activo", "")).strip().lower() in VALORES_SI]
    if clientes:
        opciones = [auth["usuario"]] + [normalizar_usuario(c["Usuario"]) for c in clientes]
        etiquetas = {auth["usuario"]: "Mi cuenta"}
        etiquetas.update({normalizar_usuario(c["Usuario"]): f"{c.get('Nombre') or c['Usuario']} ({c['Usuario']})"
                          for c in clientes})
        if st.session_state.get("usuario_activo") not in opciones:
            st.session_state["usuario_activo"] = auth["usuario"]
        cuenta_activa = st.selectbox("Viendo los datos de:", opciones,
                                     format_func=lambda u: etiquetas.get(u, u), key="usuario_activo")
        if cuenta_activa != auth["usuario"]:
            fila_c = next(c for c in clientes if normalizar_usuario(c["Usuario"]) == cuenta_activa)
            libro_cuenta = fila_c.get("Libro") or f"CoachLean_{cuenta_activa}"
            st.warning(f"Estás viendo (y registrando en) la cuenta de **{etiquetas[cuenta_activa]}**.")

if st.session_state.get("_cuenta_prev", cuenta_activa) != cuenta_activa:
    st.session_state.sesion_iniciada = False
    st.session_state.grupo_elegido = None
    st.session_state.checkin_saltado = False
st.session_state["_cuenta_prev"] = cuenta_activa
st.session_state["libro_activo"] = libro_cuenta

try:
    _get_libro(libro_cuenta)
except Exception as e:
    st.error(f"No pude abrir los datos de esta cuenta: {e}")
    st.stop()

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
libro = libro_activo()
rutinas, guias = cargar_programa(libro)
df_hist = obtener_historial(libro)
df_m = obtener_medidas(libro)
df_check = obtener_checkin(libro)
df_checks = obtener_checks(libro)
config = obtener_config(libro)
fecha_inicio = parse_fecha(config.get("fecha_inicio", "")) or hoy
modo_avance = config.get("modo_avance", "sesiones")
if modo_avance not in ("sesiones", "calendario"):
    modo_avance = "sesiones"
sesiones_previas = contar_sesiones_previas(df_hist, fecha_inicio, hoy)
semana = calcular_semana(fecha_inicio, modo_avance, sesiones_previas)
fase = fase_de_semana(semana)
detalle_avance = f"{sesiones_previas} sesiones completadas" if modo_avance == "sesiones" else ""
registros_todos = pd.concat([df_hist[["Fecha", "Ejercicio"]], df_checks[["Fecha", "Ejercicio"]]], ignore_index=True)
rec = estado_recuperacion(ultimo_por_musculo(registros_todos, guias), hoy)
checks_hoy = ejercicios_de_hoy(df_checks, hoy)
gym_hoy = ejercicios_de_hoy(df_hist, hoy)
checkin_hoy = checkin_de_hoy(df_check, hoy)
cuidado, avisos_checkin = evaluar_checkin(checkin_hoy)

# --------------------------
# Interfaz
# --------------------------
tab_entrenar, tab_casa, tab_medidas, tab_stats, tab_programa, tab_cuenta = st.tabs(
    ["🏋️ Entrenar", "🏠 Casa", "📏 Medidas", "📊 Estadísticas", "📋 Programa", "⚙️ Cuenta"]
)

# ==================================================
# TAB: ENTRENAR
# ==================================================
with tab_entrenar:
    # ---------- Pantalla inicial ----------
    if not st.session_state.sesion_iniciada:
        st.markdown("### ¿Qué quieres hacer hoy?")
        banner_programa(semana, fase, detalle_avance)

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
        banner_programa(semana, fase, detalle_avance)
        for aviso in avisos_checkin:
            st.warning(aviso)
        if not rutinas:
            st.warning("No hay rutinas activas. Revisa la pestaña 'Rutinas' de tu Google Sheet.")
        st.caption("Ordenadas según qué tan recuperados están los músculos de cada sesión. "
                   "Si faltaste unos días, la app te propone la sesión que más lo necesita.")

        prioridad = []
        for grupo in rutinas.keys():
            minimo, promedio, pendientes = preparacion_sesion(rutinas[grupo], guias, rec)
            prioridad.append({
                "grupo": grupo,
                "dias": dias_desde_ultimo(df_hist, rutinas[grupo]),
                "min": minimo, "prom": promedio, "pend": pendientes,
                "listo": minimo >= UMBRAL_LISTO,
            })
        prioridad = sorted(prioridad, key=lambda x: (0, -x["dias"]) if x["listo"] else (1, -x["prom"]))

        for idx, item in enumerate(prioridad):
            if item["listo"]:
                estado = "🟢 Lista" if item["dias"] == 999 else f"🟢 Lista (hace {item['dias']}d)"
            else:
                m, p = item["pend"][0]
                icono = "🟠" if item["min"] >= UMBRAL_CASI else "🔴"
                estado = f"{icono} {m} {p:.0%}"
            marca = "⭐ " if idx == 0 else ""
            if st.button(f"{marca}{item['grupo']}  —  {estado}", key=f"grp_{item['grupo']}"):
                st.session_state.grupo_elegido = item["grupo"]
                st.session_state.hora_inicio = ahora_lima().strftime("%H:%M")
                st.rerun()

        with st.expander("🧩 Recuperación por músculo"):
            panel_recuperacion(rec)

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
        _, _, pendientes_sesion = preparacion_sesion(rutinas.get(grupo, []), guias, rec)
        if pendientes_sesion:
            lista = ", ".join(f"{m} {p:.0%}" for m, p in pendientes_sesion)
            st.warning(f"⚠️ Aún no se recuperan del todo: {lista}. Puedes entrenar, pero baja la carga ~10% o una serie en esos músculos.")

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
                hecha = ejercicio in checks_hoy
                with st.expander(f"{'✅' if hecha else '🧘'} {ejercicio}", expanded=False):
                    mostrar_guia(info, series_obj, reps_obj, fase, semana)
                    if hecha:
                        st.success("✅ Marcada como hecha hoy")
                    elif st.button("✔ Marcar como hecha", key=f"mov_{grupo}_{ejercicio}"):
                        guardar_filas("Checks", [[str(hoy), ejercicio, "Movilidad", "Gym", ""]])
                        st.rerun()
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
                    dias_pausa = (hoy - fecha_ult.date()).days if not pd.isna(fecha_ult) else 0
                    peso_sug, motivo = sugerencia(ult, reps_obj, semana, cuidado, dias_pausa)
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
# TAB: CASA (checks de postura, core y movilidad)
# ==================================================
with tab_casa:
    st.subheader("🏠 Postura y core: tu seguimiento diario")
    st.caption("Marca lo que hiciste, en casa o en el gym. Cuenta igual para tu meta semanal (3-4 veces).")

    lunes = hoy - timedelta(days=hoy.weekday())
    dias_bl = dias_por_bloque(df_hist, df_checks, guias, hoy - timedelta(days=60))
    m1, m2, m3 = st.columns(3)
    for col, nombre_bl in ((m1, "Postura"), (m2, "Core"), (m3, "Movilidad")):
        dias_sem = {d for d in dias_bl[nombre_bl] if d >= lunes}
        col.metric(f"{nombre_bl} (semana)", f"{len(dias_sem)} días")
    racha = racha_dias(dias_bl["Postura"], hoy)
    if racha >= 2:
        st.success(f"🔥 Racha de postura: {racha} días seguidos")

    lugar = st.radio("¿Dónde lo hiciste?", ["Casa", "Gym"], horizontal=True, key="lugar_check")
    solo_casa = st.checkbox("Mostrar solo ejercicios sin máquinas (para casa)", value=True, key="solo_casa")

    vistos, lista = set(), []
    for _grupo, _ejs in rutinas.items():
        for _ej in _ejs:
            _info = guias.get(_ej, {})
            if _info.get("Bloque") in BLOQUES_CHECK and _ej not in vistos:
                vistos.add(_ej)
                lista.append((_ej, _info))
    if solo_casa:
        lista = [(e, i) for e, i in lista if se_puede_en_casa(e, i)]

    if not lista:
        st.info("Aún no hay ejercicios de postura, core o movilidad en tu programa.")
    else:
        if "cnt_casa" not in st.session_state:
            st.session_state["cnt_casa"] = 0
        cnt = st.session_state["cnt_casa"]
        with st.form(f"form_casa_{cnt}"):
            marcados = []
            for bloque_c in BLOQUES_CHECK:
                items = [(e, i) for e, i in lista if i.get("Bloque") == bloque_c]
                if not items:
                    continue
                st.markdown(f"##### {bloque_c}")
                for ej, info in items:
                    s_obj, r_obj = objetivo_fase(info, fase)
                    etiqueta = f"{ej} · {s_obj} x {r_obj}" if (s_obj or r_obj) else ej
                    if ej in checks_hoy or ej in gym_hoy:
                        st.markdown(f"✅ {etiqueta} — hecho hoy")
                    elif st.checkbox(etiqueta, key=f"chk_{cnt}_{ej}"):
                        marcados.append((ej, bloque_c))
                    with st.expander("ℹ️ Cómo hacerlo"):
                        mostrar_guia(info, s_obj, r_obj, fase, semana)
            notas_c = st.text_input("Notas (opcional)", key=f"nota_casa_{cnt}")
            if st.form_submit_button("💾 Guardar checks"):
                if not marcados:
                    st.warning("Marca al menos un ejercicio")
                else:
                    try:
                        guardar_filas("Checks", [[str(hoy), e, b, lugar, notas_c] for e, b in marcados])
                        st.session_state["cnt_casa"] += 1
                        st.toast("✅ Checks guardados")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar: {e}")

    st.divider()
    st.markdown("**Últimos 14 días**")
    dias_fuerza = dias_con_registros(df_hist)
    filas_14 = []
    for i in range(14):
        d = hoy - timedelta(days=i)
        filas_14.append({
            "Día": f"{DIAS_ES[d.weekday()]} {d.day:02d}",
            "Fuerza": "✅" if d in dias_fuerza else "·",
            "Postura": "✅" if d in dias_bl["Postura"] else "·",
            "Core": "✅" if d in dias_bl["Core"] else "·",
            "Movilidad": "✅" if d in dias_bl["Movilidad"] else "·",
        })
    mostrar_tabla(pd.DataFrame(filas_14))

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
        mostrar_tabla(df_m.iloc[::-1])
    else:
        st.info("Todavía no hay medidas registradas.")

# ==================================================
# TAB: ESTADÍSTICAS
# ==================================================
with tab_stats:
    st.subheader("📊 Tu progreso")
    with st.expander("🧩 Recuperación por músculo"):
        panel_recuperacion(rec)

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
        dias_sem_bl = dias_por_bloque(df_hist, df_checks, guias, lunes)
        w2.metric("Días con postura", len(dias_sem_bl["Postura"]))
        w3.metric("Días con core", len(dias_sem_bl["Core"]))

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
        mostrar_tabla(sub[["Fecha", "Peso", "Series", "Reps", "RPE", "Notas"]].iloc[::-1])

        st.divider()
        st.markdown("**🏆 Marcas personales (peso máximo)**")
        prs = (temp.dropna(subset=["Peso_num"])
                   .query("Peso_num > 0")
                   .groupby("Ejercicio")["Peso_num"].max()
                   .sort_values(ascending=False))
        mostrar_tabla(prs.rename("Peso máx (kg)"), hide_index=False)

    if not df_check.empty:
        st.divider()
        with st.expander("🩺 Check-ins recientes"):
            st.caption("Dolor: 0 = nada, 1 = leve, 2 = moderado, 3 = fuerte")
            mostrar_tabla(df_check.iloc[::-1].head(14))

# ==================================================
# TAB: PROGRAMA
# ==================================================
with tab_programa:
    st.subheader("📋 Mi programa (12 semanas)")
    banner_programa(semana, fase, detalle_avance)
    st.progress(min(semana, TOTAL_SEMANAS) / TOTAL_SEMANAS)

    datos_fase = pd.DataFrame([
        {"Fase": f, "Semanas": d["semanas"], "Nombre": d["nombre"], "RPE": d["rpe"], "Foco": d["foco"]}
        for f, d in FASES.items()
    ])
    mostrar_tabla(datos_fase)
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
    mostrar_tabla(pd.DataFrame(SEMANA_TIPO, columns=["Día", "Sesión"]))

    st.divider()
    st.markdown("**Ajustes del programa**")
    modos = {
        "sesiones": "Por sesiones (recomendado si no vas siempre al gym)",
        "calendario": "Por calendario (1 semana = 7 días)",
    }
    modo_sel = st.radio("¿Cómo avanzan las semanas y las fases?", list(modos.keys()),
                        format_func=lambda k: modos[k], index=0 if modo_avance == "sesiones" else 1)
    st.caption("Por sesiones: cada 4 sesiones que entrenas cuentan como 1 semana, así no pierdes la progresión si faltas.")
    nueva_fecha = st.date_input("Fecha de inicio del programa", value=fecha_inicio, key="fecha_inicio_input")
    if st.button("💾 Guardar ajustes"):
        try:
            guardar_config("fecha_inicio", nueva_fecha)
            guardar_config("modo_avance", modo_sel)
            st.toast("✅ Ajustes guardados")
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

    st.caption("Para cambiar ejercicios, edita la pestaña 'Rutinas' de tu Google Sheet.")

# ==================================================
# TAB: CUENTA
# ==================================================
with tab_cuenta:
    st.subheader("⚙️ Cuenta")
    st.write(f"Usuario: **{auth['usuario']}** · {'Coach (administrador)' if es_admin else 'Cliente'}")
    if es_admin:
        st.info("Tu contraseña de coach se cambia en Streamlit: Settings → Secrets (bloque app_auth).")
    else:
        with st.form("form_cambiar_pass"):
            actual = st.text_input("Contraseña actual", type="password")
            nueva = st.text_input("Nueva contraseña (mínimo 8 caracteres)", type="password")
            repetir = st.text_input("Repite la nueva contraseña", type="password")
            if st.form_submit_button("🔑 Cambiar contraseña"):
                error = validar_password_nueva(nueva, repetir)
                if error:
                    st.error(error)
                else:
                    try:
                        error = cambiar_password(auth["usuario"], actual, nueva)
                    except Exception as e:
                        error = f"No pude cambiar la contraseña: {e}"
                    if error:
                        st.error(error)
                    else:
                        st.success("Contraseña actualizada.")
    if st.button("Cerrar sesión", key="btn_salir2"):
        cerrar_sesion()
    if es_admin:
        st.divider()
        panel_admin()

st.markdown("---")
st.caption("Coach Lean • Programa de 12 semanas • Cambia los ejercicios desde Google Sheets")
