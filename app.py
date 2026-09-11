# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import json
import re
import sys
from zoneinfo import ZoneInfo
import extra_streamlit_components as stx
import requests
import streamlit as st
from supabase import Client, create_client

# ============================================================
# CONFIGURACION
# ============================================================

st.set_page_config(
    page_title="Gestor de Autorizacion CHESS ERP",
    page_icon="key",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>
        .main {
            padding-top: 1rem;
        }

        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }

        div[data-testid="stMetric"] {
            background-color: #f8f9fa;
            border-radius: 10px;
            padding: 10px;
        }

        .titulo-principal {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }

        .subtitulo {
            color: #666;
            margin-bottom: 1.5rem;
        }

        .estado-ok {
            padding: 12px;
            border-radius: 8px;
            background-color: #e8f5e9;
            border: 1px solid #81c784;
        }

        .estado-error {
            padding: 12px;
            border-radius: 8px;
            background-color: #ffebee;
            border: 1px solid #e57373;
        }

        .estado-warning {
            padding: 12px;
            border-radius: 8px;
            background-color: #fff8e1;
            border: 1px solid #ffca28;
        }

        .info-box {
            padding: 14px;
            border-radius: 8px;
            background-color: #eef4ff;
            border: 1px solid #90caf9;
            margin-bottom: 10px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SUPABASE
# ============================================================


@st.cache_resource
def inicializar_supabase():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]

        supabase: Client = create_client(url, key)

        return supabase

    except Exception as e:
        st.error(f"Error conectando con Supabase: {e}")
        return None


supabase = inicializar_supabase()


# ============================================================
# COOKIE MANAGER
# ============================================================

cookie_manager = stx.CookieManager(key="chess_cookie_manager")


# ============================================================
# SESSION STATE
# ============================================================

valores_iniciales = {
    "autenticado": False,
    "usuario": "",
    "password": "",
    "email": "",
    "log_ejecucion": [],
    "ultimo_mensaje_procesado": "",
    "url_autorizada_lista": False,
    "forzar_ejecucion": False,
    "in_dom": "",
    "in_op": "",
    "in_tick": "",
    "in_mot": "",
    "campo_operador": "",
    "campo_ticket": "",
    "campo_url": "",
    "campo_motivo": "",
    "mensaje": """
Roy Topping, 14 min
URL: https://codenoa.chesserp.com/AR467
Ticket: #512918
Motivo: Gerente que no aparece
""".strip(),
}

for clave, valor in valores_iniciales.items():
    if clave not in st.session_state:
        st.session_state[clave] = valor


# ============================================================
# UTILIDADES
# ============================================================


def ahora_argentina():
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))


def agregar_log(mensaje, nivel="INFO"):
    hora = ahora_argentina().strftime("%H:%M:%S")

    registro = f"[{hora}] [{nivel}] {mensaje}"

    st.session_state.log_ejecucion.append(registro)


def limpiar_log():
    st.session_state.log_ejecucion = []


def normalizar_url(url):
    if not url:
        return ""

    url = url.strip()

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    return url.rstrip("/")


def obtener_dominio(url):
    url = normalizar_url(url)

    match = re.search(r"https?://([^/]+)", url, re.IGNORECASE)

    if match:
        return match.group(1).lower()

    return ""


# ============================================================
# SUPABASE - HISTORIAL
# ============================================================


def registrar_en_historial(
    operador, url, ticket, motivo, usuario_app=None
):
    if supabase is None:
        return False

    try:
        motivo_completo = (
            f"{ticket} - {motivo}".strip() if ticket else motivo
        )

        datos = {
            "usuario": usuario_app or st.session_state.get("usuario", ""),
            "dominio_ruta": url,
            "operador": operador,
            "motivo": motivo_completo,
            "created_at": ahora_argentina().isoformat(),
        }

        resultado = (
            supabase.table("historial_autorizaciones")
            .insert(datos)
            .execute()
        )

        return bool(resultado.data)

    except Exception as e:
        agregar_log(
            f"No se pudo registrar historial: {e}", "WARNING"
        )
        return False


