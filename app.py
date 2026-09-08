import streamlit as st
import extra_streamlit_components as stx

import re
import sys
import json
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from supabase import create_client, Client


# =========================================================
# CONFIGURACIÓN
# =========================================================

st.set_page_config(
    page_title="Gestor de Autorización CHESS ERP",
    page_icon="🔑",
    layout="centered"
)

st.markdown(
    """
    <style>
        .main {
            background-color: #f8fafc;
        }

        .stButton > button {
            border-radius: 8px;
            font-weight: bold;
        }

        .stTextArea textarea {
            font-family: monospace;
        }
    </style>
    """,
    unsafe_allow_html=True
)


# =========================================================
# SUPABASE
# =========================================================

@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


supabase = init_supabase()


# =========================================================
# COOKIE MANAGER
# =========================================================

def get_cookie_manager():
    return stx.CookieManager()


cookie_manager = get_cookie_manager()


# =========================================================
# ESTADOS DE SESIÓN
# =========================================================

ESTADOS_DEFAULT = {
    "autenticado": False,
    "usuario": "",
    "password": "",
    "log_ejecucion": [],

    "txt_mensaje": (
        "Roy Topping, 14 min\n"
        "URL: https://codenoa.chesserp.com/AR467\n"
        "Ticket: #512918\n"
        "Motivo: Gerente que no aparece"
    ),

    "in_dom": "No detectado",
    "in_op": "No detectado",
    "in_tick": "",
    "in_mot": "",

    "ultimo_mensaje_procesado": None,
    "url_autorizada_lista": None,
    "forzar_ejecucion": False
}


for clave, valor in ESTADOS_DEFAULT.items():
    if clave not in st.session_state:
        st.session_state[clave] = valor


# =========================================================
# SESIÓN PERSISTENTE
# =========================================================

session_usr = cookie_manager.get(
    cookie="chess_session_usr"
)

session_pwd = cookie_manager.get(
    cookie="chess_session_pwd"
)


if (
    session_usr
    and session_pwd
    and not st.session_state.autenticado
):

    try:

        res = (
            supabase
            .table("usuarios_app")
            .select("*")
            .or_(
                f"usuario.eq.{session_usr},"
                f"email.eq.{session_usr.lower()}"
            )
            .eq(
                "password",
                session_pwd
            )
            .execute()
        )

        registros = res.data or []

        if registros:

            st.session_state.autenticado = True

            st.session_state.usuario = (
                registros[0]["usuario"]
            )

            st.session_state.password = (
                registros[0]["password"]
            )

    except Exception:
        pass


# =========================================================
# LOG
# =========================================================

def log_msg(
    msg,
    placeholder_log=None,
    estado="INFO"
):

    badges = {
        "OK": "[OK]",
        "ERROR": "[ERROR]",
        "WARN": "[WARN]",
        "INFO": "[INFO]"
    }

    badge = badges.get(
        estado,
        "[INFO]"
    )

    hora = datetime.now().strftime(
        "%H:%M:%S"
    )

    linea = (
        f"[{hora}] {badge} {msg}"
    )

    st.session_state.log_ejecucion.append(
        linea
    )

    if placeholder_log:

        placeholder_log.code(
            "\n".join(
                st.session_state.log_ejecucion
            ),
            language="bash"
        )


# =========================================================
# HISTORIAL SUPABASE
# =========================================================

def registrar_en_historial(
    usuario,
    dominio_ruta,
    operador,
    motivo_final
):

    try:

        supabase.table(
            "historial_autorizaciones"
        ).insert(
            {
                "usuario": usuario,
                "dominio_ruta": dominio_ruta,
                "operador": operador,
                "motivo": motivo_final
            }
        ).execute()

    except Exception as e:

        log_msg(
            f"Error al guardar historial: {e}",
            estado="WARN"
        )


# =========================================================
# PROCESAMIENTO DEL MENSAJE
# =========================================================

