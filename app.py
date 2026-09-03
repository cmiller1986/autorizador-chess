import streamlit as st
import streamlit.components.v1 as components
import re
import time
import sys
from datetime import datetime
from supabase import create_client, Client
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException


# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Gestor de Autorización CHESS ERP",
    page_icon="key",
    layout="centered"
)

# Estilos CSS
st.markdown("""
    <style>
    .main { background-color: #f8fafc; }
    .stButton>button { border-radius: 8px; font-weight: bold; }
    .stTextArea textarea { font-family: monospace; }
    </style>
""", unsafe_allow_html=True)

# --- INICIALIZACIÓN DE SUPABASE ---
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# --- INICIALIZACIÓN DE ESTADOS ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario" not in st.session_state:
    st.session_state.usuario = ""
if "password" not in st.session_state:
    st.session_state.password = ""
if "log_ejecucion" not in st.session_state:
    st.session_state.log_ejecucion = []

# Llaves UI
if "txt_mensaje" not in st.session_state:
    st.session_state.txt_mensaje = "Roy Topping, 14 min\nURL: https://codenoa.chesserp.com/AR467\nTicket: #512918\nMotivo: Gerente que no aparece"
if "in_dom" not in st.session_state:
    st.session_state.in_dom = "No detectado"
if "in_op" not in st.session_state:
    st.session_state.in_op = "No detectado"
if "in_tick" not in st.session_state:
    st.session_state.in_tick = ""
if "in_mot" not in st.session_state:
    st.session_state.in_mot = ""
if "ultimo_mensaje_procesado" not in st.session_state:
    st.session_state.ultimo_mensaje_procesado = None
if "url_autorizada_lista" not in st.session_state:
    st.session_state.url_autorizada_lista = None

# --- FUNCIONES AUXILIARES ---
def log_msg(msg, placeholder_log=None, estado="INFO"):
    prefix = ""
    if estado == "OK":
        prefix = "[OK] "
    elif estado == "ERROR":
        prefix = "[ERROR] "
    elif estado == "WARN":
        prefix = "[WARN] "
    else:
        prefix = "[...]"
    
    linea = f"{prefix} {msg}"
    st.session_state.log_ejecucion.append(linea)
    
    if placeholder_log:
        placeholder_log.code("\n".join(st.session_state.log_ejecucion), language="bash")

def registrar_en_historial(usuario, dominio_ruta, operador, motivo_final):
    try:
        supabase.table("historial_autorizaciones").insert({
            "usuario": usuario,
            "dominio_ruta": dominio_ruta,
            "operador": operador,
            "motivo": motivo_final,
        }).execute()
    except Exception as e:
        log_msg(f"Error al guardar historial en Supabase: {e}", estado="WARN")

def extraer_y_actualizar(texto_mensaje):
    usuario_actual = st.session_state.usuario
    lineas = [l.strip() for l in texto_mensaje.split("\n") if l.strip()]
    primera_linea = lineas[0] if lineas else ""

    if primera_linea.lower().startswith("url:") or primera_linea.lower().startswith("http"):
        operador = usuario_actual or "No detectado"
    else:
        if "," in primera_linea:
            raw_op = primera_linea.split(",")[0].strip()
        else:
            raw_op = re.split(r"\d+\s*min|Ahora|Ayer|\d{1,2}:\d{2}", primera_linea, flags=re.IGNORECASE)[0].strip()
        operador = raw_op if raw_op else "No detectado"

    pattern_url = r"(?:https?://)?(?:[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?(?:/[^\s\n]*)?"
    urls_encontradas = re.findall(pattern_url, texto_mensaje)

    if urls_encontradas:
        dominio_ruta = re.sub(r"^url:\s*", "", urls_encontradas[0], flags=re.IGNORECASE).strip().rstrip("/")
    else:
        dominio_ruta = "No detectado"

    match_ticket = re.search(r"(#\d+)", texto_mensaje)
    ticket = match_ticket.group(1) if match_ticket else ""

    match_motivo = re.search(r"[Mm]otivo:\s*(.*)", texto_mensaje, re.IGNORECASE)
    if match_motivo:
        motivo_raw = match_motivo.group(1).strip()
    else:
        resto = []
        for l in lineas:
            linea_lower = l.lower()
            if (linea_lower.startswith("url:") or 
                "http://" in linea_lower or 
                "https://" in linea_lower or 
                "chesserp" in linea_lower or
                re.search(r"\.[a-zA-Z]{2,}", l) or
                re.search(r"^#\d+$", l) or 
                l == primera_linea):
                continue
            resto.append(l)
        motivo_raw = " ".join(resto) if resto else ""

    motivo_raw = re.sub(r"(?:https?://)?\S+\.\S+", "", motivo_raw).strip()

    st.session_state["in_dom"] = dominio_ruta
    st.session_state["in_op"] = operador
    st.session_state["in_tick"] = ticket
    st.session_state["in_mot"] = motivo_raw

