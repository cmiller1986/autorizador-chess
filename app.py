import streamlit as st
import extra_streamlit_components as stx

import re
import sys
import json
import subprocess
import shutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from supabase import create_client, Client


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Gestor de Autorización CHESS ERP",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded"
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
    unsafe_allow_html=True
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

cookie_manager = stx.CookieManager(
    key="chess_cookie_manager"
)


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

    "mensaje": """
Roy Topping, 14 min
URL: https://codenoa.chesserp.com/AR467
Ticket: #512918
Motivo: Gerente que no aparece
""".strip()
}

for clave, valor in valores_iniciales.items():
    if clave not in st.session_state:
        st.session_state[clave] = valor


# ============================================================
# UTILIDADES
# ============================================================

def ahora_argentina():
    return datetime.now(
        ZoneInfo("America/Argentina/Buenos_Aires")
    )


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

    match = re.search(
        r"https?://([^/]+)",
        url,
        re.IGNORECASE
    )

    if match:
        return match.group(1).lower()

    return ""


# ============================================================
# SUPABASE - HISTORIAL
# ============================================================

def registrar_en_historial(
    operador,
    url,
    ticket,
    motivo,
    usuario_app=None
):
    if supabase is None:
        return False

    try:
        datos = {
            "operador": operador,
            "url": url,
            "ticket": ticket,
            "motivo": motivo,
            "usuario_app": usuario_app or st.session_state.get(
                "usuario",
                ""
            ),
            "fecha_hora": ahora_argentina().isoformat()
        }

        resultado = (
            supabase
            .table("historial_autorizaciones")
            .insert(datos)
            .execute()
        )

        return bool(resultado.data)

    except Exception as e:
        agregar_log(
            f"No se pudo registrar historial: {e}",
            "WARNING"
        )
        return False


def buscar_autorizacion_reciente(url):
    """
    Busca una autorización reciente sobre el mismo dominio.
    Se utiliza para evitar autorizaciones duplicadas accidentales.
    """

    if supabase is None:
        return None

    try:
        resultado = (
            supabase
            .table("historial_autorizaciones")
            .select("*")
            .order("fecha_hora", desc=True)
            .limit(20)
            .execute()
        )

        if not resultado.data:
            return None

        dominio_actual = obtener_dominio(url)

        ahora = ahora_argentina()

        for registro in resultado.data:

            url_registro = registro.get("url", "")
            dominio_registro = obtener_dominio(url_registro)

            if not dominio_actual:
                continue

            if dominio_actual != dominio_registro:
                continue

            fecha_texto = registro.get("fecha_hora")

            if not fecha_texto:
                continue

            try:
                fecha_registro = datetime.fromisoformat(
                    fecha_texto.replace("Z", "+00:00")
                )

                if fecha_registro.tzinfo is None:
                    fecha_registro = fecha_registro.replace(
                        tzinfo=ZoneInfo(
                            "America/Argentina/Buenos_Aires"
                        )
                    )

                diferencia = ahora - fecha_registro

                if diferencia <= timedelta(minutes=10):
                    return registro

            except Exception:
                continue

        return None

    except Exception as e:
        agregar_log(
            f"Error consultando historial: {e}",
            "WARNING"
        )
        return None


# ============================================================
# EXTRACCIÓN DEL MENSAJE
# ============================================================