def extraer_y_actualizar(
    texto_mensaje
):

    usuario_actual = (
        st.session_state.usuario
    )

    lineas = [
        linea.strip()
        for linea in texto_mensaje.split("\n")
        if linea.strip()
    ]

    primera_linea = (
        lineas[0]
        if lineas
        else ""
    )


    # -----------------------------------------------------
    # OPERADOR
    # -----------------------------------------------------

    if (
        primera_linea.lower().startswith("url:")
        or primera_linea.lower().startswith("http")
    ):

        operador = (
            usuario_actual
            or "No detectado"
        )

    else:

        if "," in primera_linea:

            raw_op = (
                primera_linea
                .split(",")[0]
                .strip()
            )

        else:

            raw_op = re.split(
                r"\d+\s*min|Ahora|Ayer|\d{1,2}:\d{2}",
                primera_linea,
                flags=re.IGNORECASE
            )[0].strip()

        operador = (
            raw_op
            if raw_op
            else "No detectado"
        )


    # -----------------------------------------------------
    # URL
    # -----------------------------------------------------

    pattern_url = (
        r"(?:https?://)?"
        r"(?:"
        r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        r"|"
        r"\d{1,3}(?:\.\d{1,3}){3}"
        r")"
        r"(?::\d+)?"
        r"(?:/[^\s\n]*)?"
    )

    urls_encontradas = re.findall(
        pattern_url,
        texto_mensaje
    )


    if urls_encontradas:

        dominio_ruta = (
            urls_encontradas[0]
            .strip()
            .rstrip("/")
        )

    else:

        dominio_ruta = "No detectado"


    # -----------------------------------------------------
    # TICKET
    # -----------------------------------------------------

    match_ticket = re.search(
        r"(#\d+)",
        texto_mensaje
    )

    ticket = (
        match_ticket.group(1)
        if match_ticket
        else ""
    )


    # -----------------------------------------------------
    # MOTIVO
    # -----------------------------------------------------

    match_motivo = re.search(
        r"motivo:\s*(.*)",
        texto_mensaje,
        re.IGNORECASE
    )


    if match_motivo:

        motivo_raw = (
            match_motivo
            .group(1)
            .strip()
        )

    else:

        resto = []

        for linea in lineas:

            linea_lower = linea.lower()

            if (
                linea == primera_linea
                or linea_lower.startswith("url:")
                or "http://" in linea_lower
                or "https://" in linea_lower
                or "chesserp" in linea_lower
                or re.search(
                    r"\.[a-zA-Z]{2,}",
                    linea
                )
                or re.search(
                    r"^#\d+$",
                    linea
                )
            ):
                continue

            resto.append(linea)

        motivo_raw = (
            " ".join(resto)
            if resto
            else ""
        )


    # -----------------------------------------------------
    # LIMPIEZA FINAL DEL MOTIVO
    # -----------------------------------------------------

    motivo_raw = re.sub(
        r"(?:https?://)?\S+\.\S+",
        "",
        motivo_raw
    ).strip()


    # -----------------------------------------------------
    # ACTUALIZAR ESTADOS
    # -----------------------------------------------------

    st.session_state.in_dom = (
        dominio_ruta
    )

    st.session_state.in_op = (
        operador
    )

    st.session_state.in_tick = (
        ticket
    )

    st.session_state.in_mot = (
        motivo_raw
    )


# =========================================================
# BORRAR DATOS
# =========================================================

def borrar_todo():

    st.session_state.txt_mensaje = ""

    st.session_state.in_dom = (
        "No detectado"
    )

    st.session_state.in_op = (
        "No detectado"
    )

    st.session_state.in_tick = ""
    st.session_state.in_mot = ""

    st.session_state.log_ejecucion = []

    st.session_state.ultimo_mensaje_procesado = (
        None
    )

    st.session_state.url_autorizada_lista = (
        None
    )

    st.session_state.forzar_ejecucion = (
        False
    )


# =========================================================
# VERIFICAR AUTORIZACIÓN RECIENTE
# =========================================================