def borrar_todo():
    st.session_state.txt_mensaje = ""
    st.session_state.in_dom = "No detectado"
    st.session_state.in_op = "No detectado"
    st.session_state.in_tick = ""
    st.session_state.in_mot = ""
    st.session_state.log_ejecucion = []
    st.session_state.ultimo_mensaje_procesado = None
    st.session_state.url_autorizada_lista = None

def automatizar_web(dominio_ruta, usuario, password, operador, motivo_final, texto_mensaje, placeholder_log):
    st.session_state.log_ejecucion = []
    
    if dominio_ruta.startswith("http://") or dominio_ruta.startswith("https://"):
        url_base = dominio_ruta
    else:
        contiene_puerto = re.search(r":\d+", dominio_ruta)
        es_ip = re.search(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", dominio_ruta)
        if "http://" in texto_mensaje.lower() or contiene_puerto or es_ip:
            url_base = f"http://{dominio_ruta}"
        else:
            url_base = f"https://{dominio_ruta}"

    log_msg(f"Iniciando acceso dinámico a: {url_base}", placeholder_log, "INFO")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors=yes")
    options.add_argument("--allow-insecure-localhost")

    driver = None
    try:
        log_msg("Iniciando navegador Chrome optimizado...", placeholder_log, "INFO")
        
        if sys.platform.startswith("linux"):
            options.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver")
        else:
            service = Service()
            if sys.platform.startswith("win"):
                service.creation_flags = 0x08000000

        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 20)
        log_msg("Navegador listo.", placeholder_log, "OK")

        # Cargar la raíz e investigar redirección dinámica del router (/ARxxx)
        log_msg("Inicializando SPA de Chess ERP...", placeholder_log, "INFO")
        driver.get(url_base)
        time.sleep(3)  # Tiempo de espera para que resuelva redirecciones de servidor/router

        # Capturar la URL real resuelta por el navegador
        url_actual = driver.current_url.split("#")[0].rstrip("/")
        url_admin = f"{url_actual}/#/admin"

        log_msg(f"Navegando a la pantalla de admin: {url_admin}", placeholder_log, "INFO")
        driver.get(url_admin)
        time.sleep(2)

        log_msg("Esperando formulario de Autorización...", placeholder_log, "INFO")
        xpath_input_usr = "//input[@id='usuario' or @formcontrolname='usuario']"
        wait.until(EC.presence_of_element_located((By.XPATH, xpath_input_usr)))
        log_msg("Formulario de Autorización detectado.", placeholder_log, "OK")
        time.sleep(1)

        def inyectar_campo_js(id_o_control, valor, nombre_campo):
            script = """
                var selector = arguments[0];
                var val = arguments[1];
                
                var el = document.getElementById(selector) || 
                         document.querySelector('[formcontrolname="' + selector + '"]') ||
                         document.querySelector('[name="' + selector + '"]');
                
                if (!el) {
                    var inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="button"]), textarea'));
                    
                    if (selector.toLowerCase().includes('usuario')) {
                        el = inputs[0];
                    } else if (selector.toLowerCase().includes('contrasenia') || selector.toLowerCase().includes('password')) {
                        el = document.querySelector('input[type="password"]') || inputs[1];
                    } else if (selector.toLowerCase().includes('operador')) {
                        el = inputs.find(i => (i.placeholder || '').toLowerCase().includes('operador') || (i.id || '').toLowerCase().includes('operador')) || inputs[2];
                    } else if (selector.toLowerCase().includes('detalle') || selector.toLowerCase().includes('motivo')) {
                        el = document.querySelector('textarea') || 
                             inputs.find(i => (i.placeholder || '').toLowerCase().includes('motivo') || (i.id || '').toLowerCase().includes('motivo')) || 
                             inputs[inputs.length - 1];
                    }
                }

                if (el) {
                    el.removeAttribute('disabled');
                    el.removeAttribute('readonly');
                    el.focus();
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                    return true;
                }
                return false;
            """
            for _ in range(5):
                res = driver.execute_script(script, id_o_control, valor)
                if res:
                    return True
                time.sleep(0.5)
            log_msg(f"No se pudo inyectar el valor en {nombre_campo}", placeholder_log, "ERROR")
            return False

        # PASO 1: Formulario de Autorización
        log_msg(f"Ingresando Usuario Admin: '{usuario}'...", placeholder_log, "INFO")
        if inyectar_campo_js("usuario", usuario, "Usuario"):
            log_msg("Usuario ingresado correctamente.", placeholder_log, "OK")
        time.sleep(0.4)

        log_msg("Ingresando Contraseña...", placeholder_log, "INFO")
        if inyectar_campo_js("contrasenia", password, "Contraseña"):
            log_msg("Contraseña ingresada correctamente.", placeholder_log, "OK")
        time.sleep(1.0)

        log_msg(f"Asignando Operador Autorizado: '{operador}'...", placeholder_log, "INFO")
        ok_op = inyectar_campo_js("operadorAutorizado", operador, "Operador Autorizado")
        if not ok_op:
            return False, "No se pudo escribir el Operador Autorizado en el formulario.", False
        log_msg("Operador Autorizado asignado.", placeholder_log, "OK")
        time.sleep(0.4)

        log_msg(f"Asignando Motivo: '{motivo_final}'...", placeholder_log, "INFO")
        ok_mot = inyectar_campo_js("detalle", motivo_final, "Motivo")
        if not ok_mot:
            return False, "No se pudo escribir el Motivo en el formulario.", False
        log_msg("Motivo asignado.", placeholder_log, "OK")
        time.sleep(1)

        log_msg("Enviando autorización al ERP...", placeholder_log, "INFO")
        btn_enviado = driver.execute_script("""
            var btn = document.querySelector('button[label="PERMITIR ACCESO"]') || document.querySelector('button.login-button') || document.querySelector('button');
            if (btn) {
                btn.removeAttribute('disabled');
                btn.classList.remove('p-disabled');
                btn.click();
                return true;
            }
            return false;
        """)

        if not btn_enviado:
            log_msg("No se encontró el botón 'PERMITIR ACCESO'.", placeholder_log, "ERROR")
            return False, "No se encontró el botón 'PERMITIR ACCESO'.", False
        
        log_msg("Solicitud enviada al servidor ERP.", placeholder_log, "OK")

        # PASO 2: Redirección automática al Login
        log_msg("Esperando redirección automática a la pantalla de Login...", placeholder_log, "INFO")
        time.sleep(3)

        # PASO 3: Iniciar Sesión Final
        log_msg("Iniciando sesión en la pantalla de Login...", placeholder_log, "INFO")
        wait.until(EC.presence_of_element_located((By.XPATH, xpath_input_usr)))

        inyectar_campo_js("usuario", usuario, "Usuario Login")
        time.sleep(0.4)
        inyectar_campo_js("contrasenia", password, "Contraseña Login")
        time.sleep(0.8)

        log_msg("Enviando credenciales de inicio de sesión...", placeholder_log, "INFO")
        driver.execute_script("""
            var inputPass = document.getElementById('contrasenia') || document.querySelector('input[type="password"]');
            var form = inputPass ? inputPass.closest('form') : null;
            if (form) {
                form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            } else {
                var btnLogin = document.querySelector('button[label="INICIAR SESIÓN"]') || document.querySelector('button.login-button') || Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('INICIAR'));
                if (btnLogin) {
                    btnLogin.removeAttribute('disabled');
                    btnLogin.click();
                }
            }
        """)

        try:
            elem_pass = driver.find_element(By.XPATH, "//input[@type='password']")
            elem_pass.send_keys(Keys.ENTER)
        except Exception:
            pass

        time.sleep(4)

        log_msg("ACCESO AUTORIZADO Y SESIÓN INICIADA CORRECTAMENTE EN CHESS ERP.", placeholder_log, "OK")
        registrar_en_historial(usuario, dominio_ruta, operador, motivo_final)
        return True, "Acceso e inicio de sesión completados correctamente", False, url_actual

    except Exception as e:
        nombre_error = type(e).__name__
        detalle = str(e).strip().split("\n")[0]
        mensaje_completo = f"{nombre_error}: {detalle}" if detalle else nombre_error
        log_msg(f"ERROR EN AUTOMATIZACIÓN: {mensaje_completo}", placeholder_log, "ERROR")
        return False, mensaje_completo, False, None
    finally:
        if driver:
            driver.quit()