def extraer_y_actualizar(mensaje):
    """
    Extrae:
      - Operador
      - URL
      - Ticket
      - Motivo
    """

    if not mensaje:
        return False

    texto = mensaje.strip()

    # --------------------------------------------------------
    # OPERADOR
    # --------------------------------------------------------

    operador = ""

    patrones_operador = [
        r"^\s*([^,\n]+),\s*\d+\s*(?:min|minutos|mins?)?",
        r"^\s*([^\n]+),\s*\d+\s*(?:min|minutos|mins?)?"
    ]

    for patron in patrones_operador:
        match = re.search(
            patron,
            texto,
            re.IGNORECASE
        )

        if match:
            operador = match.group(1).strip()
            break

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    url = ""

    match_url = re.search(
        r"(https?://[^\s]+)",
        texto,
        re.IGNORECASE
    )

    if match_url:
        url = match_url.group(1).strip()

        # Quitar caracteres finales habituales
        url = url.rstrip(".,;")

    # --------------------------------------------------------
    # TICKET
    # --------------------------------------------------------

    ticket = ""

    match_ticket = re.search(
        r"Ticket\s*:\s*#?\s*(\d+)",
        texto,
        re.IGNORECASE
    )

    if match_ticket:
        ticket = f"#{match_ticket.group(1)}"

    # --------------------------------------------------------
    # MOTIVO
    # --------------------------------------------------------

    motivo = ""

    match_motivo = re.search(
        r"Motivo\s*:\s*(.+?)(?=\n|$)",
        texto,
        re.IGNORECASE
    )

    if match_motivo:
        motivo = match_motivo.group(1).strip()

    # --------------------------------------------------------
    # ACTUALIZAR SESSION STATE
    # --------------------------------------------------------

    st.session_state.in_dom = operador
    st.session_state.in_op = operador
    st.session_state.in_tick = ticket
    st.session_state.in_mot = motivo

    st.session_state.ultimo_mensaje_procesado = texto

    st.session_state.url_autorizada_lista = bool(
        url and operador
    )

    return True


# ============================================================
# DETECCIÓN DE NAVEGADORES
# ============================================================

def detectar_navegadores_sistema():
    """
    Busca navegadores instalados en el sistema.

    Orden de prioridad:
        1. chromium
        2. chromium-browser
        3. google-chrome
        4. google-chrome-stable
    """

    candidatos = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]

    encontrados = []

    for nombre in candidatos:

        ruta = shutil.which(nombre)

        if ruta:
            encontrados.append({
                "nombre": nombre,
                "ruta": ruta
            })

    return encontrados


