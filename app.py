import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date
from collections import defaultdict
import time

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
# Configuración de Google Sheets
# --------------------------
NOMBRE_LIBRO = "CoachLeanHistorial"

HISTORIAL_COLUMNAS = ["Fecha", "Ejercicio", "Peso", "Series", "Reps", "RPE", "Notas"]

MEDIDAS_COLUMNAS = [
    "Fecha", "Peso", "Cuello", "Hombros", "Pecho", "Cintura", "Cadera",
    "Brazo D", "Brazo I", "Muslo", "Pantorrilla", "Notas"
]

REST_DAYS = {
    "Pecho": 2, "Espalda": 2, "Hombros": 2, "Bíceps": 1,
    "Tríceps": 3, "Piernas": 3, "Glúteos": 3, "Abs": 1
}

@st.cache_resource
def get_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    return gspread.authorize(creds)

def get_sheet(nombre):
    """Devuelve la pestaña pedida; la crea con encabezados si no existe."""
    libro = get_client().open(NOMBRE_LIBRO)
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
        return ws

def guardar_fila(pestana, fila):
    get_sheet(pestana).append_row(fila)
    obtener_historial.clear()
    obtener_medidas.clear()

# --------------------------
# Lectura de datos (con caché para que la app vuele)
# --------------------------
@st.cache_data(ttl=120, show_spinner=False)
def obtener_historial():
    columnas = HISTORIAL_COLUMNAS
    try:
        data = get_sheet("Historial").get_all_records()
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

@st.cache_data(ttl=120, show_spinner=False)
def obtener_medidas():
    columnas = MEDIDAS_COLUMNAS
    try:
        data = get_sheet("Medidas").get_all_records()
        if not data:
            return pd.DataFrame(columns=columnas)
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        for col in columnas:
            if col not in df.columns:
                df[col] = None
        return df[columnas]
    except Exception as e:
        st.warning(f"Error leyendo medidas: {e}")
        return pd.DataFrame(columns=columnas)

@st.cache_data(ttl=120, show_spinner=False)
def obtener_rutinas_activas():
    try:
        data = get_sheet("Rutinas").get_all_records()
        if not data:
            return {}
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        if "Activo" in df.columns:
            df = df[df["Activo"].astype(str).str.strip().str.lower().isin(["sí", "si", "s", "yes", "1"])]
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

@st.cache_data(ttl=120, show_spinner=False)
def obtener_guias():
    """Lee la info de cada ejercicio (técnica, imagen, etc.) desde Rutinas."""
    try:
        data = get_sheet("Rutinas").get_all_records()
        guias = {}
        for fila in data:
            ej = str(fila.get("Ejercicio", "")).strip()
            if ej:
                guias[ej] = {str(k).strip(): str(v).strip() for k, v in fila.items()}
        return guias
    except Exception as e:
        st.warning(f"Error leyendo guías: {e}")
        return {}

def mostrar_guia(info):
    """Muestra imagen, video y descripción del ejercicio (solo lo que esté lleno)."""
    if not info:
        return
    if info.get("Imagen"):
        st.image(info["Imagen"], use_container_width=True)
    if info.get("Video"):
        st.video(info["Video"])
    if info.get("Series") or info.get("Reps"):
        st.markdown(
            f"🎯 **Objetivo:** {info.get('Series', '-')} series x {info.get('Reps', '-')} reps"
            f" · descanso {info.get('Descanso', '-')}"
        )
    if info.get("Tecnica"):
        st.markdown(f"**Técnica:** {info['Tecnica']}")
    if info.get("Respiracion"):
        st.markdown(f"**Respiración:** {info['Respiracion']}")
    if info.get("Errores"):
        st.warning(f"**Errores comunes:** {info['Errores']}")


# --------------------------
# Helpers
# --------------------------
def ultimo_registro(df, ejercicio):
    if df.empty or "Ejercicio" not in df.columns:
        return None
    coincidencias = df[df["Ejercicio"] == ejercicio].copy()
    if coincidencias.empty:
        return None
    coincidencias["Fecha_dt"] = pd.to_datetime(coincidencias["Fecha"], errors="coerce")
    coincidencias = coincidencias.sort_values("Fecha_dt", ascending=False)
    return coincidencias.iloc[0]

