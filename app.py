import streamlit as st
import streamlit.components.v1 as components
import extra_streamlit_components as stx
import re
import time
import sys
import os
import json
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from supabase import create_client, Client

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

# --- INICIALIZACIÓN DE COOKIE MANAGER ---
def get_cookie_manager():
    return stx.CookieManager()

cookie_manager = get_cookie_manager()

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

# --- VERIFICACIÓN DE SESIÓN PERSISTENTE MEDIANTE COOKIES ---
session_usr = cookie_manager.get(cookie="chess_session_usr")
session_pwd = cookie_manager.get(cookie="chess_session_pwd")

if session_usr and session_pwd and not st.session_state.autenticado:
    try:
        res = (
            supabase.table("usuarios_app")
            .select("*")
            .or_(f"usuario.eq.{session_usr},email.eq.{session_usr.lower()}")
            .eq("password", session_pwd)
            .execute()
        )
        registros = res.data or []
        if len(registros) > 0:
            st.session_state.autenticado = True
            st.session_state.usuario = registros[0]["usuario"]
            st.session_state.password = registros[0]["password"]
    except Exception:
        pass

# --- FUNCIONES AUXILIARES ---
def log_msg(msg, placeholder_log=None, estado="INFO"):
    if estado == "OK":
        badge = '[OK]'
    elif estado == "ERROR":
        badge = '[ERROR]'
    elif estado == "WARN":
        badge = '[WARN]'
    else:
        badge = '[INFO]'

    hora = datetime.now().strftime("%H:%M:%S")
    linea = f"[{hora}] {badge} {msg}"
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