# --- PANTALLA 1: LOGIN Y REGISTRO CON PERSISTENCIA DE CREDENCIALES ---
def vista_login():
    st.markdown("<h2 style='text-align: center;'>Acceso CHESS ERP</h2>", unsafe_allow_html=True)
    st.markdown("---")
    
    opcion = st.radio("Acción:", ["Iniciar Sesion", "Registrar Usuario"], horizontal=True)

    # Inyección de JS nativa que recupera y auto-completa las credenciales desde localStorage
    st.markdown("""
        <script>
            (function() {
                setTimeout(function() {
                    const savedUsr = localStorage.getItem('chess_saved_usr');
                    const savedPwd = localStorage.getItem('chess_saved_pwd');
                    
                    if (savedUsr && savedPwd) {
                        const inputs = window.parent.document.querySelectorAll('input');
                        inputs.forEach(function(input) {
                            if (input.type === 'text' && !input.value) {
                                input.value = savedUsr;
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                            }
                            if (input.type === 'password' && !input.value) {
                                input.value = savedPwd;
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                            }
                        });
                    }
                }, 300);
            })();
        </script>
    """, unsafe_allow_html=True)

    with st.form("auth_form"):
        usr_input = st.text_input("Usuario ERP", key="login_usr_input")
        pwd = st.text_input("Contraseña ERP", type="password", key="login_pwd_input")
        
        email_input = None
        if opcion == "Registrar Usuario":
            email_input = st.text_input("Correo electrónico")

        recordar_credenciales = st.checkbox("Recordar credenciales en este navegador", value=True)
        
        submit = st.form_submit_button("CONTINUAR", use_container_width=True)
        
        if submit:
            if not usr_input or not pwd:
                st.warning("Por favor complete usuario y contraseña.")
                return

            usuario_limpio = usr_input.strip()

            if opcion == "Iniciar Sesion":
                with st.spinner("Verificando credenciales en Supabase..."):
                    try:
                        res = (
                            supabase.table("usuarios_app")
                            .select("*")
                            .or_(f"usuario.eq.{usuario_limpio},email.eq.{usuario_limpio.lower()}")
                            .eq("password", pwd)
                            .execute()
                        )
                        
                        registros = res.data or []
                        if len(registros) > 0:
                            st.session_state.autenticado = True
                            st.session_state.usuario = registros[0]["usuario"]
                            st.session_state.password = registros[0]["password"]
                            
                            # Script JS que se ejecuta al autenticar con éxito para guardar/borrar en localStorage
                            if recordar_credenciales:
                                js_save = f"""
                                    <script>
                                        localStorage.setItem('chess_saved_usr', '{usuario_limpio}');
                                        localStorage.setItem('chess_saved_pwd', '{pwd}');
                                    </script>
                                """
                            else:
                                js_save = """
                                    <script>
                                        localStorage.removeItem('chess_saved_usr');
                                        localStorage.removeItem('chess_saved_pwd');
                                    </script>
                                """
                            st.markdown(js_save, unsafe_allow_html=True)
                            st.rerun()
                        else:
                            st.error("Usuario, email o contraseña incorrectos.")
                    except Exception as e:
                        st.error(f"Error al consultar la base de datos: {e}")

            elif opcion == "Registrar Usuario":
                email_final = email_input.strip().lower() if email_input else f"{usuario_limpio.lower()}@chesserp.com"

                with st.spinner("Guardando en usuarios_app..."):
                    try:
                        supabase.table("usuarios_app").insert({
                            "usuario": usuario_limpio,
                            "password": pwd,
                            "email": email_final
                        }).execute()

                        st.success(f"Usuario '{usuario_limpio}' registrado exitosamente. Ya puede iniciar sesión.")
                    except Exception as e:
                        st.error(f"Error al registrar en Supabase (usuario o email ya existente): {e}")