def sugerir_peso(ult):
    try:
        peso = float(ult.get("Peso"))
        rpe = pd.to_numeric(pd.Series([ult.get("RPE")]), errors="coerce").iloc[0]
        if pd.isna(rpe):
            return peso
        if rpe <= 6:
            return peso + 2.5
        if rpe <= 8:
            return peso
        return max(peso - 2.5, 0)
    except Exception:
        return None

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
    return (date.today() - ultima.date()).days

# --------------------------
# Estado de sesión
# --------------------------
hoy = str(date.today())

for clave, valor in [("fecha_sesion", None), ("grupo_elegido", None), ("sesion_iniciada", False)]:
    if clave not in st.session_state:
        st.session_state[clave] = valor

if st.session_state.fecha_sesion != hoy:
    st.session_state.sesion_iniciada = False
    st.session_state.grupo_elegido = None
    st.session_state.fecha_sesion = hoy

# --------------------------
# Interfaz
# --------------------------
st.title("💪 Coach Lean")
st.caption("Postura • Abs • Cuerpo lean y musculoso • Programas flexibles")
guias = obtener_guias()

rutinas = obtener_rutinas_activas()
df_hist = obtener_historial()

tab_entrenar, tab_medidas, tab_stats, tab_programa = st.tabs(
    ["🏋️ Entrenar", "📏 Medidas", "📊 Estadísticas", "📋 Programa"]
)