def buscar_autorizacion_reciente(dominio_ruta, minutos=10):
    try:
        res = (
            supabase.table("historial_autorizaciones")
            .select("created_at, usuario, operador, dominio_ruta")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        registros = res.data or []
        tz_local = ZoneInfo("America/Argentina/Buenos_Aires")
        ahora = datetime.now(tz_local)

        dom_limpio = dominio_ruta.lower().replace("https://", "").replace("http://", "").strip().rstrip("/")

        for r in registros:
            dom_reg = (r.get("dominio_ruta") or "").lower().replace("https://", "").replace("http://", "").strip().rstrip("/")
            if dom_limpio in dom_reg or dom_reg in dom_limpio:
                fecha_raw = r.get("created_at", "")
                fecha_dt = datetime.fromisoformat(fecha_raw.replace("Z", "+00:00")).astimezone(tz_local)
                
                diferencia_minutos = (ahora - fecha_dt).total_seconds() / 60.0
                if diferencia_minutos <= minutos:
                    return {
                        "activa": True,
                        "hace_minutos": int(diferencia_minutos),
                        "usuario": r.get("usuario", "Desconocido"),
                        "operador": r.get("operador", "Desconocido"),
                        "fecha": fecha_dt.strftime("%H:%M:%S")
                    }
    except Exception as e:
        print(f"Error al verificar autorización reciente: {e}")
    return {"activa": False}

# --- GENERADOR DEL WORKER EXTERNO ---
def asegurar_script_worker():
    script_code = """import sys
import json
import re
from playwright.sync_api import sync_playwright

def run():
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "No se recibieron parámetros"}))
        return

    params = json.loads(sys.argv[1])
    dominio_ruta = params["dominio_ruta"]
    usuario = params["usuario"]
    password = params["password"]
    operador = params["operador"]
    motivo_final = params["motivo_final"]
    texto_mensaje = params["texto_mensaje"]

    if dominio_ruta.startswith("http://") or dominio_ruta.startswith("https://"):
        url_base = dominio_ruta
    else:
        contiene_puerto = re.search(r":\d+", dominio_ruta)
        es_ip = re.search(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", dominio_ruta)
        if "http://" in texto_mensaje.lower() or contiene_puerto or es_ip:
            url_base = f"http://{dominio_ruta}"
        else:
            url_base = f"https://{dominio_ruta}"

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
            context = browser.new_context(ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
            page = context.new_page()

            page.goto(url_base, timeout=30000)
            page.wait_for_timeout(2000)

            url_actual = page.url.split("#")[0].rstrip("/")
            url_admin = f"{url_actual}/#/admin"

            page.goto(url_admin, timeout=30000)
            page.wait_for_selector("#usuario, input[formcontrolname='usuario']", timeout=20000)

            script_inyect = \"\"\"
            ([selector, val]) => {
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
            }
            \"\"\"

            page.evaluate(script_inyect, ["usuario", usuario])
            page.wait_for_timeout(400)
            page.evaluate(script_inyect, ["contrasenia", password])
            page.wait_for_timeout(800)
            page.evaluate(script_inyect, ["operadorAutorizado", operador])
            page.wait_for_timeout(400)
            page.evaluate(script_inyect, ["detalle", motivo_final])
            page.wait_for_timeout(800)

            page.evaluate(\"\"\"
                () => {
                    var btn = document.querySelector('button[label="PERMITIR ACCESO"]') || document.querySelector('button.login-button') || document.querySelector('button');
                    if (btn) {
                        btn.removeAttribute('disabled');
                        btn.classList.remove('p-disabled');
                        btn.click();
                    }
                }
            \"\"\")

            page.wait_for_timeout(3000)
            page.wait_for_selector("#usuario, input[formcontrolname='usuario']", timeout=15000)

            page.evaluate(script_inyect, ["usuario", usuario])
            page.wait_for_timeout(400)
            page.evaluate(script_inyect, ["contrasenia", password])
            page.wait_for_timeout(800)

            page.evaluate(\"\"\"
                () => {
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
                }
            \"\"\")
            
            page.keyboard.press("Enter")
            page.wait_for_timeout(4000)
            browser.close()

            print(json.dumps({"success": True, "url_actual": url_actual}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

if __name__ == "__main__":
    run()
"""
    with open("runner_playwright.py", "w", encoding="utf-8") as f:
        f.write(script_code)

def automatizar_web(dominio_ruta, usuario, password, operador, motivo_final, texto_mensaje, placeholder_log):
    st.session_state.log_ejecucion = []
    
    # Instalación previa de Chromium (las dependencias OS las gestiona packages.txt)
    try:
        log_msg("Verificando/Instalando Chromium...", placeholder_log, "INFO")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        log_msg(f"Aviso en verificación de Playwright: {e}", placeholder_log, "WARN")

    asegurar_script_worker()

    params = {
        "dominio_ruta": dominio_ruta,
        "usuario": usuario,
        "password": password,
        "operador": operador,
        "motivo_final": motivo_final,
        "texto_mensaje": texto_mensaje
    }

    log_msg("Iniciando subproceso aislado de automatización...", placeholder_log, "INFO")
    
    try:
        resultado = subprocess.run(
            [sys.executable, "runner_playwright.py", json.dumps(params)],
            capture_output=True,
            text=True,
            check=True
        )
        
        salida_raw = resultado.stdout.strip()
        lineas_salida = [l for l in salida_raw.split("\n") if l.startswith("{")]
        
        if lineas_salida:
            data = json.loads(lineas_salida[-1])
            if data.get("success"):
                log_msg("ACCESO AUTORIZADO Y SESIÓN INICIADA CORRECTAMENTE EN CHESS ERP.", placeholder_log, "OK")
                registrar_en_historial(usuario, dominio_ruta, operador, motivo_final)
                return True, "Acceso e inicio de sesión completados correctamente", False, data.get("url_actual")
            else:
                err_msg = data.get("error", "Error desconocido en worker")
                log_msg(f"ERROR EN WORKER: {err_msg}", placeholder_log, "ERROR")
                return False, err_msg, False, None
        else:
            log_msg(f"Respuesta inesperada del worker: {salida_raw}", placeholder_log, "ERROR")
            return False, "Salida no válida del worker de Playwright", False, None

    except subprocess.CalledProcessError as e:
        err_out = e.stderr or e.stdout
        log_msg(f"ERROR EN SUBPROCESO: {err_out.strip()}", placeholder_log, "ERROR")
        return False, f"Subproceso fallido: {err_out.strip()}", False, None
    except Exception as e:
        log_msg(f"ERROR EN AUTOMATIZACIÓN: {e}", placeholder_log, "ERROR")
        return False, str(e), False, None

# --- PANTALLA 1: LOGIN Y REGISTRO ---
def vista_login():
    st.markdown("<h2 style='text-align: center;'>Acceso CHESS ERP</h2>", unsafe_allow_html=True)
    st.markdown("---")
    
    opcion = st.radio("Acción:", ["Iniciar Sesion", "Registrar Usuario"], horizontal=True)

    with st.form("auth_form"):
        usr_input = st.text_input("Usuario ERP", value=session_usr if session_usr else "", key="login_usr_input")
        pwd = st.text_input("Contraseña ERP", type="password", value=session_pwd if session_pwd else "", key="login_pwd_input")
        
        email_input = None
        if opcion == "Registrar Usuario":
            email_input = st.text_input("Correo electrónico", key="login_email_input")

        recordar_credenciales = st.checkbox("Recordar credenciales y mantener sesión activa", value=True)
        
        submit = st.form_submit_button("CONTINUAR", width="stretch")
        
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

                            if recordar_credenciales:
                                exp_date = datetime.now() + timedelta(days=30)
                                try:
                                    cookie_manager.set("chess_session_usr", usuario_limpio, key="set_usr", expires_at=exp_date)
                                    cookie_manager.set("chess_session_pwd", pwd, key="set_pwd", expires_at=exp_date)
                                except Exception:
                                    pass
                            else:
                                try:
                                    cookie_manager.delete("chess_session_usr", key="del_usr")
                                    cookie_manager.delete("chess_session_pwd", key="del_pwd")
                                except Exception:
                                    pass

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

    js_autofill = """data:text/html,
        <script>
            const doc = window.parent.document;
            const inputs = doc.querySelectorAll('input');
            inputs.forEach(function(input) {
                if (input.type === 'text' && !input.getAttribute('data-configured')) {
                    input.setAttribute('autocomplete', 'username');
                    input.setAttribute('name', 'username');
                    input.setAttribute('data-configured', 'true');
                }
                if (input.type === 'password' && !input.getAttribute('data-configured')) {
                    input.setAttribute('autocomplete', 'current-password');
                    input.setAttribute('name', 'password');
                    input.setAttribute('data-configured', 'true');
                }
            });
        </script>
    """
    st.iframe(js_autofill, height=0)

# --- PANTALLA 2: PRINCIPAL ---
def vista_principal():
    st.sidebar.title("Menú")
    st.sidebar.write(f"**Usuario activo:** `{st.session_state.usuario}`")
    if st.sidebar.button("🚪 Cerrar Sesión", width="stretch"):
        st.session_state.autenticado = False
        st.session_state.usuario = ""
        st.session_state.password = ""
        
        try:
            cookie_manager.delete("chess_session_usr", key="logout_usr")
        except Exception:
            pass
            
        try:
            cookie_manager.delete("chess_session_pwd", key="logout_pwd")
        except Exception:
            pass

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
        btn_procesar = st.button("⚡ PROCESAR MENSAJE", width="stretch")
    with col_borr:
        st.button("🗑️ Borrar", on_click=borrar_todo, width="stretch")

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

    btn_permitir = st.button("PERMITIR ACCESO EN CHESS ERP", type="primary", width="stretch")

    if st.session_state.url_autorizada_lista:
        st.link_button(
            "🔗 Abrir ERP Habilitado en la Web", 
            st.session_state.url_autorizada_lista, 
            width="stretch"
        )

    sesion_activa_detectada = False
    if btn_permitir and dominio_final and dominio_final != "No detectado":
        sesion_previa = buscar_autorizacion_reciente(dominio_final, minutos=10)
        if sesion_previa["activa"] and not st.session_state.get("forzar_ejecucion", False):
            sesion_activa_detectada = True
            st.warning(
                f"⚠️ **SESIÓN ACTIVA DETECTADA:** Este entorno (`{dominio_final}`) ya fue autorizado hace "
                f"**{sesion_previa['hace_minutos']} min** (a las {sesion_previa['fecha']}) por el aprobador "
                f"**{sesion_previa['usuario']}** para el operador **{sesion_previa['operador']}**."
            )
            
            col_reutilizar, col_forzar = st.columns(2)
            with col_reutilizar:
                url_directa = dominio_final if dominio_final.startswith("http") else f"https://{dominio_final}"
                st.link_button("🔗 Ir directamente al ERP", url_directa, width="stretch")
            with col_forzar:
                if st.button("⚡ Re-autorizar de todos modos", width="stretch"):
                    st.session_state["forzar_ejecucion"] = True
                    st.rerun()

    st.markdown("---")

    st.markdown("#### Estado de Ejecución")
    placeholder_log = st.empty()
    
    if st.session_state.log_ejecucion:
        placeholder_log.code("\n".join(st.session_state.log_ejecucion), language="bash")

    if btn_permitir and not sesion_activa_detectada:
        if not dominio_final or dominio_final == "No detectado":
            st.error("Por favor ingrese un Servidor / Ruta URL válido.")
        else:
            st.session_state["forzar_ejecucion"] = False
            
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

    st.markdown("---")

    with st.expander("Ver Historial de Autorizaciones"):
        col_hist_title, col_hist_btn = st.columns([3, 1])
        with col_hist_title:
            st.caption("Últimas autorizaciones registradas en la plataforma:")
        with col_hist_btn:
            if st.button("🔄 Actualizar", key="btn_refresh_hist", width="stretch"):
                st.rerun()

        try:
            res = (
                supabase.table("historial_autorizaciones")
                .select("created_at, operador, motivo, usuario, dominio_ruta")
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            registros = res.data or []
            
            if registros:
                tz_local = ZoneInfo("America/Argentina/Buenos_Aires")
                datos_tabla = []
                
                for r in registros:
                    fecha_raw = r.get("created_at", "")
                    try:
                        fecha_dt = datetime.fromisoformat(fecha_raw.replace("Z", "+00:00"))
                        fecha_local = fecha_dt.astimezone(tz_local)
                        fecha_fmt = fecha_local.strftime("%d/%m/%Y %H:%M")
                    except Exception:
                        fecha_fmt = fecha_raw[:16]

                    motivo_completo = r.get("motivo", "") or "-"
                    match_ticket = re.search(r"(#\d+)", motivo_completo)
                    
                    if match_ticket:
                        id_ticket = match_ticket.group(1)
                        motivo_limpio = re.sub(r"^#\d+\s*[-–—]?\s*", "", motivo_completo).strip()
                        motivo_limpio = motivo_limpio if motivo_limpio else "-"
                    else:
                        id_ticket = "-"
                        motivo_limpio = motivo_completo

                    datos_tabla.append({
                        "Fecha / Hora": fecha_fmt,
                        "Operador Autorizado": r.get("operador", "-"),
                        "Id Ticket": id_ticket,
                        "Motivo": motivo_limpio,
                        "Usuario Aprobador ERP": r.get("usuario", "-"),
                        "Servidor / Ruta": r.get("dominio_ruta", "-")
                    })

                st.dataframe(
                    datos_tabla,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Fecha / Hora": st.column_config.TextColumn("Fecha / Hora", width="medium"),
                        "Operador Autorizado": st.column_config.TextColumn("Operador Autorizado", width="medium"),
                        "Id Ticket": st.column_config.TextColumn("Id Ticket", width="small"),
                        "Motivo": st.column_config.TextColumn("Motivo", width="large"),
                        "Usuario Aprobador ERP": st.column_config.TextColumn("Usuario Aprobador ERP", width="small"),
                        "Servidor / Ruta": st.column_config.TextColumn("Servidor / Ruta", width="medium"),
                    }
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