def buscar_autorizacion_reciente(url):
    if supabase is None:
        return None

    try:
        resultado = (
            supabase.table("historial_autorizaciones")
            .select("*")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )

        if not resultado.data:
            return None

        dominio_actual = obtener_dominio(url)

        ahora = ahora_argentina()

        for registro in resultado.data:

            url_registro = registro.get("dominio_ruta", "")
            dominio_registro = obtener_dominio(url_registro)

            if not dominio_actual:
                continue

            if dominio_actual != dominio_registro:
                continue

            fecha_texto = registro.get("created_at")

            if not fecha_texto:
                continue

            try:
                fecha_registro = datetime.fromisoformat(
                    fecha_texto.replace("Z", "+00:00")
                )

                if fecha_registro.tzinfo is None:
                    fecha_registro = fecha_registro.replace(
                        tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")
                    )

                diferencia = ahora - fecha_registro

                if diferencia <= timedelta(minutes=10):
                    return registro

            except Exception:
                continue

        return None

    except Exception as e:
        agregar_log(
            f"Error consultando historial: {e}", "WARNING"
        )
        return None


def extraer_y_actualizar(mensaje):
    if not mensaje:
        return False

    texto = mensaje.strip()

    # 1. Extracci¨®n de Operador
    operador = ""
    patrones_operador = [
        r"^\s*([^,\n]+),\s*(?:\w+\s+)?\d{1,2}(?::\d{2}|\s*(?:min|minutos|mins?))?",
        r"(?:operador|usuario|solicitante|enviado por)\s*:\s*(.+?)(?=\n|$)",
        r"^\s*([^,\n]+),",
    ]

    for patron in patrones_operador:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            op_candidate = match.group(1).strip()
            op_candidate = re.sub(
                r"^enviado\s+por\s+", "", op_candidate, flags=re.IGNORECASE
            )
            if op_candidate and not op_candidate.lower().startswith("url"):
                operador = op_candidate
                break

    # 2. Extracci¨®n de URL
    url_limpia = ""
    patron_url = r"((?:https?://)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?::\d+)?(?:/[^\s#?]*)?)"
    match_url = re.search(patron_url, texto, re.IGNORECASE)

    if match_url:
        raw_url = match_url.group(1).strip().rstrip(".,;")

        if "http" in raw_url.lower():
            idx = raw_url.lower().find("http")
            raw_url = raw_url[idx:]

        if not raw_url.startswith(("http://", "https://")):
            raw_url = "https://" + raw_url

        raw_url = re.sub(r"/#.*$", "", raw_url)
        raw_url = re.sub(r"\?.*$", "", raw_url)

        url_limpia = raw_url.rstrip("/")

    # 3. Extracci¨®n de Ticket
    ticket = ""
    match_ticket = re.search(r"Ticket\s*:\s*#?\s*(\d+)", texto, re.IGNORECASE)
    if match_ticket:
        ticket = f"#{match_ticket.group(1)}"

    # 4. Extracci¨®n de Motivo
    motivo = ""
    match_motivo = re.search(
        r"Motivo\s*:\s*(.+?)(?=\n|$)", texto, re.IGNORECASE
    )
    if match_motivo and match_motivo.group(1).strip():
        motivo = match_motivo.group(1).strip()
    else:
        motivo = "Autorizacion de acceso solicitada"

    st.session_state.in_dom = url_limpia
    st.session_state.in_op = operador
    st.session_state.in_tick = ticket
    st.session_state.in_mot = motivo

    st.session_state.campo_operador = operador
    st.session_state.campo_ticket = ticket
    st.session_state.campo_url = url_limpia
    st.session_state.campo_motivo = motivo

    st.session_state.ultimo_mensaje_procesado = texto
    st.session_state.url_autorizada_lista = bool(url_limpia and operador)

    return True