def obtener_version_navegador(ruta):
    """
    Intenta obtener la versión del navegador del sistema.
    """

    try:
        resultado = subprocess.run(
            [ruta, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )

        salida = (
            resultado.stdout.strip()
            or resultado.stderr.strip()
        )

        return salida

    except Exception as e:
        return f"No se pudo obtener versión: {e}"


# ============================================================
# PLAYWRIGHT - PREPARAR CHROMIUM
# ============================================================

@st.cache_resource
def preparar_chromium():

    agregar_log(
        "Verificando disponibilidad de Chromium..."
    )

    # --------------------------------------------------------
    # PRIMERO: NAVEGADORES DEL SISTEMA
    # --------------------------------------------------------

    navegadores = detectar_navegadores_sistema()

    if navegadores:

        for navegador in navegadores:

            version = obtener_version_navegador(
                navegador["ruta"]
            )

            agregar_log(
                f"Navegador del sistema encontrado: "
                f"{navegador['nombre']} "
                f"({navegador['ruta']}) - {version}",
                "OK"
            )

        agregar_log(
            "Se priorizará el navegador del sistema.",
            "OK"
        )

    else:

        agregar_log(
            "No se encontró Chromium/Chrome del sistema."
        )

        # ----------------------------------------------------
        # SEGUNDO: CHROMIUM DE PLAYWRIGHT
        # ----------------------------------------------------

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

                agregar_log(
                    "Chromium de Playwright disponible.",
                    "OK"
                )

            else:

                error = (
                    resultado.stderr
                    or resultado.stdout
                    or "Error desconocido"
                )

                agregar_log(
                    f"Error instalando Chromium de Playwright: "
                    f"{error}",
                    "ERROR"
                )

                return False, navegadores

        except Exception as e:

            agregar_log(
                f"Error preparando Chromium: {e}",
                "ERROR"
            )

            return False, navegadores

    return True, navegadores


# ============================================================
# WORKER PLAYWRIGHT
# ============================================================

def crear_worker_playwright():

    worker_code = r'''
import sys
import json
import shutil
import traceback
from playwright.sync_api import sync_playwright


def detectar_navegadores():

    candidatos = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]

    encontrados = []

    for nombre in candidatos:

        ruta = shutil.which(nombre)

        if ruta:
            encontrados.append({
                "nombre": nombre,
                "ruta": ruta
            })

    return encontrados


def obtener_version(ruta):

    import subprocess

    try:

        resultado = subprocess.run(
            [ruta, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )

        return (
            resultado.stdout.strip()
            or resultado.stderr.strip()
        )

    except Exception as e:

        return str(e)


def main():

    parametros = json.loads(
        sys.argv[1]
    )

    url = parametros.get("url", "")
    usuario = parametros.get("usuario", "")
    password = parametros.get("password", "")
    operador = parametros.get("operador", "")
    detalle = parametros.get("detalle", "")

    if not url:
        raise Exception("No se recibió URL.")

    navegadores = detectar_navegadores()

    print(
        json.dumps({
            "tipo": "diagnostico",
            "mensaje": "Navegadores del sistema detectados",
            "navegadores": [
                {
                    "nombre": n["nombre"],
                    "ruta": n["ruta"],
                    "version": obtener_version(n["ruta"])
                }
                for n in navegadores
            ]
        }),
        flush=True
    )

    args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--no-zygote",
        "--ignore-certificate-errors",
    ]

    with sync_playwright() as p:

        browser = None

        # ====================================================
        # OPCIÓN 1 - NAVEGADOR DEL SISTEMA
        # ====================================================

        if navegadores:

            for navegador in navegadores:

                ruta = navegador["ruta"]

                try:

                    print(
                        json.dumps({
                            "tipo": "diagnostico",
                            "mensaje":
                                "Intentando navegador del sistema",
                            "nombre": navegador["nombre"],
                            "ruta": ruta
                        }),
                        flush=True
                    )

                    browser = p.chromium.launch(
                        executable_path=ruta,
                        headless=True,
                        args=args
                    )

                    print(
                        json.dumps({
                            "tipo": "diagnostico",
                            "mensaje":
                                "Navegador del sistema iniciado correctamente",
                            "ruta": ruta
                        }),
                        flush=True
                    )

                    break

                except Exception as e:

                    print(
                        json.dumps({
                            "tipo": "diagnostico",
                            "mensaje":
                                "Falló navegador del sistema",
                            "ruta": ruta,
                            "error": str(e)
                        }),
                        flush=True
                    )

                    browser = None

        # ====================================================
        # OPCIÓN 2 - PLAYWRIGHT
        # ====================================================

        if browser is None:

            try:

                print(
                    json.dumps({
                        "tipo": "diagnostico",
                        "mensaje":
                            "Intentando Chromium administrado por Playwright"
                    }),
                    flush=True
                )

                browser = p.chromium.launch(
                    headless=True,
                    args=args
                )

                print(
                    json.dumps({
                        "tipo": "diagnostico",
                        "mensaje":
                            "Chromium de Playwright iniciado correctamente"
                    }),
                    flush=True
                )

            except Exception as e:

                raise Exception(
                    "No fue posible iniciar ningún navegador.\n"
                    "Navegadores del sistema detectados: "
                    f"{[n['ruta'] for n in navegadores]}\n"
                    "Error Playwright:\n"
                    f"{e}"
                )

        # ====================================================
        # AUTOMATIZACIÓN
        # ====================================================

        context = browser.new_context(
            ignore_https_errors=True
        )

        page = context.new_page()

        try:

            print(
                json.dumps({
                    "tipo": "diagnostico",
                    "mensaje": "Navegando a URL",
                    "url": url
                }),
                flush=True
            )

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(3000)

            # ------------------------------------------------
            # INGRESAR A ADMIN
            # ------------------------------------------------

            admin_url = url.rstrip("/") + "/#/admin"

            print(
                json.dumps({
                    "tipo": "diagnostico",
                    "mensaje":
                        "Navegando al módulo de administración",
                    "url": admin_url
                }),
                flush=True
            )

            page.goto(
                admin_url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(3000)

            # ------------------------------------------------
            # FUNCIÓN AUXILIAR JS
            # ------------------------------------------------

            def llenar_campo_por_texto(
                valor,
                posibles_selectores
            ):

                if not valor:
                    return False

                for selector in posibles_selectores:

                    try:

                        locator = page.locator(
                            selector
                        ).first

                        if locator.count() > 0:

                            locator.fill(
                                valor
                            )

                            return True

                    except Exception:
                        pass

                return False

            # ------------------------------------------------
            # PRIMERA PANTALLA DE ACCESO
            # ------------------------------------------------

            llenar_campo_por_texto(
                usuario,
                [
                    'input[type="text"]',
                    'input[type="email"]',
                    'input[placeholder*="usuario" i]',
                    'input[placeholder*="user" i]',
                    'input[name*="usuario" i]',
                    'input[name*="user" i]'
                ]
            )

            llenar_campo_por_texto(
                password,
                [
                    'input[type="password"]',
                    'input[placeholder*="contraseña" i]',
                    'input[placeholder*="password" i]',
                    'input[name*="password" i]'
                ]
            )

            # ------------------------------------------------
            # OPERADOR
            # ------------------------------------------------

            if operador:

                page.evaluate(
                    """
                    (valor) => {
                        const inputs =
                            Array.from(
                                document.querySelectorAll(
                                    'input, textarea'
                                )
                            );

                        for (const input of inputs) {

                            const texto = (
                                input.placeholder ||
                                input.name ||
                                input.id ||
                                ''
                            ).toLowerCase();

                            if (
                                texto.includes('operador') ||
                                texto.includes('usuario')
                            ) {
                                input.value = valor;
                                input.dispatchEvent(
                                    new Event(
                                        'input',
                                        { bubbles: true }
                                    )
                                );
                                input.dispatchEvent(
                                    new Event(
                                        'change',
                                        { bubbles: true }
                                    )
                                );
                                break;
                            }
                        }
                    }
                    """,
                    operador
                )

            # ------------------------------------------------
            # DETALLE / MOTIVO
            # ------------------------------------------------

            if detalle:

                page.evaluate(
                    """
                    (valor) => {

                        const campos =
                            Array.from(
                                document.querySelectorAll(
                                    'input, textarea'
                                )
                            );

                        for (const campo of campos) {

                            const texto = (
                                campo.placeholder ||
                                campo.name ||
                                campo.id ||
                                ''
                            ).toLowerCase();

                            if (
                                texto.includes('detalle') ||
                                texto.includes('motivo') ||
                                texto.includes('observ')
                            ) {

                                campo.value = valor;

                                campo.dispatchEvent(
                                    new Event(
                                        'input',
                                        { bubbles: true }
                                    )
                                );

                                campo.dispatchEvent(
                                    new Event(
                                        'change',
                                        { bubbles: true }
                                    )
                                );

                                break;
                            }
                        }
                    }
                    """,
                    detalle
                )

            # ------------------------------------------------
            # BOTÓN PERMITIR ACCESO
            # ------------------------------------------------

            botones = [
                page.get_by_text(
                    "PERMITIR ACCESO",
                    exact=False
                ),
                page.get_by_role(
                    "button",
                    name="PERMITIR ACCESO"
                ),
                page.get_by_text(
                    "Permitir acceso",
                    exact=False
                )
            ]

            boton_encontrado = False

            for boton in botones:

                try:

                    if boton.count() > 0:

                        boton.first.click(
                            timeout=10000
                        )

                        boton_encontrado = True

                        break

                except Exception:
                    continue

            if not boton_encontrado:

                # Intento genérico mediante JavaScript

                resultado_click = page.evaluate(
                    """
                    () => {

                        const elementos =
                            Array.from(
                                document.querySelectorAll(
                                    'button, input, a, div'
                                )
                            );

                        const objetivo =
                            elementos.find(
                                e =>
                                    (
                                        e.innerText ||
                                        e.value ||
                                        ''
                                    )
                                    .trim()
                                    .toUpperCase()
                                    .includes(
                                        'PERMITIR ACCESO'
                                    )
                            );

                        if (objetivo) {

                            objetivo.click();

                            return true;
                        }

                        return false;
                    }
                    """
                )

                if not resultado_click:

                    raise Exception(
                        "No se encontró el botón "
                        "'PERMITIR ACCESO'."
                    )

            page.wait_for_timeout(4000)

            # ------------------------------------------------
            # SEGUNDA PANTALLA DE LOGIN
            # ------------------------------------------------

            llenar_campo_por_texto(
                usuario,
                [
                    'input[type="text"]',
                    'input[type="email"]',
                    'input[placeholder*="usuario" i]',
                    'input[placeholder*="user" i]',
                    'input[name*="usuario" i]',
                    'input[name*="user" i]'
                ]
            )

            llenar_campo_por_texto(
                password,
                [
                    'input[type="password"]',
                    'input[placeholder*="contraseña" i]',
                    'input[placeholder*="password" i]',
                    'input[name*="password" i]'
                ]
            )

            page.wait_for_timeout(1000)

            # ------------------------------------------------
            # LOGIN
            # ------------------------------------------------

            try:

                botones_login = [
                    page.get_by_role(
                        "button",
                        name=re.compile(
                            "ingresar|login|entrar|aceptar",
                            re.IGNORECASE
                        )
                    ),
                    page.get_by_text(
                        re.compile(
                            "ingresar|login|entrar|aceptar",
                            re.IGNORECASE
                        )
                    )
                ]

                login_realizado = False

                for boton in botones_login:

                    try:

                        if boton.count() > 0:

                            boton.first.click(
                                timeout=10000
                            )

                            login_realizado = True

                            break

                    except Exception:
                        continue

                if not login_realizado:

                    page.keyboard.press("Enter")

            except Exception:

                page.keyboard.press("Enter")

            page.wait_for_timeout(5000)

            print(
                json.dumps({
                    "tipo": "resultado",
                    "ok": True,
                    "mensaje":
                        "Automatización ejecutada correctamente"
                }),
                flush=True
            )

        finally:

            try:
                context.close()
            except Exception:
                pass

            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print(
            json.dumps({
                "tipo": "error",
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }),
            flush=True
        )

        sys.exit(1)
''' 

    return worker_code


# ============================================================
# AUTOMATIZACIÓN WEB
# ============================================================

def automatizar_web(
    url,
    usuario,
    password,
    operador,
    detalle
):

    limpiar_log()

    agregar_log(
        "Verificando disponibilidad de Chromium..."
    )

    # --------------------------------------------------------
    # PREPARAR / DETECTAR
    # --------------------------------------------------------

    preparado, navegadores = preparar_chromium()

    if not preparado:

        agregar_log(
            "No fue posible preparar el entorno de navegador.",
            "ERROR"
        )

        return False, "\n".join(
            st.session_state.log_ejecucion
        )

    agregar_log(
        "Iniciando subproceso aislado de automatización..."
    )

    # --------------------------------------------------------
    # CREAR WORKER
    # --------------------------------------------------------

    worker_path = "/tmp/runner_playwright.py"

    try:

        worker_code = crear_worker_playwright()

        with open(
            worker_path,
            "w",
            encoding="utf-8"
        ) as archivo:

            archivo.write(worker_code)

    except Exception as e:

        agregar_log(
            f"No se pudo crear el worker: {e}",
            "ERROR"
        )

        return False, "\n".join(
            st.session_state.log_ejecucion
        )

    # --------------------------------------------------------
    # PARÁMETROS
    # --------------------------------------------------------

    parametros = {
        "url": normalizar_url(url),
        "usuario": usuario,
        "password": password,
        "operador": operador,
        "detalle": detalle
    }

    # --------------------------------------------------------
    # EJECUTAR WORKER
    # --------------------------------------------------------

    try:

        resultado = subprocess.run(
            [
                sys.executable,
                worker_path,
                json.dumps(
                    parametros,
                    ensure_ascii=False
                )
            ],
            capture_output=True,
            text=True,
            timeout=180
        )

        stdout = resultado.stdout or ""
        stderr = resultado.stderr or ""

        # ----------------------------------------------------
        # PROCESAR SALIDA DEL WORKER
        # ----------------------------------------------------

        resultado_json = None

        for linea in stdout.splitlines():

            linea = linea.strip()

            if not linea:
                continue

            try:

                dato = json.loads(linea)

                # --------------------------------------------
                # DIAGNÓSTICOS
                # --------------------------------------------

                if dato.get("tipo") == "diagnostico":

                    mensaje = dato.get(
                        "mensaje",
                        ""
                    )

                    if mensaje:
                        agregar_log(
                            mensaje
                        )

                    navegadores_detectados = dato.get(
                        "navegadores"
                    )

                    if navegadores_detectados:

                        for navegador in navegadores_detectados:

                            agregar_log(
                                f"  {navegador.get('nombre')}: "
                                f"{navegador.get('ruta')} "
                                f"- {navegador.get('version')}"
                            )

                    ruta = dato.get("ruta")

                    if ruta:

                        agregar_log(
                            f"Ruta utilizada: {ruta}",
                            "OK"
                        )

                    error = dato.get("error")

                    if error:

                        agregar_log(
                            f"Error: {error}",
                            "WARNING"
                        )

                # --------------------------------------------
                # RESULTADO
                # --------------------------------------------

                elif dato.get("tipo") == "resultado":

                    resultado_json = dato

                # --------------------------------------------
                # ERROR
                # --------------------------------------------

                elif dato.get("tipo") == "error":

                    resultado_json = dato

            except Exception:
                # Salida no JSON: ignorar
                pass

        # ----------------------------------------------------
        # ERROR
        # ----------------------------------------------------

        if resultado.returncode != 0:

            if resultado_json:
                error_worker = resultado_json.get(
                    "error",
                    "Error desconocido"
                )
            else:
                error_worker = stderr or stdout

            agregar_log(
                f"ERROR EN WORKER: {error_worker}",
                "ERROR"
            )

            if stderr:

                agregar_log(
                    stderr.strip(),
                    "ERROR"
                )

            return False, "\n".join(
                st.session_state.log_ejecucion
            )

        # ----------------------------------------------------
        # ÉXITO
        # ----------------------------------------------------

        agregar_log(
            "Automatización finalizada correctamente.",
            "OK"
        )

        registrar_en_historial(
            operador=operador,
            url=url,
            ticket=st.session_state.in_tick,
            motivo=detalle,
            usuario_app=st.session_state.usuario
        )

        return True, "\n".join(
            st.session_state.log_ejecucion
        )

    except subprocess.TimeoutExpired:

        agregar_log(
            "La automatización superó el tiempo máximo de 180 segundos.",
            "ERROR"
        )

        return False, "\n".join(
            st.session_state.log_ejecucion
        )

    except Exception as e:

        agregar_log(
            f"Error ejecutando worker: {e}",
            "ERROR"
        )

        return False, "\n".join(
            st.session_state.log_ejecucion
        )


# ============================================================
# LOGIN
# ============================================================

def consultar_usuario(username):
    if supabase is None:
        return None

    try:

        resultado = (
            supabase
            .table("usuarios_app")
            .select("*")
            .or_(
                f"usuario.eq.{username},"
                f"email.eq.{username}"
            )
            .limit(1)
            .execute()
        )

        if resultado.data:
            return resultado.data[0]

        return None

    except Exception as e:

        st.error(
            f"Error consultando usuario: {e}"
        )

        return None


def autenticar_usuario(username, password):

    usuario = consultar_usuario(username)

    if not usuario:
        return False, "Usuario no encontrado."

    password_bd = usuario.get("password")

    if password_bd != password:
        return False, "Contraseña incorrecta."

    return True, usuario


def registrar_usuario(
    username,
    password,
    email
):

    if supabase is None:
        return False, "Supabase no está disponible."

    try:

        existente = consultar_usuario(
            username
        )

        if existente:
            return False, "El usuario ya existe."

        datos = {
            "usuario": username,
            "email": email,
            "password": password
        }

        resultado = (
            supabase
            .table("usuarios_app")
            .insert(datos)
            .execute()
        )

        if resultado.data:

            return True, "Usuario registrado correctamente."

        return False, "No se pudo registrar el usuario."

    except Exception as e:

        return False, str(e)


def vista_login():

    st.markdown(
        '<div class="titulo-principal">🔐 Gestor de Autorización CHESS ERP</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitulo">Ingreso al sistema de autorización</div>',
        unsafe_allow_html=True
    )

    tab_login, tab_registro = st.tabs(
        [
            "🔑 Iniciar Sesión",
            "📝 Registrar Usuario"
        ]
    )

    # ========================================================
    # LOGIN
    # ========================================================

    with tab_login:

        usuario = st.text_input(
            "Usuario / Email",
            value=st.session_state.usuario,
            key="login_usuario"
        )

        password = st.text_input(
            "Contraseña",
            type="password",
            value=st.session_state.password,
            key="login_password"
        )

        recordar = st.checkbox(
            "Recordar credenciales y mantener sesión activa",
            value=False,
            key="recordar_login"
        )

        if st.button(
            "🔐 Iniciar Sesión",
            type="primary",
            width="stretch"
        ):

            if not usuario or not password:

                st.error(
                    "Ingresá usuario y contraseña."
                )

            else:

                correcto, resultado = autenticar_usuario(
                    usuario,
                    password
                )

                if correcto:

                    st.session_state.autenticado = True
                    st.session_state.usuario = usuario
                    st.session_state.password = password

                    if recordar:

                        try:

                            cookie_manager.set(
                                "chess_usuario",
                                usuario,
                                expires_at=(
                                    ahora_argentina()
                                    + timedelta(days=30)
                                )
                            )

                        except Exception:
                            pass

                    st.success(
                        "Inicio de sesión correcto."
                    )

                    st.rerun()

                else:

                    st.error(resultado)

    # ========================================================
    # REGISTRO
    # ========================================================

    with tab_registro:

        nuevo_usuario = st.text_input(
            "Usuario",
            key="registro_usuario"
        )

        nuevo_email = st.text_input(
            "Email",
            key="registro_email"
        )

        nueva_password = st.text_input(
            "Contraseña",
            type="password",
            key="registro_password"
        )

        repetir_password = st.text_input(
            "Repetir contraseña",
            type="password",
            key="registro_password2"
        )

        if st.button(
            "📝 Registrar Usuario",
            type="primary",
            width="stretch"
        ):

            if not nuevo_usuario:
                st.error("Ingresá un usuario.")

            elif not nuevo_email:
                st.error("Ingresá un email.")

            elif not nueva_password:
                st.error("Ingresá una contraseña.")

            elif nueva_password != repetir_password:
                st.error(
                    "Las contraseñas no coinciden."
                )

            else:

                correcto, mensaje = registrar_usuario(
                    nuevo_usuario,
                    nueva_password,
                    nuevo_email
                )

                if correcto:
                    st.success(mensaje)

                else:
                    st.error(mensaje)


# ============================================================
# CERRAR SESIÓN
# ============================================================

def cerrar_sesion():

    st.session_state.autenticado = False
    st.session_state.usuario = ""
    st.session_state.password = ""

    try:
        cookie_manager.delete(
            "chess_usuario"
        )
    except Exception:
        pass

    st.rerun()


# ============================================================
# VISTA PRINCIPAL
# ============================================================

def vista_principal():

    # ========================================================
    # SIDEBAR
    # ========================================================

    with st.sidebar:

        st.markdown(
            "### 🔐 CHESS ERP"
        )

        st.markdown(
            f"Usuario: **{st.session_state.usuario}**"
        )

        st.divider()

        if st.button(
            "🚪 Cerrar Sesión",
            width="stretch"
        ):
            cerrar_sesion()

        st.divider()

        st.markdown(
            """
            **Gestor de Autorización**

            Automatización de autorizaciones
            mediante Playwright.
            """
        )

    # ========================================================
    # TÍTULO
    # ========================================================

    st.markdown(
        '<div class="titulo-principal">🔐 Gestor de Autorización CHESS ERP</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitulo">Procesamiento y autorización automática de solicitudes</div>',
        unsafe_allow_html=True
    )

    # ========================================================
    # MENSAJE
    # ========================================================

    st.subheader(
        "📨 Mensaje de autorización"
    )

    mensaje = st.text_area(
        "Pegá aquí el mensaje recibido:",
        value=st.session_state.mensaje,
        height=180,
        key="mensaje_autorizacion"
    )

    col1, col2 = st.columns(2)

    with col1:

        if st.button(
            "🔎 Procesar mensaje",
            type="primary",
            width="stretch"
        ):

            if not mensaje.strip():

                st.warning(
                    "Ingresá un mensaje."
                )

            else:

                extraer_y_actualizar(
                    mensaje
                )

                st.success(
                    "Datos extraídos correctamente."
                )

    with col2:

        if st.button(
            "🗑️ Limpiar",
            width="stretch"
        ):

            st.session_state.mensaje = ""

            st.session_state.in_dom = ""
            st.session_state.in_op = ""
            st.session_state.in_tick = ""
            st.session_state.in_mot = ""

            st.rerun()

    # ========================================================
    # DATOS DETECTADOS
    # ========================================================

    st.subheader(
        "📋 Datos detectados"
    )

    col1, col2 = st.columns(2)

    with col1:

        operador = st.text_input(
            "Operador",
            value=st.session_state.in_op,
            key="campo_operador"
        )

        ticket = st.text_input(
            "Ticket",
            value=st.session_state.in_tick,
            key="campo_ticket"
        )

    with col2:

        url = st.text_input(
            "URL",
            value=st.session_state.in_dom,
            key="campo_url"
        )

        motivo = st.text_area(
            "Motivo",
            value=st.session_state.in_mot,
            height=100,
            key="campo_motivo"
        )

    # ========================================================
    # ACTUALIZAR SESSION STATE
    # ========================================================

    st.session_state.in_op = operador
    st.session_state.in_tick = ticket
    st.session_state.in_dom = url
    st.session_state.in_mot = motivo

    # ========================================================
    # VALIDACIÓN
    # ========================================================

    datos_completos = bool(
        operador.strip()
        and url.strip()
        and motivo.strip()
    )

    if datos_completos:

        st.markdown(
            """
            <div class="estado-ok">
                ✅ Datos suficientes para ejecutar la autorización.
            </div>
            """,
            unsafe_allow_html=True
        )

    else:

        st.markdown(
            """
            <div class="estado-warning">
                ⚠️ Faltan datos para ejecutar la autorización.
                Verificá operador, URL y motivo.
            </div>
            """,
            unsafe_allow_html=True
        )

    # ========================================================
    # AUTORIZACIÓN
    # ========================================================

    st.subheader(
        "🚀 Autorización"
    )

    col1, col2 = st.columns(2)

    with col1:

        ejecutar = st.button(
            "🚀 AUTORIZAR",
            type="primary",
            width="stretch",
            disabled=not datos_completos
        )

    with col2:

        verificar = st.button(
            "🔍 Verificar autorización reciente",
            width="stretch",
            disabled=not bool(url.strip())
        )

    # ========================================================
    # VERIFICAR DUPLICADO
    # ========================================================

    if verificar:

        reciente = buscar_autorizacion_reciente(
            url
        )

        if reciente:

            fecha = reciente.get(
                "fecha_hora",
                ""
            )

            operador_anterior = reciente.get(
                "operador",
                ""
            )

            ticket_anterior = reciente.get(
                "ticket",
                ""
            )

            st.warning(
                "⚠️ Se encontró una autorización reciente "
                f"para este dominio.\n\n"
                f"Operador: {operador_anterior}\n\n"
                f"Ticket: {ticket_anterior}\n\n"
                f"Fecha: {fecha}"
            )

            st.session_state.forzar_ejecucion = True

        else:

            st.success(
                "✅ No se encontraron autorizaciones "
                "recientes para este dominio."
            )

    # ========================================================
    # EJECUTAR
    # ========================================================

    if ejecutar:

        reciente = buscar_autorizacion_reciente(
            url
        )

        if reciente and not st.session_state.forzar_ejecucion:

            st.warning(
                "⚠️ Ya existe una autorización reciente "
                "para este dominio."
            )

            st.info(
                "Si necesitás realizarla igualmente, "
                "verificá la información y volvé a ejecutar."
            )

        else:

            with st.spinner(
                "Ejecutando autorización en CHESS ERP..."
            ):

                correcto, log = automatizar_web(
                    url=url,
                    usuario=st.session_state.usuario,
                    password=st.session_state.password,
                    operador=operador,
                    detalle=motivo
                )

            if correcto:

                st.success(
                    "✅ Autorización ejecutada correctamente."
                )

            else:

                st.error(
                    "❌ La autorización no pudo ejecutarse."
                )

            st.session_state.forzar_ejecucion = False

    # ========================================================
    # ESTADO DE EJECUCIÓN
    # ========================================================

    st.subheader(
        "📊 Estado de Ejecución"
    )

    if st.session_state.log_ejecucion:

        log_texto = "\n".join(
            st.session_state.log_ejecucion
        )

        st.code(
            log_texto,
            language="bash"
        )

    else:

        st.info(
            "Todavía no se ejecutó ninguna automatización."
        )

    # ========================================================
    # HISTORIAL SUPABASE
    # ========================================================

    st.subheader(
        "📚 Historial de autorizaciones"
    )

    if supabase is not None:

        try:

            resultado = (
                supabase
                .table("historial_autorizaciones")
                .select("*")
                .order("fecha_hora", desc=True)
                .limit(50)
                .execute()
            )

            if resultado.data:

                import pandas as pd

                df = pd.DataFrame(
                    resultado.data
                )

                st.dataframe(
                    df,
                    width="stretch",
                    hide_index=True
                )

            else:

                st.info(
                    "No hay autorizaciones registradas."
                )

        except Exception as e:

            st.warning(
                f"No se pudo cargar el historial: {e}"
            )


# ============================================================
# ARRANQUE
# ============================================================

if not st.session_state.autenticado:

    vista_login()

else:

    vista_principal()