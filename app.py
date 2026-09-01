import streamlit as st
import re
import time
import os
import sys
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

ARCHIVO_HISTORIAL = "historial_autorizaciones.txt"

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Gestor de Autorización CHESS ERP",
    page_icon="🔓",
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

# --- INICIALIZACIÓN DE ESTADOS ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario" not in st.session_state:
    st.session_state.usuario = ""
if "password" not in st.session_state:
    st.session_state.password = ""
if "log_ejecucion" not in st.session_state:
    st.session_state.log_ejecucion = []

# Inicializamos las llaves de los controles UI
if "in_dom" not in st.session_state:
    st.session_state.in_dom = "No detectado"
if "in_op" not in st.session_state:
    st.session_state.in_op = "No detectado"
if "in_tick" not in st.session_state:
    st.session_state.in_tick = ""
if "in_mot" not in st.session_state:
    st.session_state.in_mot = ""

# --- FUNCIONES AUXILIARES ---
def log_msg(msg):
    st.session_state.log_ejecucion.append(f"> {msg}")

def registrar_en_historial(usuario, dominio_ruta, operador, motivo_final):
    try:
        fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linea = f"[{fecha_hora}] USUARIO: {usuario} | RUTA: {dominio_ruta} | OPERADOR: {operador} | MOTIVO: {motivo_final}\n"
        with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
            f.write(linea)
    except Exception as e:
        log_msg(f"⚠️ Error al guardar historial: {e}")

def extraer_y_actualizar(texto_mensaje):
    usuario_actual = st.session_state.usuario
    lineas = [l.strip() for l in texto_mensaje.split("\n") if l.strip()]
    primera_linea = lineas[0] if lineas else ""

    # 1. Extracción de Operador
    if primera_linea.lower().startswith("url:") or primera_linea.lower().startswith("http"):
        operador = usuario_actual or "No detectado"
    else:
        if "," in primera_linea:
            raw_op = primera_linea.split(",")[0].strip()
        else:
            raw_op = re.split(r"\d+\s*min|Ahora|Ayer|\d{1,2}:\d{2}", primera_linea, flags=re.IGNORECASE)[0].strip()
        operador = raw_op if raw_op else "No detectado"

    # 2. Extracción de URL/Servidor
    urls_encontradas = re.findall(r"(?:https?://)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?::\d+)?(?:/[^\s\n]*)?", texto_mensaje)
    if not urls_encontradas:
        urls_encontradas = re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?", texto_mensaje)

    if urls_encontradas:
        dominio_ruta = re.sub(r"^url:\s*", "", urls_encontradas[0], flags=re.IGNORECASE).strip().rstrip("/")
    else:
        dominio_ruta = "No detectado"

    # 3. Extracción de Ticket
    match_ticket = re.search(r"(#\d+)", texto_mensaje)
    ticket = match_ticket.group(1) if match_ticket else ""

    # 4. Extracción de Motivo
    match_motivo = re.search(r"[Mm]otivo:\s*(.*)", texto_mensaje, re.IGNORECASE)
    if match_motivo:
        motivo_raw = match_motivo.group(1).strip()
    else:
        resto = [
            l for l in lineas 
            if not l.lower().startswith("url:") 
            and not "http://" in l.lower() 
            and not "https://" in l.lower() 
            and not re.search(r"^#\d+$", l) 
            and l != primera_linea
        ]
        motivo_raw = " ".join(resto) if resto else ""

    # Sobreescritura directa de las keys del session_state
    st.session_state["in_dom"] = dominio_ruta
    st.session_state["in_op"] = operador
    st.session_state["in_tick"] = ticket
    st.session_state["in_mot"] = motivo_raw

def escribir_elemento_humano(driver, elemento, texto):
    try:
        driver.execute_script("arguments[0].click();", elemento)
        time.sleep(0.1)
        elemento.send_keys(Keys.CONTROL + "a")
        elemento.send_keys(Keys.BACKSPACE)
        time.sleep(0.1)
        elemento.send_keys(texto)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));"
            "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
            elemento,
        )
        time.sleep(0.1)
    except Exception:
        try:
            driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));"
                "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                elemento, texto
            )
        except Exception as e:
            log_msg(f"⚠️ Error al escribir en campo: {str(e).split('\n')[0]}")