# ============================================================
# AUTOMATIZACION HTTP
# ============================================================


def automatizar_web(url, usuario, password, operador, detalle):
    limpiar_log()

    url_limpia = normalizar_url(url)
    match_base = re.match(r"(https?://[^/]+/[^/#]+)", url_limpia)
    url_base = match_base.group(1) if match_base else url_limpia

    endpoint_autorizar = (
        f"{url_base.rstrip('/')}/web/api/soporte/v1/validarUsuarioAdmin"
    )

    agregar_log(
        f"Iniciando solicitud en API CHESS ERP: {endpoint_autorizar}..."
    )

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    })

    try:
        motivo_final = (
            f"{st.session_state.in_tick} {detalle}".strip()
            if st.session_state.in_tick
            else detalle
        )

        payload = {
            "usuario": usuario,
            "pass": password,
            "operador": operador,
            "detalle": motivo_final,
        }

        agregar_log(
            f"Enviando autorizacion para operador '{operador}'..."
        )

        response = session.post(
            endpoint_autorizar, json=payload, verify=False, timeout=20
        )

        content_type = response.headers.get("content-type", "N/A")
        agregar_log(
            f"POST -> status {response.status_code}, content-type:"
            f" {content_type}",
            "DEBUG",
        )

        try:
            data_respuesta = response.json()
        except Exception as e_json:
            agregar_log(f"No se pudo parsear JSON: {e_json}", "ERROR")
            return False, "\n".join(st.session_state.log_ejecucion)

        errores = data_respuesta.get("error", [])

        if response.status_code in [200, 201] and not errores:
            agregar_log("AUTORIZACION COMPLETADA CON EXITO.", "OK")

            registrar_en_historial(
                operador=operador,
                url=url,
                ticket=st.session_state.in_tick,
                motivo=detalle,
                usuario_app=st.session_state.usuario,
            )

            return True, "\n".join(st.session_state.log_ejecucion)
        else:
            agregar_log(f"ERROR EN AUTORIZACION: {errores}", "ERROR")
            return False, "\n".join(st.session_state.log_ejecucion)

    except Exception as e:
        agregar_log(f"ERROR DE CONEXION: {str(e)}", "ERROR")
        return False, "\n".join(st.session_state.log_ejecucion)


def consultar_usuario(username):
    if supabase is None:
        return None

    try:
        resultado = (
            supabase.table("usuarios_app")
            .select("*")
            .or_(f"usuario.eq.{username},email.eq.{username}")
            .limit(1)
            .execute()
        )

        if resultado.data:
            return resultado.data[0]

        return None

    except Exception as e:
        st.error(f"Error consultando usuario: {e}")
        return None


def autenticar_usuario(username, password):
    usuario = consultar_usuario(username)

    if not usuario:
        return False, "Usuario no encontrado."

    password_bd = usuario.get("password")

    if password_bd != password:
        return False, "Contrasena incorrecta."

    return True, usuario


def registrar_usuario(username, password, email):
    if supabase is None:
        return False, "Supabase no esta disponible."

    try:
        existente = consultar_usuario(username)

        if existente:
            return False, "El usuario ya existe."

        datos = {"usuario": username, "email": email, "password": password}

        resultado = (
            supabase.table("usuarios_app").insert(datos).execute()
        )

        if resultado.data:
            return True, "Usuario registrado correctamente."

        return False, "No se pudo registrar el usuario."

    except Exception as e:
        return False, str(e)