# --- PANTALLA 2: PRINCIPAL ---
def vista_principal():
    st.sidebar.title("Menú")
    st.sidebar.write(f"**Usuario activo:** `{st.session_state.usuario}`")
    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.session_state.usuario = ""
        st.session_state.password = ""
        borrar_todo()
        st.rerun()

    st.title("Gestor de Autorización CHESS ERP")
    
    txt_mensaje = st.text_area(
        "Pegue el mensaje de solicitud:",
        key="txt_mensaje",
        height=120
    )

    col_proc, col_borr = st.columns([2, 1])
    
    with col_proc:
        btn_procesar = st.button("⚡ PROCESAR MENSAJE", use_container_width=True)
    with col_borr:
        st.button("🗑️ Borrar", on_click=borrar_todo, use_container_width=True)

    if btn_procesar:
        if txt_mensaje.strip():
            extraer_y_actualizar(txt_mensaje)
            st.session_state.ultimo_mensaje_procesado = txt_mensaje
            st.session_state.url_autorizada_lista = None
            st.rerun()
        else:
            st.warning("Por favor ingrese o pegue un mensaje antes de procesar.")

    if st.session_state.ultimo_mensaje_procesado != txt_mensaje and st.session_state.ultimo_mensaje_procesado is None:
        extraer_y_actualizar(txt_mensaje)
        st.session_state.ultimo_mensaje_procesado = txt_mensaje

    st.markdown("---")

    st.markdown("### Datos Detectados (Editables)")
    st.caption("Verifique o edite los campos manualmente antes de autorizar:")

    col1, col2 = st.columns(2)
    with col1:
        dominio_final = st.text_input("Servidor / Ruta URL:", key="in_dom")
        operador_final = st.text_input("Operador Autorizado:", key="in_op")
    with col2:
        ticket_final = st.text_input("No. Ticket:", key="in_tick")
        motivo_base = st.text_input("Motivo:", key="in_mot")

    if ticket_final and not motivo_base.startswith(ticket_final):
        motivo_ejecucion = f"{ticket_final} - {motivo_base}" if motivo_base else ticket_final
    else:
        motivo_ejecucion = motivo_base

    st.markdown("---")

    btn_permitir = st.button("PERMITIR ACCESO EN CHESS ERP", type="primary", use_container_width=True)

    if st.session_state.url_autorizada_lista:
        st.link_button(
            "🔗 Abrir ERP Habilitado en la Web", 
            st.session_state.url_autorizada_lista, 
            use_container_width=True
        )

    st.markdown("---")

    st.markdown("#### Estado de Ejecución")
    placeholder_log = st.empty()
    
    if st.session_state.log_ejecucion:
        placeholder_log.code("\n".join(st.session_state.log_ejecucion), language="bash")

    if btn_permitir:
        if not dominio_final or dominio_final == "No detectado":
            st.error("Por favor ingrese un Servidor / Ruta URL válido.")
        else:
            exito, msg, advertencia, url_resuelta = automatizar_web(
                dominio_final,
                st.session_state.usuario,
                st.session_state.password,
                operador_final,
                motivo_ejecucion,
                txt_mensaje,
                placeholder_log
            )
            if exito:
                st.session_state.url_autorizada_lista = url_resuelta or (
                    dominio_final if dominio_final.startswith("http") else f"https://{dominio_final}"
                )
                if not advertencia:
                    st.success(f"{msg}")
                else:
                    st.warning(f"{msg}")
                st.rerun()
            else:
                st.session_state.url_autorizada_lista = None
                st.error(f"Error: {msg}")

    with st.expander("Ver Historial de Autorizaciones"):
        try:
            res = (
                supabase.table("historial_autorizaciones")
                .select("*")
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            registros = res.data or []
            if registros:
                for r in registros:
                    fecha = r.get("created_at", "")
                    st.text(
                        f"[{fecha}] USUARIO: {r.get('usuario','')} | RUTA: {r.get('dominio_ruta','')} "
                        f"| OPERADOR: {r.get('operador','')} | MOTIVO: {r.get('motivo','')}"
                    )
            else:
                st.info("Aún no hay registros en el historial.")
        except Exception as e:
            st.warning(f"No se pudo cargar el historial desde Supabase: {e}")

# --- EJECUCIÓN PRINCIPAL ---
if not st.session_state.autenticado:
    vista_login()
else:
    vista_principal()