# --- VALIDACIÓN DINÁMICA DE CREDENCIALES ---
def validar_credenciales_erp(usuario, password, url_servidor):
    if not url_servidor.startswith("http://") and not url_servidor.startswith("https://"):
        url_target = f"https://{url_servidor.strip()}"
    else:
        url_target = url_servidor.strip()

    if "/#/admin" not in url_target:
        url_target = (url_target.split("#")[0].rstrip("/") + "/#/admin") if "#" in url_target else f"{url_target.rstrip('/')}/#/admin"

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors=yes")
    options.add_argument("--allow-insecure-localhost")

    if sys.platform.startswith("linux"):
        options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
    else:
        service = Service()
        if sys.platform.startswith("win"):
            service.creation_flags = 0x08000000

    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 12)

        driver.get(url_target)
        wait.until(EC.presence_of_element_located((By.XPATH, "//input")))
        time.sleep(1)

        inputs_texto = driver.find_elements(By.XPATH, "//input[not(@type='checkbox') and not(@type='radio') and not(@type='hidden') and not(@type='button')]")
        input_pass = driver.find_elements(By.XPATH, "//input[@type='password']")
        inputs_visibles = [i for i in inputs_texto if i.is_displayed()]

        if inputs_visibles:
            escribir_elemento_humano(driver, inputs_visibles[0], usuario)
        if input_pass:
            escribir_elemento_humano(driver, input_pass[0], password)

        xpath_btn = "//button[contains(translate(text(), 'PERMITIR ACCESO', 'permitir acceso'), 'permitir acceso')]"
        elementos = driver.find_elements(By.XPATH, xpath_btn)
        btn_target = [e for e in elementos if e.is_displayed()]
        if btn_target:
            driver.execute_script("arguments[0].click();", btn_target[0])

        time.sleep(2)
        
        errores_alert = driver.find_elements(By.XPATH, "//*[contains(@class, 'error') or contains(@class, 'alert-danger') or contains(text(), 'incorrecta') or contains(text(), 'inválido')]")
        mensajes_error = [e.text for e in errores_alert if e.is_displayed() and e.text.strip()]

        if mensajes_error:
            return False, mensajes_error[0]
        
        return True, "Credenciales válidas"

    except Exception as e:
        return False, f"No se pudo conectar al ERP: {str(e).split('\n')[0]}"
    finally:
        if driver:
            driver.quit()

def automatizar_web(dominio_ruta, usuario, password, operador, motivo_final, texto_mensaje):
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

    log_msg(f"Iniciando acceso dinámico a: {url_base}")

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
        log_msg("Iniciando navegador Chrome optimizado...")
        
        if sys.platform.startswith("linux"):
            options.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver")
        else:
            service = Service()
            if sys.platform.startswith("win"):
                service.creation_flags = 0x08000000

        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 15)

        log_msg("Navegando a la URL del ERP...")
        driver.get(url_base)
        time.sleep(2)

        url_actual = driver.current_url.rstrip("/")
        if "/#/admin" not in url_actual:
            url_target = (url_actual.split("#")[0].rstrip("/") + "/#/admin") if "#" in url_actual else f"{url_actual}/#/admin"
            log_msg(f"Navegando a la pantalla de admin: {url_target}")
            driver.get(url_target)
            time.sleep(1)

        log_msg("Esperando formulario de Autorización...")
        wait.until(EC.presence_of_element_located((By.XPATH, "//input")))
        time.sleep(1)

        inputs_texto = driver.find_elements(By.XPATH, "//input[not(@type='checkbox') and not(@type='radio') and not(@type='hidden') and not(@type='button')]")
        input_pass = driver.find_elements(By.XPATH, "//input[@type='password']")
        inputs_visibles = [i for i in inputs_texto if i.is_displayed()]

        log_msg(f"Ingresando Usuario: '{usuario}'...")
        if inputs_visibles:
            escribir_elemento_humano(driver, inputs_visibles[0], usuario)

        log_msg("Ingresando Contraseña...")
        if input_pass:
            escribir_elemento_humano(driver, input_pass[0], password)

        log_msg(f"Asignando Operador Autorizado: '{operador}'...")
        if len(inputs_visibles) >= 3:
            escribir_elemento_humano(driver, inputs_visibles[2], operador)
        elif len(inputs_visibles) >= 2 and not input_pass:
            escribir_elemento_humano(driver, inputs_visibles[1], operador)

        textareas = driver.find_elements(By.TAG_NAME, "textarea")
        log_msg(f"Asignando Motivo: '{motivo_final}'...")
        if textareas:
            escribir_elemento_humano(driver, textareas[0], motivo_final)

        log_msg("Enviando autorización al sistema...")
        time.sleep(0.5)

        xpath_btn = "//button[contains(translate(text(), 'PERMITIR ACCESO', 'permitir acceso'), 'permitir acceso')]"
        elementos = driver.find_elements(By.XPATH, xpath_btn)
        btn_target = [e for e in elementos if e.is_displayed()]
        if btn_target:
            driver.execute_script("arguments[0].click();", btn_target[0])

        time.sleep(2)
        errores_alert = driver.find_elements(By.XPATH, "//*[contains(@class, 'error') or contains(@class, 'alert-danger') or contains(text(), 'incorrecta') or contains(text(), 'inválido')]")
        mensajes_error = [e.text for e in errores_alert if e.is_displayed() and e.text.strip()]

        if mensajes_error:
            log_msg(f"❌ ERROR DETECTADO: {mensajes_error[0]}")
            return False, mensajes_error[0]
        else:
            log_msg("✅ ACCESO AUTORIZADO CORRECTAMENTE.")
            registrar_en_historial(usuario, dominio_ruta, operador, motivo_final)
            return True, "Acceso concedido correctamente"

    except Exception as e:
        err_msg = str(e).split("\n")[0]
        log_msg(f"❌ ERROR: {err_msg}")
        return False, err_msg
    finally:
        if driver:
            driver.quit()