def vista_login():
    st.markdown(
        '<div class="titulo-principal">Gestor de Autorizacion CHESS ERP</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitulo">Ingreso al sistema de autorizacion</div>',
        unsafe_allow_html=True,
    )

    tab_login, tab_registro = st.tabs(
        ["Iniciar Sesion", "Registrar Usuario"]
    )

    with tab_login:
        usuario = st.text_input(
            "Usuario / Email",
            value=st.session_state.usuario,
            key="login_usuario",
        )
        password = st.text_input(
            "Contrasena",
            type="password",
            value=st.session_state.password,
            key="login_password",
        )
        recordar = st.checkbox(
            "Recordar credenciales y mantener sesion activa",
            value=False,
            key="recordar_login",
        )

        if st.button("Iniciar Sesion", type="primary", use_container_width=True):
            if not usuario or not password:
                st.error("Ingresa usuario y contrasena.")
            else:
                correcto, resultado = autenticar_usuario(
                    usuario, password
                )
                if correcto:
                    usuario_real = resultado.get("usuario", usuario)

                    st.session_state.autenticado = True
                    st.session_state.usuario = usuario_real
                    st.session_state.password = password

                    if recordar:
                        try:
                            cookie_manager.set(
                                "chess_usuario",
                                usuario_real,
                                expires_at=(
                                    ahora_argentina() + timedelta(days=30)
                                ),
                            )
                        except Exception:
                            pass

                    st.success("Inicio de sesion correcto.")
                    st.rerun()
                else:
                    st.error(resultado)

    with tab_registro:
        nuevo_usuario = st.text_input("Usuario", key="registro_usuario")
        nuevo_email = st.text_input("Email", key="registro_email")
        nueva_password = st.text_input(
            "Contrasena", type="password", key="registro_password"
        )
        repetir_password = st.text_input(
            "Repetir contrasena", type="password", key="registro_password2"
        )

        if st.button(
            "Registrar Usuario", type="primary", use_container_width=True
        ):
            if not nuevo_usuario:
                st.error("Ingresa un usuario.")
            elif not nuevo_email:
                st.error("Ingresa un email.")
            elif not nueva_password:
                st.error("Ingresa una contrasena.")
            elif nueva_password != repetir_password:
                st.error("Las contrasenas no coinciden.")
            else:
                correcto, mensaje = registrar_usuario(
                    nuevo_usuario, nueva_password, nuevo_email
                )
                if correcto:
                    st.success(mensaje)
                else:
                    st.error(mensaje)


def cerrar_sesion():
    st.session_state.autenticado = False
    st.session_state.usuario = ""
    st.session_state.password = ""

    try:
        cookie_manager.delete("chess_usuario")
    except Exception:
        pass

    st.rerun()


# ============================================================
# VISTA PRINCIPAL
# ============================================================