# ==================================================
# TAB: ENTRENAR
# ==================================================
with tab_entrenar:
    if not st.session_state.sesion_iniciada:
        st.markdown("### ¿Qué quieres hacer hoy?")

        if df_hist.empty:
            st.info("Aún no tienes registros. ¡Inicia tu primera rutina! 💪")
        else:
            temp = df_hist.copy()
            temp["Fecha_dt"] = pd.to_datetime(temp["Fecha"], errors="coerce").dt.date
            dias_entrenados = sorted(set(temp["Fecha_dt"].dropna()))
            recientes = [d for d in dias_entrenados if (date.today() - d).days <= 30]
            c1, c2 = st.columns(2)
            c1.metric("Días entrenados (30 días)", len(recientes))
            if dias_entrenados:
                c2.metric("Último entrenamiento", max(dias_entrenados).strftime("%d %b"))

        st.write("")
        if st.button("🏋️ Iniciar rutina de hoy"):
            st.session_state.sesion_iniciada = True
            st.rerun()

    elif st.session_state.grupo_elegido is None:
        st.subheader("Elige el grupo muscular de hoy")
        st.caption("Ordenados por prioridad de recuperación")

        prioridad = []
        for grupo in rutinas.keys():
            descanso = REST_DAYS.get(grupo, 2)
            dias = dias_desde_ultimo(df_hist, rutinas[grupo])
            prioridad.append({"grupo": grupo, "dias": dias,
                              "listo": dias >= descanso, "descanso": descanso})
        prioridad = sorted(prioridad, key=lambda x: (-x["listo"], -x["dias"]))

        for item in prioridad:
            estado = "🟢 Listo" if item["listo"] else f"🟠 {item['dias']}d (mín {item['descanso']})"
            if st.button(f"{item['grupo']}  —  {estado}", key=f"grp_{item['grupo']}"):
                st.session_state.grupo_elegido = item["grupo"]
                st.session_state.hora_inicio = datetime.now().strftime("%H:%M")
                st.rerun()

        if st.button("⬅️ Volver al inicio"):
            st.session_state.sesion_iniciada = False
            st.rerun()

    else:
        grupo = st.session_state.grupo_elegido
        st.success(f"Sesión de **{grupo}** iniciada a las {st.session_state.get('hora_inicio', '')}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Cambiar de grupo"):
                st.session_state.grupo_elegido = None
                st.rerun()
        with c2:
            if st.button("🏁 Terminar sesión"):
                ej_grupo = rutinas.get(grupo, [])
                temp = df_hist.copy()
                temp["Fecha_dt"] = pd.to_datetime(temp["Fecha"], errors="coerce").dt.date
                hoy_rows = temp[(temp["Fecha_dt"] == date.today()) & (temp["Ejercicio"].isin(ej_grupo))]
                n_ej = hoy_rows["Ejercicio"].nunique()
                n_series = pd.to_numeric(hoy_rows["Series"], errors="coerce").sum()
                st.balloons()
                st.success(f"¡Sesión completada! {n_ej} ejercicios y {int(n_series)} series de {grupo} 💪")
                st.session_state.sesion_iniciada = False
                st.session_state.grupo_elegido = None
                time.sleep(2)
                st.rerun()

        with st.expander("⏱️ Temporizador de descanso"):
            descanso = st.number_input("Segundos de descanso", min_value=15, max_value=600, value=90, step=15)
            if st.button("▶️ Iniciar"):
                placeholder = st.empty()
                barra = st.progress(0)
                fin = time.time() + descanso
                while time.time() < fin:
                    restante = max(0, int(fin - time.time()))
                    placeholder.metric("Tiempo restante", f"{restante // 60:02d}:{restante % 60:02d}")
                    barra.progress(min(1.0, 1 - restante / descanso))
                    time.sleep(1)
                placeholder.success("💪 ¡Descanso terminado, a darle!")
                barra.progress(1.0)

        st.divider()
        st.subheader(f"Ejercicios de {grupo}")

        ejercicios = rutinas.get(grupo, [])
        if not ejercicios:
            st.warning("No hay ejercicios activos para este grupo. Agrégalos en la pestaña 'Rutinas' de tu Google Sheet.")
        else:
            for ejercicio in ejercicios:
                ult = ultimo_registro(df_hist, ejercicio)

                with st.expander(f"📌 {ejercicio}", expanded=False):
                    mostrar_guia(guias.get(ejercicio, {}))
                    if ult is not None:
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Peso", f"{ult.get('Peso', '-')} kg")
                        c2.metric("Series", f"{ult.get('Series', '-')}")
                        c3.metric("RPE", f"{ult.get('RPE', '-')}")
                        detalle = ult.get("Reps", "")
                        if detalle and str(detalle).strip():
                            st.info(f"**Series:** {detalle}")
                        fecha_ult = pd.to_datetime(ult.get("Fecha"), errors="coerce")
                        fecha_txt = fecha_ult.strftime("%d %b %Y") if not pd.isna(fecha_ult) else str(ult.get("Fecha", ""))
                        st.caption(f"Última vez: {fecha_txt}")
                        sug = sugerir_peso(ult)
                        if sug is not None:
                            st.markdown(f"💡 **Sugerencia hoy: {sug} kg**")
                    else:
                        st.caption("Primera vez con este ejercicio. ¡Establece tu base! 🎯")

                    with st.form(key=f"form_{grupo}_{ejercicio}"):
                        st.markdown("**Registra cada serie:**")
                        h1, h2, h3 = st.columns([1, 2, 2])
                        h1.markdown("**Serie**")
                        h2.markdown("**Peso (kg)**")
                        h3.markdown("**Reps**")

                        series_data = []
                        for i in range(1, 6):
                            c1, c2, c3 = st.columns([1, 2, 2])
                            c1.markdown(f"**{i}**")
                            peso = c2.number_input(
                                f"Peso {ejercicio} {i}", min_value=0.0, step=0.5,
                                label_visibility="collapsed", key=f"peso_{grupo}_{ejercicio}_{i}"
                            )
                            reps = c3.number_input(
                                f"Reps {ejercicio} {i}", min_value=0, step=1,
                                label_visibility="collapsed", key=f"reps_{grupo}_{ejercicio}_{i}"
                            )
                            if peso > 0 or reps > 0:
                                series_data.append(f"{peso}kg x {int(reps)}")

                        rpe = st.slider("RPE (esfuerzo percibido)", 1, 10, 7, key=f"rpe_{grupo}_{ejercicio}")
                        notas = st.text_area("Notas (opcional)", key=f"nota_{grupo}_{ejercicio}")

                        if st.form_submit_button("💾 Guardar ejercicio"):
                            if not series_data:
                                st.warning("Registra al menos una serie")
                            else:
                                try:
                                    primer_peso = float(series_data[0].split("kg")[0])
                                    guardar_fila("Historial", [
                                        str(date.today()),
                                        ejercicio,
                                        primer_peso,
                                        len(series_data),
                                        " | ".join(series_data),
                                        rpe,
                                        notas
                                    ])
                                    st.toast("✅ Guardado")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al guardar: {e}")