# --- PANTALLA 1: LOGIN (CON VALIDACIÓN ACTIVA) ---
def vista_login():
    st.markdown("<h2 style='text-align: center;'>🔑 Inicio de Sesión CHESS ERP</h2>", unsafe_allow_html=True)
    st.markdown("---")
    
    with st.form("login_form"):
        usr = st.text_input("Usuario ERP")
        pwd = st.text_input("Contraseña ERP", type="password")
        srv = st.text_input("Servidor ERP para validar (URL/Dominio):", value="codenoa.chesserp.com/AR467")
        
        submit = st.form_submit_button("🔑 INICIAR SESIÓN", use_container_width=True)
        
        if submit:
            if usr and pwd and srv:
                with st.spinner("Verificando credenciales con el ERP..."):
                    valido, msg = validar_credenciales_erp(usr, pwd, srv)
                    if valido:
                        st.session_state.autenticado = True
                        st.session_state.usuario = usr
                        st.session_state.password = pwd
                        st.rerun()
                    else:
                        st.error(f"❌ Acceso Denegado: {msg}")
            else:
                st.warning("Por favor complete todos los campos (Usuario, Contraseña y Servidor).")

# --- PANTALLA 2: PRINCIPAL ---
def vista_principal():
    st.sidebar.title(f"👤 {st.session_state.usuario}")
    if st.sidebar.button("Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

    st.title("🔓 Gestor de Autorización CHESS ERP")
    
    txt_mensaje = st.text_area(
        "Pegue el mensaje de solicitud:",
        value="Roy Topping, 14 min\nURL: https://codenoa.chesserp.com/AR467\nTicket: #512918\nMotivo: Gerente que no aparece",
        height=120
    )

    if st.button("🔍 PROCESAR MENSAJE", use_container_width=True):
        extraer_y_actualizar(txt_mensaje)
        st.rerun()

    if st.session_state.in_dom == "No detectado":
        extraer_y_actualizar(txt_mensaje)

    st.markdown("---")

    st.markdown("### 📋 Datos Detectados (Editables)")
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

    if st.button("🔓 PERMITIR ACCESO EN CHESS ERP", type="primary", use_container_width=True):
        if not dominio_final or dominio_final == "No detectado":
            st.error("Por favor ingrese un Servidor / Ruta URL válido.")
        else:
            with st.spinner(f"Procesando autorización para {dominio_final}..."):
                exito, msg = automatizar_web(
                    dominio_final,
                    st.session_state.usuario,
                    st.session_state.password,
                    operador_final,
                    motivo_ejecucion,
                    txt_mensaje
                )
                if exito:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ Error: {msg}")

    if st.session_state.log_ejecucion:
        st.markdown("#### 📜 Estado de Ejecución")
        st.code("\n".join(st.session_state.log_ejecucion), language="bash")

    with st.expander("📜 Ver Historial de Autorizaciones"):
        if os.path.exists(ARCHIVO_HISTORIAL):
            with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
                st.text(f.read())
        else:
            st.info("Aún no hay registros en el historial.")

# --- EJECUCIÓN PRINCIPAL ---
if not st.session_state.autenticado:
    vista_login()
else:
    vista_principal()