def vista_principal():
    with st.sidebar:
        st.markdown("### CHESS ERP")
        st.markdown(f"Usuario: **{st.session_state.usuario}**")
        st.divider()

        if st.button("Cerrar Sesion", use_container_width=True):
            cerrar_sesion()

        st.divider()
        st.markdown(
            """
            **Gestor de Autorizacion**

            Procesamiento y autorizacion directa
            via API HTTP.
            """
        )

    st.markdown(
        '<div class="titulo-principal">Gestor de Autorizacion CHESS ERP</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="subtitulo">Procesamiento y autorizacion automatica de solicitudes</div>',
        unsafe_allow_html=True,
    )

    # Mensaje
    st.subheader("Mensaje de autorizacion")
    mensaje = st.text_area(
        "Pega aqui el mensaje recibido:",
        value=st.session_state.mensaje,
        height=180,
        key="mensaje_autorizacion",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Procesar mensaje", type="primary", use_container_width=True
        ):
            if not mensaje.strip():
                st.warning("Ingresa un mensaje.")
            else:
                extraer_y_actualizar(mensaje)
                st.success("Datos extraidos correctamente.")
                st.rerun()

    with col2:

        def limpiar_todo():
            st.session_state.mensaje_autorizacion = ""
            st.session_state.mensaje = ""
            st.session_state.campo_operador = ""
            st.session_state.campo_ticket = ""
            st.session_state.campo_url = ""
            st.session_state.campo_motivo = ""
            st.session_state.in_dom = ""
            st.session_state.in_op = ""
            st.session_state.in_tick = ""
            st.session_state.in_mot = ""

        st.button(
            "Limpiar", use_container_width=True, on_click=limpiar_todo
        )

    # Datos Detectados
    st.subheader("Datos detectados")
    col1, col2 = st.columns(2)

    with col1:
        operador = st.text_input("Operador", key="campo_operador")
        ticket = st.text_input("Ticket", key="campo_ticket")

    with col2:
        url = st.text_input("URL", key="campo_url")
        motivo = st.text_area("Motivo", height=100, key="campo_motivo")

    # Sincronizar estado auxiliar
    st.session_state.in_op = operador
    st.session_state.in_tick = ticket
    st.session_state.in_dom = url
    st.session_state.in_mot = motivo

    datos_completos = bool(operador.strip() and url.strip() and motivo.strip())

    if datos_completos:
        st.markdown(
            '<div class="estado-ok">Datos suficientes para ejecutar la autorizacion.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="estado-warning">Faltan datos para ejecutar la autorizacion. Verifica operador, URL y motivo.</div>',
            unsafe_allow_html=True,
        )

    # Autorizacion
    st.subheader("Autorizacion")
    col1, col2 = st.columns(2)

    with col1:
        ejecutar = st.button(
            "AUTORIZAR",
            type="primary",
            use_container_width=True,
            disabled=not datos_completos,
        )

    with col2:
        verificar = st.button(
            "Verificar autorizacion reciente",
            use_container_width=True,
            disabled=not bool(url.strip()),
        )

    if verificar:
        reciente = buscar_autorizacion_reciente(url)
        if reciente:
            fecha = reciente.get("created_at", "")
            operador_anterior = reciente.get("operador", "")
            motivo_anterior = reciente.get("motivo", "")
            st.warning(
                "Se encontro una autorizacion reciente para este dominio.\n\n"
                f"Operador: {operador_anterior}\n\nMotivo: {motivo_anterior}\n\nFecha: {fecha}"
            )
            st.session_state.forzar_ejecucion = True
        else:
            st.success(
                "No se encontraron autorizaciones recientes para este dominio."
            )

    if ejecutar:
        reciente = buscar_autorizacion_reciente(url)
        if reciente and not st.session_state.forzar_ejecucion:
            st.warning(
                "Ya existe una autorizacion reciente para este dominio."
            )
            st.info(
                "Si necesitas realizarla igualmente, verifica la informacion y vuelve a ejecutar."
            )
        else:
            with st.spinner("Ejecutando autorizacion en CHESS ERP..."):
                correcto, log = automatizar_web(
                    url=url,
                    usuario=st.session_state.usuario,
                    password=st.session_state.password,
                    operador=operador,
                    detalle=motivo,
                )

            if correcto:
                st.success("Autorizacion ejecutada correctamente.")
                st.link_button(
                    "Abrir ERP para validar acceso",
                    normalizar_url(url),
                    type="primary",
                    use_container_width=True,
                )
            else:
                st.error("La autorizacion no pudo ejecutarse.")

            st.session_state.forzar_ejecucion = False

    # Estado
    st.subheader("Estado de Ejecucion")
    if st.session_state.log_ejecucion:
        log_texto = "\n".join(st.session_state.log_ejecucion)
        st.code(log_texto, language="bash")
    else:
        st.info("Todavia no se ejecuto ninguna automatizacion.")

    # Historial
    st.subheader("Historial de autorizaciones")
    if supabase is not None:
        try:
            resultado = (
                supabase.table("historial_autorizaciones")
                .select("*")
                .order("created_at", desc=True)
                .limit(50)
                .execute()
            )

            if resultado.data:
                import pandas as pd

                df = pd.DataFrame(resultado.data)
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No hay autorizaciones registradas.")
        except Exception as e:
            st.warning(f"No se pudo cargar el historial: {e}")


# ============================================================
# ARRANQUE
# ============================================================

if not st.session_state.autenticado:
    vista_login()
else:
    vista_principal()