def buscar_autorizacion_reciente(
    dominio_ruta,
    minutos=10
):

    try:

        res = (
            supabase
            .table("historial_autorizaciones")
            .select(
                "created_at, usuario, operador, dominio_ruta"
            )
            .order(
                "created_at",
                desc=True
            )
            .limit(20)
            .execute()
        )

        registros = res.data or []

        tz_local = ZoneInfo(
            "America/Argentina/Buenos_Aires"
        )

        ahora = datetime.now(
            tz_local
        )


        def limpiar_dominio(valor):

            return (
                (valor or "")
                .lower()
                .replace(
                    "https://",
                    ""
                )
                .replace(
                    "http://",
                    ""
                )
                .strip()
                .rstrip("/")
            )


        dom_limpio = limpiar_dominio(
            dominio_ruta
        )


        for registro in registros:

            dom_reg = limpiar_dominio(
                registro.get(
                    "dominio_ruta"
                )
            )


            if (
                dom_limpio in dom_reg
                or dom_reg in dom_limpio
            ):

                fecha_raw = registro.get(
                    "created_at",
                    ""
                )

                if not fecha_raw:
                    continue

                fecha_dt = (
                    datetime
                    .fromisoformat(
                        fecha_raw.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                    .astimezone(
                        tz_local
                    )
                )

                diferencia_minutos = (
                    ahora - fecha_dt
                ).total_seconds() / 60


                if (
                    0 <= diferencia_minutos <= minutos
                ):

                    return {

                        "activa": True,

                        "hace_minutos": int(
                            diferencia_minutos
                        ),

                        "usuario": registro.get(
                            "usuario",
                            "Desconocido"
                        ),

                        "operador": registro.get(
                            "operador",
                            "Desconocido"
                        ),

                        "fecha": fecha_dt.strftime(
                            "%H:%M:%S"
                        )

                    }


    except Exception as e:

        print(
            f"Error verificando autorización: {e}"
        )


    return {
        "activa": False
    }


# =========================================================
# INSTALAR / VERIFICAR CHROMIUM
# =========================================================

@st.cache_resource
def preparar_chromium():

    try:

        resultado = subprocess.run(

            [
                sys.executable,
                "-m",
                "playwright",
                "install",
                "chromium"
            ],

            capture_output=True,

            text=True,

            timeout=180

        )


        if resultado.returncode == 0:

            return True, ""


        return (
            False,
            resultado.stderr
            or resultado.stdout
            or "Error desconocido"
        )


    except Exception as e:

        return (
            False,
            str(e)
        )


# =========================================================
# WORKER PLAYWRIGHT
# =========================================================

WORKER_PATH = "/tmp/runner_playwright.py"


def asegurar_script_worker():

    script_code = r'''
import sys
import json
import re

from playwright.sync_api import sync_playwright


def run():

    if len(sys.argv) < 2:

        print(
            json.dumps(
                {
                    "success": False,
                    "error": "No se recibieron parámetros"
                }
            )
        )

        return


    params = json.loads(
        sys.argv[1]
    )


    dominio_ruta = params[
        "dominio_ruta"
    ]

    usuario = params[
        "usuario"
    ]

    password = params[
        "password"
    ]

    operador = params[
        "operador"
    ]

    motivo_final = params[
        "motivo_final"
    ]

    texto_mensaje = params[
        "texto_mensaje"
    ]


    # =====================================================
    # CONSTRUIR URL
    # =====================================================

    if (
        dominio_ruta.startswith("http://")
        or dominio_ruta.startswith("https://")
    ):

        url_base = dominio_ruta

    else:

        contiene_puerto = re.search(
            r":\d+",
            dominio_ruta
        )

        es_ip = re.search(
            r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            dominio_ruta
        )


        if (
            "http://" in texto_mensaje.lower()
            or contiene_puerto
            or es_ip
        ):

            url_base = (
                f"http://{dominio_ruta}"
            )

        else:

            url_base = (
                f"https://{dominio_ruta}"
            )


    # =====================================================
    # AUTOMATIZACIÓN
    # =====================================================

    browser = None
    context = None

    try:

        with sync_playwright() as p:

            browser = p.chromium.launch(

                headless=True,

                args=[

                    "--no-sandbox",

                    "--disable-setuid-sandbox",

                    "--disable-dev-shm-usage",

                    "--disable-gpu",

                    "--no-first-run",

                    "--no-zygote",

                    "--ignore-certificate-errors"

                ]

            )


            context = browser.new_context(

                ignore_https_errors=True,

                viewport={
                    "width": 1920,
                    "height": 1080
                }

            )


            page = context.new_page()


            # -------------------------------------------------
            # ABRIR URL BASE
            # -------------------------------------------------

            page.goto(
                url_base,
                timeout=30000,
                wait_until="domcontentloaded"
            )

            page.wait_for_timeout(
                2000
            )


            url_actual = (
                page.url
                .split("#")[0]
                .rstrip("/")
            )


            url_admin = (
                f"{url_actual}/#/admin"
            )


            # -------------------------------------------------
            # ADMIN
            # -------------------------------------------------

            page.goto(

                url_admin,

                timeout=30000,

                wait_until="domcontentloaded"

            )


            page.wait_for_selector(

                "#usuario, input[formcontrolname='usuario']",

                timeout=20000

            )


            # =================================================
            # SCRIPT PARA COMPLETAR CAMPOS
            # =================================================

            script_inyect = """
            ([selector, val]) => {

                var el =
                    document.getElementById(selector)
                    ||
                    document.querySelector(
                        '[formcontrolname="' + selector + '"]'
                    )
                    ||
                    document.querySelector(
                        '[name="' + selector + '"]'
                    );


                if (!el) {

                    var inputs = Array.from(
                        document.querySelectorAll(
                            'input:not([type="hidden"]):not([type="checkbox"]):not([type="button"]), textarea'
                        )
                    );


                    if (
                        selector.toLowerCase()
                        .includes('usuario')
                    ) {

                        el = inputs[0];

                    }


                    else if (
                        selector.toLowerCase()
                        .includes('contrasenia')
                        ||
                        selector.toLowerCase()
                        .includes('password')
                    ) {

                        el =
                            document.querySelector(
                                'input[type="password"]'
                            )
                            ||
                            inputs[1];

                    }


                    else if (
                        selector.toLowerCase()
                        .includes('operador')
                    ) {

                        el =
                            inputs.find(
                                i =>
                                    (i.placeholder || '')
                                    .toLowerCase()
                                    .includes('operador')
                                    ||
                                    (i.id || '')
                                    .toLowerCase()
                                    .includes('operador')
                            )
                            ||
                            inputs[2];

                    }


                    else if (
                        selector.toLowerCase()
                        .includes('detalle')
                        ||
                        selector.toLowerCase()
                        .includes('motivo')
                    ) {

                        el =
                            document.querySelector(
                                'textarea'
                            )
                            ||
                            inputs.find(
                                i =>
                                    (i.placeholder || '')
                                    .toLowerCase()
                                    .includes('motivo')
                                    ||
                                    (i.id || '')
                                    .toLowerCase()
                                    .includes('motivo')
                            )
                            ||
                            inputs[
                                inputs.length - 1
                            ];

                    }

                }


                if (el) {

                    el.removeAttribute(
                        'disabled'
                    );

                    el.removeAttribute(
                        'readonly'
                    );

                    el.focus();

                    el.value = val;


                    el.dispatchEvent(
                        new Event(
                            'input',
                            {
                                bubbles: true
                            }
                        )
                    );


                    el.dispatchEvent(
                        new Event(
                            'change',
                            {
                                bubbles: true
                            }
                        )
                    );


                    el.dispatchEvent(
                        new Event(
                            'blur',
                            {
                                bubbles: true
                            }
                        )
                    );


                    return true;

                }


                return false;

            }
            """


            # -------------------------------------------------
            # COMPLETAR USUARIO
            # -------------------------------------------------

            page.evaluate(

                script_inyect,

                [
                    "usuario",
                    usuario
                ]

            )

            page.wait_for_timeout(
                400
            )


            # -------------------------------------------------
            # COMPLETAR CONTRASEÑA
            # -------------------------------------------------

            page.evaluate(

                script_inyect,

                [
                    "contrasenia",
                    password
                ]

            )

            page.wait_for_timeout(
                800
            )


            # -------------------------------------------------
            # COMPLETAR OPERADOR
            # -------------------------------------------------

            page.evaluate(

                script_inyect,

                [
                    "operadorAutorizado",
                    operador
                ]

            )

            page.wait_for_timeout(
                400
            )


            # -------------------------------------------------
            # COMPLETAR MOTIVO
            # -------------------------------------------------

            page.evaluate(

                script_inyect,

                [
                    "detalle",
                    motivo_final
                ]

            )

            page.wait_for_timeout(
                800
            )


            # -------------------------------------------------
            # PERMITIR ACCESO
            # -------------------------------------------------

            resultado_permitir = page.evaluate(

                """
                () => {

                    var btn =
                        document.querySelector(
                            'button[label="PERMITIR ACCESO"]'
                        )
                        ||
                        document.querySelector(
                            'button.login-button'
                        )
                        ||
                        Array.from(
                            document.querySelectorAll(
                                'button'
                            )
                        ).find(
                            b =>
                                (b.innerText || '')
                                .toUpperCase()
                                .includes(
                                    'PERMITIR'
                                )
                        );


                    if (btn) {

                        btn.removeAttribute(
                            'disabled'
                        );

                        btn.classList.remove(
                            'p-disabled'
                        );

                        btn.click();

                        return true;

                    }


                    return false;

                }
                """

            )


            if not resultado_permitir:

                raise Exception(
                    "No se encontró el botón PERMITIR ACCESO."
                )


            page.wait_for_timeout(
                3000
            )


            # -------------------------------------------------
            # ESPERAR LOGIN
            # -------------------------------------------------

            page.wait_for_selector(

                "#usuario, input[formcontrolname='usuario']",

                timeout=15000

            )


            # -------------------------------------------------
            # COMPLETAR USUARIO NUEVAMENTE
            # -------------------------------------------------

            page.evaluate(

                script_inyect,

                [
                    "usuario",
                    usuario
                ]

            )

            page.wait_for_timeout(
                400
            )


            # -------------------------------------------------
            # COMPLETAR CONTRASEÑA NUEVAMENTE
            # -------------------------------------------------

            page.evaluate(

                script_inyect,

                [
                    "contrasenia",
                    password
                ]

            )

            page.wait_for_timeout(
                800
            )


            # -------------------------------------------------
            # LOGIN
            # -------------------------------------------------

            resultado_login = page.evaluate(

                """
                () => {

                    var inputPass =
                        document.getElementById(
                            'contrasenia'
                        )
                        ||
                        document.querySelector(
                            'input[type="password"]'
                        );


                    var form =
                        inputPass
                        ? inputPass.closest(
                            'form'
                        )
                        : null;


                    if (form) {

                        form.dispatchEvent(
                            new Event(
                                'submit',
                                {
                                    cancelable: true,
                                    bubbles: true
                                }
                            )
                        );

                        return true;

                    }


                    var btnLogin =
                        document.querySelector(
                            'button[label="INICIAR SESIÓN"]'
                        )
                        ||
                        document.querySelector(
                            'button.login-button'
                        )
                        ||
                        Array.from(
                            document.querySelectorAll(
                                'button'
                            )
                        ).find(
                            b =>
                                (b.innerText || '')
                                .toUpperCase()
                                .includes(
                                    'INICIAR'
                                )
                        );


                    if (btnLogin) {

                        btnLogin.removeAttribute(
                            'disabled'
                        );

                        btnLogin.click();

                        return true;

                    }


                    return false;

                }
                """

            )


            if not resultado_login:

                raise Exception(
                    "No se encontró el formulario o botón de inicio de sesión."
                )


            page.keyboard.press(
                "Enter"
            )


            page.wait_for_timeout(
                4000
            )


            # -------------------------------------------------
            # CERRAR NAVEGADOR
            # -------------------------------------------------

            if context:

                context.close()

            if browser:

                browser.close()


            print(
                json.dumps(
                    {
                        "success": True,
                        "url_actual": url_actual
                    }
                )
            )


    except Exception as e:

        try:

            if context:
                context.close()

        except Exception:
            pass


        try:

            if browser:
                browser.close()

        except Exception:
            pass


        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(e)
                }
            )
        )


if __name__ == "__main__":

    run()
'''


    with open(
        WORKER_PATH,
        "w",
        encoding="utf-8"
    ) as archivo:

        archivo.write(
            script_code
        )


# =========================================================
# AUTOMATIZACIÓN WEB
# =========================================================

def automatizar_web(

    dominio_ruta,

    usuario,

    password,

    operador,

    motivo_final,

    texto_mensaje,

    placeholder_log

):

    st.session_state.log_ejecucion = []


    # -----------------------------------------------------
    # PREPARAR CHROMIUM
    # -----------------------------------------------------

    log_msg(

        "Verificando disponibilidad de Chromium...",

        placeholder_log,

        "INFO"

    )


    chromium_ok, chromium_error = (
        preparar_chromium()
    )


    if not chromium_ok:

        log_msg(

            f"No se pudo preparar Chromium: {chromium_error}",

            placeholder_log,

            "ERROR"

        )


        return (
            False,
            f"No se pudo preparar Chromium: {chromium_error}",
            False,
            None
        )


    log_msg(

        "Chromium disponible.",

        placeholder_log,

        "OK"

    )


    # -----------------------------------------------------
    # CREAR WORKER
    # -----------------------------------------------------

    asegurar_script_worker()


    params = {

        "dominio_ruta": dominio_ruta,

        "usuario": usuario,

        "password": password,

        "operador": operador,

        "motivo_final": motivo_final,

        "texto_mensaje": texto_mensaje

    }


    log_msg(

        "Iniciando subproceso aislado de automatización...",

        placeholder_log,

        "INFO"

    )


    try:

        resultado = subprocess.run(

            [

                sys.executable,

                WORKER_PATH,

                json.dumps(params)

            ],

            capture_output=True,

            text=True,

            check=True,

            timeout=90

        )


        salida_raw = (
            resultado.stdout.strip()
        )


        lineas_salida = [

            linea

            for linea in salida_raw.split("\n")

            if linea.strip().startswith("{")

        ]


        if lineas_salida:

            try:

                data = json.loads(
                    lineas_salida[-1]
                )

            except json.JSONDecodeError:

                log_msg(

                    f"Respuesta no válida del worker: {salida_raw}",

                    placeholder_log,

                    "ERROR"

                )

                return (
                    False,
                    "El worker devolvió una respuesta no válida.",
                    False,
                    None
                )


            if data.get("success"):

                log_msg(

                    "ACCESO AUTORIZADO Y SESIÓN INICIADA CORRECTAMENTE EN CHESS ERP.",

                    placeholder_log,

                    "OK"

                )


                registrar_en_historial(

                    usuario,

                    dominio_ruta,

                    operador,

                    motivo_final

                )


                return (

                    True,

                    "Acceso e inicio de sesión completados correctamente",

                    False,

                    data.get("url_actual")

                )


            else:

                err_msg = data.get(

                    "error",

                    "Error desconocido en worker"

                )


                log_msg(

                    f"ERROR EN WORKER: {err_msg}",

                    placeholder_log,

                    "ERROR"

                )


                return (

                    False,

                    err_msg,

                    False,

                    None

                )


        else:

            log_msg(

                f"Respuesta inesperada del worker: {salida_raw}",

                placeholder_log,

                "ERROR"

            )


            return (

                False,

                "Salida no válida del worker de Playwright",

                False,

                None

            )


    except subprocess.TimeoutExpired:

        log_msg(

            "La automatización superó el tiempo máximo de espera.",

            placeholder_log,

            "ERROR"

        )


        return (

            False,

            "Tiempo máximo de automatización excedido.",

            False,

            None

        )


    except subprocess.CalledProcessError as e:

        err_out = (

            e.stderr
            or e.stdout
            or "Error desconocido"
        )


        log_msg(

            f"ERROR EN SUBPROCESO: {err_out.strip()}",

            placeholder_log,

            "ERROR"

        )


        return (

            False,

            err_out.strip(),

            False,

            None

        )


    except Exception as e:

        log_msg(

            f"ERROR EN AUTOMATIZACIÓN: {e}",

            placeholder_log,

            "ERROR"

        )


        return (

            False,

            str(e),

            False,

            None

        )


# =========================================================
# LOGIN
# =========================================================

def vista_login():

    st.markdown(

        "<h2 style='text-align: center;'>"
        "Acceso CHESS ERP"
        "</h2>",

        unsafe_allow_html=True

    )


    st.markdown("---")


    opcion = st.radio(

        "Acción:",

        [
            "Iniciar Sesión",
            "Registrar Usuario"
        ],

        horizontal=True

    )


    with st.form("auth_form"):

        usr_input = st.text_input(

            "Usuario ERP",

            value=(
                session_usr
                if session_usr
                else ""
            ),

            key="login_usr_input"

        )


        pwd = st.text_input(

            "Contraseña ERP",

            type="password",

            value=(
                session_pwd
                if session_pwd
                else ""
            ),

            key="login_pwd_input"

        )


        email_input = None


        if opcion == "Registrar Usuario":

            email_input = st.text_input(

                "Correo electrónico",

                key="login_email_input"

            )


        recordar_credenciales = st.checkbox(

            "Recordar credenciales y mantener sesión activa",

            value=True

        )


        submit = st.form_submit_button(

            "CONTINUAR",

            width="stretch"

        )


        if submit:

            if not usr_input or not pwd:

                st.warning(
                    "Por favor complete usuario y contraseña."
                )

                return


            usuario_limpio = (
                usr_input.strip()
            )


            # =================================================
            # LOGIN
            # =================================================

            if opcion == "Iniciar Sesión":

                with st.spinner(
                    "Verificando credenciales..."
                ):

                    try:

                        res = (

                            supabase

                            .table("usuarios_app")

                            .select("*")

                            .or_(

                                f"usuario.eq.{usuario_limpio},"

                                f"email.eq.{usuario_limpio.lower()}"

                            )

                            .eq(
                                "password",
                                pwd
                            )

                            .execute()

                        )


                        registros = (
                            res.data or []
                        )


                        if registros:

                            st.session_state.autenticado = (
                                True
                            )

                            st.session_state.usuario = (
                                registros[0]["usuario"]
                            )

                            st.session_state.password = (
                                registros[0]["password"]
                            )


                            # ---------------------------------
                            # COOKIES
                            # ---------------------------------

                            if recordar_credenciales:

                                exp_date = (
                                    datetime.now()
                                    + timedelta(days=30)
                                )


                                try:

                                    cookie_manager.set(

                                        "chess_session_usr",

                                        usuario_limpio,

                                        key="set_usr",

                                        expires_at=exp_date

                                    )


                                    cookie_manager.set(

                                        "chess_session_pwd",

                                        pwd,

                                        key="set_pwd",

                                        expires_at=exp_date

                                    )

                                except Exception:

                                    pass


                            else:

                                try:

                                    cookie_manager.delete(

                                        "chess_session_usr",

                                        key="del_usr"

                                    )

                                except Exception:

                                    pass


                                try:

                                    cookie_manager.delete(

                                        "chess_session_pwd",

                                        key="del_pwd"

                                    )

                                except Exception:

                                    pass


                            st.rerun()


                        else:

                            st.error(

                                "Usuario, email o contraseña incorrectos."

                            )


                    except Exception as e:

                        st.error(

                            f"Error al consultar la base de datos: {e}"

                        )


            # =================================================
            # REGISTRO
            # =================================================

            elif opcion == "Registrar Usuario":

                email_final = (

                    email_input.strip().lower()

                    if email_input

                    else (
                        f"{usuario_limpio.lower()}"
                        "@chesserp.com"
                    )

                )


                with st.spinner(
                    "Registrando usuario..."
                ):

                    try:

                        supabase.table(
                            "usuarios_app"
                        ).insert(

                            {

                                "usuario":
                                    usuario_limpio,

                                "password":
                                    pwd,

                                "email":
                                    email_final

                            }

                        ).execute()


                        st.success(

                            f"Usuario '{usuario_limpio}' "
                            "registrado correctamente. "
                            "Ya puede iniciar sesión."

                        )


                    except Exception as e:

                        st.error(

                            f"Error al registrar usuario: {e}"

                        )


# =========================================================
# PANTALLA PRINCIPAL
# =========================================================

def vista_principal():

    # =====================================================
    # SIDEBAR
    # =====================================================

    st.sidebar.title(
        "Menú"
    )


    st.sidebar.write(

        f"**Usuario activo:** "
        f"`{st.session_state.usuario}`"

    )


    if st.sidebar.button(

        "🚪 Cerrar Sesión",

        width="stretch"

    ):

        st.session_state.autenticado = False

        st.session_state.usuario = ""

        st.session_state.password = ""


        try:

            cookie_manager.delete(

                "chess_session_usr",

                key="logout_usr"

            )

        except Exception:

            pass


        try:

            cookie_manager.delete(

                "chess_session_pwd",

                key="logout_pwd"

            )

        except Exception:

            pass


        borrar_todo()

        st.rerun()


    # =====================================================
    # TÍTULO
    # =====================================================

    st.title(
        "Gestor de Autorización CHESS ERP"
    )


    # =====================================================
    # MENSAJE
    # =====================================================

    txt_mensaje = st.text_area(

        "Pegue el mensaje de solicitud:",

        key="txt_mensaje",

        height=120

    )


    col_proc, col_borr = st.columns(
        [2, 1]
    )


    with col_proc:

        btn_procesar = st.button(

            "⚡ PROCESAR MENSAJE",

            width="stretch"

        )


    with col_borr:

        st.button(

            "🗑️ Borrar",

            on_click=borrar_todo,

            width="stretch"

        )


    if btn_procesar:

        if txt_mensaje.strip():

            extraer_y_actualizar(
                txt_mensaje
            )


            st.session_state.ultimo_mensaje_procesado = (
                txt_mensaje
            )

            st.session_state.url_autorizada_lista = (
                None
            )


            st.rerun()

        else:

            st.warning(

                "Por favor ingrese o pegue un mensaje antes de procesar."

            )


    # =====================================================
    # PROCESAMIENTO INICIAL
    # =====================================================

    if (

        st.session_state.ultimo_mensaje_procesado
        is None

    ):

        extraer_y_actualizar(
            txt_mensaje
        )

        st.session_state.ultimo_mensaje_procesado = (
            txt_mensaje
        )


    st.markdown("---")


    # =====================================================
    # DATOS DETECTADOS
    # =====================================================

    st.markdown(
        "### Datos Detectados (Editables)"
    )


    st.caption(
        "Verifique o edite los campos manualmente antes de autorizar."
    )


    col1, col2 = st.columns(2)


    with col1:

        dominio_final = st.text_input(

            "Servidor / Ruta URL:",

            key="in_dom"

        )


        operador_final = st.text_input(

            "Operador Autorizado:",

            key="in_op"

        )


    with col2:

        ticket_final = st.text_input(

            "No. Ticket:",

            key="in_tick"

        )


        motivo_base = st.text_input(

            "Motivo:",

            key="in_mot"

        )


    # =====================================================
    # MOTIVO FINAL
    # =====================================================

    if (

        ticket_final

        and

        not motivo_base.startswith(
            ticket_final
        )

    ):

        motivo_ejecucion = (

            f"{ticket_final} - {motivo_base}"

            if motivo_base

            else ticket_final

        )

    else:

        motivo_ejecucion = motivo_base


    st.markdown("---")


    # =====================================================
    # AUTORIZAR
    # =====================================================

    btn_permitir = st.button(

        "PERMITIR ACCESO EN CHESS ERP",

        type="primary",

        width="stretch"

    )


    if st.session_state.url_autorizada_lista:

        st.link_button(

            "🔗 Abrir ERP Habilitado en la Web",

            st.session_state.url_autorizada_lista,

            width="stretch"

        )


    sesion_activa_detectada = False


    # =====================================================
    # VERIFICAR SESIÓN PREVIA
    # =====================================================

    if (

        btn_permitir

        and dominio_final

        and dominio_final != "No detectado"

    ):

        sesion_previa = (

            buscar_autorizacion_reciente(

                dominio_final,

                minutos=10

            )

        )


        if (

            sesion_previa["activa"]

            and

            not st.session_state.get(
                "forzar_ejecucion",
                False
            )

        ):

            sesion_activa_detectada = True


            st.warning(

                f"⚠️ **SESIÓN ACTIVA DETECTADA:** "
                f"Este entorno (`{dominio_final}`) "
                f"ya fue autorizado hace "
                f"**{sesion_previa['hace_minutos']} min** "
                f"(a las {sesion_previa['fecha']}) "
                f"por **{sesion_previa['usuario']}** "
                f"para el operador "
                f"**{sesion_previa['operador']}**."

            )


            col_reutilizar, col_forzar = (
                st.columns(2)
            )


            with col_reutilizar:

                url_directa = (

                    dominio_final

                    if dominio_final.startswith(
                        "http"
                    )

                    else (
                        f"https://{dominio_final}"
                    )

                )


                st.link_button(

                    "🔗 Ir directamente al ERP",

                    url_directa,

                    width="stretch"

                )


            with col_forzar:

                if st.button(

                    "⚡ Re-autorizar de todos modos",

                    width="stretch"

                ):

                    st.session_state[
                        "forzar_ejecucion"
                    ] = True

                    st.rerun()


    st.markdown("---")


    # =====================================================
    # LOG
    # =====================================================

    st.markdown(
        "#### Estado de Ejecución"
    )


    placeholder_log = st.empty()


    if st.session_state.log_ejecucion:

        placeholder_log.code(

            "\n".join(
                st.session_state.log_ejecucion
            ),

            language="bash"

        )


    # =====================================================
    # EJECUTAR AUTOMATIZACIÓN
    # =====================================================

    if (

        btn_permitir

        and

        not sesion_activa_detectada

    ):

        if (

            not dominio_final

            or dominio_final == "No detectado"

        ):

            st.error(

                "Por favor ingrese un Servidor / Ruta URL válido."

            )

        else:

            st.session_state[
                "forzar_ejecucion"
            ] = False


            exito, msg, advertencia, url_resuelta = (

                automatizar_web(

                    dominio_final,

                    st.session_state.usuario,

                    st.session_state.password,

                    operador_final,

                    motivo_ejecucion,

                    txt_mensaje,

                    placeholder_log

                )

            )


            if exito:

                st.session_state.url_autorizada_lista = (

                    url_resuelta

                    or (

                        dominio_final

                        if dominio_final.startswith(
                            "http"
                        )

                        else (
                            f"https://{dominio_final}"
                        )

                    )

                )


                if not advertencia:

                    st.success(
                        msg
                    )

                else:

                    st.warning(
                        msg
                    )


                st.rerun()


            else:

                st.session_state.url_autorizada_lista = (
                    None
                )

                st.error(
                    f"Error: {msg}"
                )


    st.markdown("---")


    # =====================================================
    # HISTORIAL
    # =====================================================

    with st.expander(
        "Ver Historial de Autorizaciones"
    ):

        col_hist_title, col_hist_btn = (
            st.columns([3, 1])
        )


        with col_hist_title:

            st.caption(

                "Últimas autorizaciones registradas en la plataforma:"

            )


        with col_hist_btn:

            if st.button(

                "🔄 Actualizar",

                key="btn_refresh_hist",

                width="stretch"

            ):

                st.rerun()


        try:

            res = (

                supabase

                .table(
                    "historial_autorizaciones"
                )

                .select(
                    "created_at, operador, motivo, usuario, dominio_ruta"
                )

                .order(
                    "created_at",
                    desc=True
                )

                .limit(100)

                .execute()

            )


            registros = res.data or []


            if registros:

                tz_local = ZoneInfo(

                    "America/Argentina/Buenos_Aires"

                )


                datos_tabla = []


                for registro in registros:

                    fecha_raw = registro.get(

                        "created_at",

                        ""

                    )


                    try:

                        fecha_dt = (

                            datetime

                            .fromisoformat(

                                fecha_raw.replace(

                                    "Z",

                                    "+00:00"

                                )

                            )

                        )


                        fecha_local = (

                            fecha_dt

                            .astimezone(
                                tz_local
                            )

                        )


                        fecha_fmt = (

                            fecha_local.strftime(

                                "%d/%m/%Y %H:%M"

                            )

                        )


                    except Exception:

                        fecha_fmt = (
                            fecha_raw[:16]
                            if fecha_raw
                            else "-"
                        )


                    motivo_completo = (

                        registro.get(
                            "motivo",
                            ""
                        )

                        or "-"

                    )


                    match_ticket = re.search(

                        r"(#\d+)",

                        motivo_completo

                    )


                    if match_ticket:

                        id_ticket = (
                            match_ticket.group(1)
                        )


                        motivo_limpio = re.sub(

                            r"^#\d+\s*[-–—]?\s*",

                            "",

                            motivo_completo

                        ).strip()


                        motivo_limpio = (

                            motivo_limpio

                            if motivo_limpio

                            else "-"

                        )


                    else:

                        id_ticket = "-"

                        motivo_limpio = (
                            motivo_completo
                        )


                    datos_tabla.append(

                        {

                            "Fecha / Hora":
                                fecha_fmt,

                            "Operador Autorizado":
                                registro.get(
                                    "operador",
                                    "-"
                                ),

                            "Id Ticket":
                                id_ticket,

                            "Motivo":
                                motivo_limpio,

                            "Usuario Aprobador ERP":
                                registro.get(
                                    "usuario",
                                    "-"
                                ),

                            "Servidor / Ruta":
                                registro.get(
                                    "dominio_ruta",
                                    "-"
                                )

                        }

                    )


                st.dataframe(

                    datos_tabla,

                    width="stretch",

                    hide_index=True,

                    column_config={

                        "Fecha / Hora":

                            st.column_config.TextColumn(

                                "Fecha / Hora",

                                width="medium"

                            ),


                        "Operador Autorizado":

                            st.column_config.TextColumn(

                                "Operador Autorizado",

                                width="medium"

                            ),


                        "Id Ticket":

                            st.column_config.TextColumn(

                                "Id Ticket",

                                width="small"

                            ),


                        "Motivo":

                            st.column_config.TextColumn(

                                "Motivo",

                                width="large"

                            ),


                        "Usuario Aprobador ERP":

                            st.column_config.TextColumn(

                                "Usuario Aprobador ERP",

                                width="small"

                            ),


                        "Servidor / Ruta":

                            st.column_config.TextColumn(

                                "Servidor / Ruta",

                                width="medium"

                            )

                    }

                )


            else:

                st.info(
                    "Aún no hay registros en el historial."
                )


        except Exception as e:

            st.warning(

                f"No se pudo cargar el historial: {e}"

            )


# =========================================================
# EJECUCIÓN PRINCIPAL
# =========================================================

if not st.session_state.autenticado:

    vista_login()

else:

    vista_principal()