# ==================================================
# TAB: MEDIDAS
# ==================================================
with tab_medidas:
    st.subheader("📏 Seguimiento de medidas corporales")
    st.caption("Registra solo lo que midas; los cambios se grafican automáticamente.")

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
            fila = [str(date.today())] + ["" if valores[c] == 0 else valores[c] for c in campos] + [notas_med]
            if all(v == "" for v in fila[1:-1]):
                st.warning("Registra al menos una medida")
            else:
                guardar_fila("Medidas", fila)
                st.toast("✅ Medidas guardadas")
                st.rerun()

    df_m = obtener_medidas()
    if not df_m.empty:
        st.divider()
        opciones = [c for c in MEDIDAS_COLUMNAS if c not in ("Fecha", "Notas")]
        medida_sel = st.selectbox("¿Qué medida quieres ver?", opciones)
        unidad = "kg" if medida_sel == "Peso" else "cm"

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
                st.metric(f"{medida_sel} (actual)", f"{ultimo:.1f} {unidad}",
                          delta=f"{ultimo - previo:+.1f} {unidad} vs registro anterior")
            else:
                st.metric(f"{medida_sel} (actual)", f"{ultimo:.1f} {unidad}")
            st.line_chart(reg.set_index("Fecha_dt")[[medida_sel]])
            c1, c2 = st.columns(2)
            c1.metric("Primera medición", f"{reg[medida_sel].iloc[0]:.1f} {unidad}")
            c2.metric("Cambio total", f"{ultimo - reg[medida_sel].iloc[0]:+.1f} {unidad}")
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

        dias = sorted(set(temp["Fecha_dt"].dt.date))
        recientes = [d for d in dias if (date.today() - d).days <= 30]
        c1, c2, c3 = st.columns(3)
        c1.metric("Sesiones (30 días)", len(recientes))
        c2.metric("Ejercicios distintos", temp["Ejercicio"].nunique())
        c3.metric("Registros totales", len(temp))

        st.divider()

        ejercicios_registrados = sorted(temp["Ejercicio"].dropna().unique())
        ej_sel = st.selectbox("Progreso por ejercicio", ejercicios_registrados)
        sub = temp[temp["Ejercicio"] == ej_sel].sort_values("Fecha_dt")
        sub_p = sub.dropna(subset=["Peso_num"])
        if not sub_p.empty:
            st.line_chart(sub_p.set_index("Fecha_dt")[["Peso_num"]].rename(columns={"Peso_num": "Peso (kg)"}))
            st.metric("🏆 Peso máximo registrado", f"{sub_p['Peso_num'].max()} kg")
        st.dataframe(
            sub[["Fecha", "Peso", "Series", "Reps", "RPE", "Notas"]].iloc[::-1],
            use_container_width=True, hide_index=True
        )

        st.divider()
        st.markdown("**🏆 Marcas personales (peso máximo)**")
        prs = (temp.dropna(subset=["Peso_num"])
                  .groupby("Ejercicio")["Peso_num"].max()
                  .sort_values(ascending=False))
        st.dataframe(prs.rename("Peso máx (kg)"), use_container_width=True)

# ==================================================
# TAB: PROGRAMA
# ==================================================
with tab_programa:
    st.subheader("📋 Mi Programa Actual (3 meses)")
    if not rutinas:
        st.warning("No se encontraron rutinas activas. Revisa la pestaña 'Rutinas' en Google Sheets.")
    else:
        for grupo, ejercicios in rutinas.items():
            with st.expander(f"**{grupo}** ({len(ejercicios)} ejercicios)"):
                for i, ej in enumerate(ejercicios, 1):
                    st.write(f"{i}. {ej}")
    st.caption("Para cambiar tu programa edita la pestaña 'Rutinas' de tu Google Sheet (columnas: Grupo, Ejercicio, Orden, Activo).")

st.markdown("---")
st.caption("Coach Lean • Programas flexibles de 3 meses • Cambia los ejercicios desde Google Sheets")
