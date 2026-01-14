import streamlit as st
import requests
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ 1. CONFIGURACIÓN Y SECRETOS
# ==========================================
# Intentamos cargar los secrets. Si faltan, avisamos pero no rompemos la app hasta que se necesiten.
try:
    TN_TOKEN = st.secrets["TN_TOKEN"]
    TN_ID = st.secrets["TN_ID"]
    ARIA_KEY = st.secrets["ARIA_KEY"]
except Exception as e:
    st.error(f"⚠️ Error de Configuración: Faltan claves en Secrets ({e})")
    st.stop()

# Configuración fija
TN_USER_AGENT = "RobotWeb (24705)"
ARIA_URL_BASE = "https://api.anatod.ar/api"
TAG_ESPERA = "#ESPERANDO_DIFERENCIA"

if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}

# ==========================================
# 🔌 2. FUNCIONES DE CONEXIÓN
# ==========================================
def solo_numeros(texto):
    """Limpia strings dejando solo dígitos 0-9."""
    if texto is None: return ""
    return re.sub(r'\D', '', str(texto))

def consultar_api_aria(params):
    """Consulta genérica a /clientes (q, ident)."""
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get(f"{ARIA_URL_BASE}/clientes", headers=headers, params=params, timeout=8)
        if res.status_code == 200:
            d = res.json()
            if isinstance(d, dict) and "data" in d: return d["data"]
            if isinstance(d, list): return d
            if isinstance(d, dict): return [d]
        return []
    except Exception as e:
        print(f"Error Conexión Aria: {e}")
        return []

def consultar_api_aria_id(cliente_id):
    """Consulta directa por ID (/cliente/{id})."""
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get(f"{ARIA_URL_BASE}/cliente/{cliente_id}", headers=headers, timeout=5)
        if res.status_code == 200:
            d = res.json()
            if isinstance(d, list): return d
            if isinstance(d, dict): return [d]
        return []
    except: return []

def obtener_pedidos(estado="open"):
    """Trae pedidos de Tiendanube."""
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders?status={estado}&per_page=50"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    try:
        res = requests.get(url, headers=headers)
        return res.json() if res.status_code == 200 else []
    except: return []

def actualizar_nota(id_pedido, nota_actual, nueva_etiqueta):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    if nueva_etiqueta in nota_actual: return
    nota_final = f"{nota_actual} {nueva_etiqueta}".strip()
    requests.put(url, headers=headers, json={"owner_note": nota_final})

def eliminar_etiqueta(id_pedido, nota_actual):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    nota_limpia = nota_actual.replace(TAG_ESPERA, "").strip()
    requests.put(url, headers=headers, json={"owner_note": nota_limpia})

# ==========================================
# 📧 3. GESTOR DE CORREOS (UNIVERSAL)
# ==========================================
def enviar_notificacion(email_cliente, nombre_cliente, escenario, datos_extra={}):
    # Leemos la configuración de correo desde Secrets
    try:
        SMTP_SERVER = st.secrets["email"]["smtp_server"]
        SMTP_PORT = st.secrets["email"]["smtp_port"]
        SMTP_USER = st.secrets["email"]["smtp_user"]
        SMTP_PASS = st.secrets["email"]["smtp_password"]
    except:
        st.warning("⚠️ No se pudo enviar el correo: Faltan configurar los datos [email] en Secrets.")
        return False

    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = email_cliente
    
    # Textos de correos
    if escenario == 1: # RECHAZADO
        msg['Subject'] = "Información importante sobre tu pedido en SSServicios"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        Muchas gracias por tu compra en nuestra tienda online.<br><br>
        <b>Te informamos que hemos realizado el análisis crediticio correspondiente y, por el momento, no es posible procesar la financiación de este pedido a través de tu factura de servicios; podés probar nuevamente en unos meses.</b><br><br>
        ¡No te preocupes! Si deseas continuar con la compra, puedes hacerlo abonando con <b>tarjeta de crédito, débito o transferencia bancaria</b>. Por favor, avísanos respondiendo a este correo si prefieres cambiar el medio de pago.<br><br>
        Saludos cordiales,<br>El equipo de SSServicios
        """
    elif escenario == 2: # DIFERENCIA
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        alias = "TU.ALIAS.AQUI" 
        cbu = "0000000000000000000000" 
        msg['Subject'] = "Acción requerida: Tu pedido en SSServicios (Cupo Disponible)"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        ¡Tenemos buenas noticias! Hemos verificado tu cuenta y tienes un cupo disponible de <b>${cupo:,.0f}</b> para financiar tu compra en cuotas sin interés.<br><br>
        Como el total de tu pedido supera ese monto, para aprobar el envío necesitamos que abones la diferencia de <b>${dif:,.0f}</b> mediante transferencia bancaria.<br><br>
        <b>Datos para la transferencia:</b><br><ul><li>Alias: {alias}</li><li>CBU: {cbu}</li></ul>
        Por favor, <b>responde a este correo adjuntando el comprobante de pago</b>.<br><br>
        Saludos,<br>El equipo de SSServicios
        """
    elif escenario == 3: # APROBADO
        msg['Subject'] = "¡Felicitaciones! Tu compra fue aprobada ✅"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        Te confirmamos que tu solicitud de financiación ha sido <b>aprobada exitosamente</b>.<br><br>
        El importe de tu compra se verá reflejado en tu próxima factura de SSServicios en <b>3 cuotas sin interés</b>.<br><br>
        Ya estamos preparando tu pedido.<br><br>
        Saludos,<br>El equipo de SSServicios
        """
    else: return False

    msg.attach(MIMEText(cuerpo, 'html'))
    
    # Envío Universal (Detecta SSL o TLS según puerto)
    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, email_cliente, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"❌ Error técnico enviando correo: {e}")
        return False

# ==========================================
# 🧠 4. LÓGICA DE BÚSQUEDA (CASCADA)
# ==========================================
def buscar_cliente_cascada(nombre_tn, dni_tn, nota_tn):
    # NIVEL 1: ID EN NOTA
    ids_en_nota = re.findall(r'\b\d{3,7}\b', str(nota_tn))
    for pid in ids_en_nota:
        res = consultar_api_aria_id(pid)
        if res and res[0].get('cliente_id'): return res[0], f"✅ ID {pid} (Nota)"

    # NIVEL 2: DNI / CUIT
    dni_input = solo_numeros(dni_tn)
    numeros_a_probar = []
    if len(dni_input) > 5: numeros_a_probar.append(dni_input)
    if len(dni_input) == 11: numeros_a_probar.append(dni_input[2:10])

    for n in numeros_a_probar:
        res = consultar_api_aria({'ident': n}) # Intentar exacto
        if res:
            for c in res:
                da = solo_numeros(c.get('cliente_dnicuit',''))
                if n in da or da in n: return c, f"✅ Doc {n}"
        
        res_q = consultar_api_aria({'q': n}) # Intentar texto
        if res_q:
            for c in res_q:
                da = solo_numeros(c.get('cliente_dnicuit',''))
                if n in da or da in n: return c, f"✅ Doc Q {n}"

    # NIVEL 3: APELLIDO
    partes = nombre_tn.replace(",","").split()
    if len(partes) >= 1:
        ape = partes[-1]
        if len(ape) > 3:
            res = consultar_api_aria({'q': ape})
            if res:
                if numeros_a_probar: # Validar con DNI
                    dni_obj = numeros_a_probar[-1]
                    for c in res:
                        if dni_obj in solo_numeros(c.get('cliente_dnicuit','')): return c, "✅ Apellido + DNI"
                else: # Validar con Nombre
                    ptn = set(nombre_tn.lower().split())
                    for c in res:
                        nom_aria = (str(c.get('cliente_nombre',''))+" "+str(c.get('cliente_apellido',''))).lower()
                        if len(ptn.intersection(set(nom_aria.split()))) >= 2: return c, "✅ Nombre Coincidente"

    return None, "❌ No encontrado"

def extraer_productos(pedido):
    return ", ".join([f"{i.get('name')} ({i.get('quantity')})" for i in pedido.get('products', [])])

# ==========================================
# 🖥️ 5. INTERFAZ OPERATIVA (STREAMLIT)
# ==========================================
st.set_page_config(page_title="Asistente Ventas", page_icon="🤖", layout="wide")
st.title("🤖 Asistente de Ventas Contrafactura")
st.markdown("**Bandeja Unificada:** Gestión de financiación y transferencias.")

# --- SIDEBAR (BARRA LATERAL) ---
st.sidebar.header("Panel de Control")

# === 🕵️ CONSULTA MANUAL DE CUPO (Sidebar) ===
st.sidebar.markdown("---")
st.sidebar.subheader("🔎 Consulta Rápida")
id_manual = st.sidebar.text_input("Ingresa ID Cliente:", placeholder="Ej: 7113")

if st.sidebar.button("Consultar Cupo"):
    if not id_manual:
        st.sidebar.warning("Ingresa un número.")
    else:
        with st.spinner("Buscando..."):
            res_manual = consultar_api_aria_id(id_manual)
            
            if res_manual and res_manual[0].get('cliente_id'):
                cli_m = res_manual[0]
                nom_m = f"{cli_m.get('cliente_nombre','')} {cli_m.get('cliente_apellido','')}"
                try: cupo_m = float(cli_m.get('clienteScoringFinanciable', 0))
                except: cupo_m = 0.0
                try: meses_m = int(cli_m.get('cliente_meses_atraso', 0))
                except: meses_m = 0
                
                # Mostrar resultados en Sidebar
                st.sidebar.success(f"✅ **{nom_m}**")
                st.sidebar.metric("Cupo Disponible", f"${cupo_m:,.0f}")
                
                if meses_m > 0:
                    st.sidebar.error(f"⛔ Mora: {meses_m} meses")
                else:
                    st.sidebar.info("✅ Al día")
            else:
                st.sidebar.error("❌ Cliente no existe.")
st.sidebar.markdown("---")
# ==========================================

opcion = st.sidebar.radio("Vista:", ["Nuevos (Bandeja Entrada)", "Pendientes (Diferencia)"])
if st.sidebar.button("🔄 Actualizar Bandeja"): st.rerun()

modo_pendientes = opcion == "Pendientes (Diferencia)"
estado_tn = "any" if modo_pendientes else "open"

with st.spinner('Sincronizando pedidos...'):
    pedidos_raw = obtener_pedidos(estado_tn)

pedidos_visibles = []

# --- FILTROS Y PROCESAMIENTO ---
if pedidos_raw:
    for p in pedidos_raw:
        # Filtros de limpieza (Lo que NO queremos ver)
        if p.get('payment_status') == 'paid': continue 
        if p.get('shipping_status') in ['shipped', 'picked_up']: continue
        if p.get('status') == 'cancelled' or p.get('payment_status') == 'voided': continue

        nota = p.get('owner_note') or ""
        es_espera = TAG_ESPERA in nota
        
        if modo_pendientes and es_espera: pedidos_visibles.append(p)
        elif not modo_pendientes and not es_espera: pedidos_visibles.append(p)

# --- VISUALIZACIÓN LISTADO ---
if not pedidos_visibles:
    st.info("✅ ¡Todo limpio! No hay pedidos pendientes de acción.")
else:
    st.success(f"Gestión: {len(pedidos_visibles)} pedidos pendientes.")

    for p in pedidos_visibles:
        id_p = p['id']
        nom = p['customer']['name']
        dni = p['customer'].get('identification') or "S/D"
        mail = p['customer'].get('email')
        total = float(p['total'])
        nota = p.get('owner_note', '')
        gateway = p.get('payment_details', {}).get('method', 'unknown').lower()
        prods = extraer_productos(p)

        # Distinción Visual
        es_transferencia = 'transfer' in gateway or 'wire' in gateway
        icono_pago = "🏦" if es_transferencia else "🤝"
        lbl_pago = "Transferencia" if es_transferencia else "A Convenir"

        with st.expander(f"{icono_pago} #{id_p} | {nom} | ${total:,.0f} | {lbl_pago}", expanded=True):
            c1, c2 = st.columns([1, 1])
            with c1:
                st.markdown(f"**Items:** {prods}")
                st.markdown(f"**Doc TN:** `{dni}`")
                st.markdown(f"**Nota:** {nota}")
                if es_transferencia: st.info("ℹ️ Verificar pago o intención de cuotas.")

            with c2:
                if st.button(f"🔍 Analizar Cliente", key=f"btn_{id_p}"):
                    st.session_state['analisis_activo'][id_p] = True
                
                # --- LÓGICA ANÁLISIS ---
                if st.session_state['analisis_activo'].get(id_p):
                    st.markdown("---")
                    with st.spinner("Buscando..."):
                        cli, msg = buscar_cliente_cascada(nom, dni, nota)
                    
                    if not cli:
                        st.error(msg)
                        st.warning("💡 Acción: Buscar ID manual y agregar a la nota.")
                    else:
                        id_aria = cli.get('cliente_id')
                        try: cupo = float(cli.get('clienteScoringFinanciable', 0))
                        except: cupo = 0.0
                        try: saldo = float(cli.get('cliente_saldo', 0))
                        except: saldo = 0.0
                        try: meses_atraso = int(cli.get('cliente_meses_atraso', 0))
                        except: meses_atraso = 0

                        st.success(f"{msg}")
                        st.success(f"🆔 ID RECUPERADO: **{id_aria}**")
                        
                        col_s, col_c = st.columns(2)
                        lbl_saldo = f"${saldo:,.0f}"
                        if meses_atraso > 0:
                            col_s.metric("Deuda", lbl_saldo, f"{meses_atraso} Meses Mora", delta_color="inverse")
                        else:
                            col_s.metric("Deuda", lbl_saldo, "Al día", delta_color="normal")
                        col_c.metric("Cupo Disp.", f"${cupo:,.0f}")
                        st.markdown("---")

                        # DECISIÓN
                        if meses_atraso > 0:
                            st.error(f"⛔ RECHAZADO: Tiene {meses_atraso} meses de mora.")
                            if st.button("📧 Enviar Rechazo", key=f"r_{id_p}"):
                                if enviar_notificacion(mail, nom, 1): st.success("Enviado.")
                        
                        elif total <= cupo:
                            st.success("🚀 APROBADO: Cliente OK.")
                            valor_cuota = total / 3
                            st.code(f"ID: {id_aria}\nImporte: ${valor_cuota:,.2f}\nCuotas: 3")
                            if st.button(f"✅ Cargado Manualmente", key=f"ok_{id_p}"):
                                enviar_notificacion(mail, nom, 3)
                                st.toast("Notificado.")
                                del st.session_state['analisis_activo'][id_p]
                                if modo_pendientes: eliminar_etiqueta(id_p, nota)
                                st.rerun()

                        else:
                            dif = total - cupo
                            st.warning(f"⚠️ FALTA SALDO: Diferencia ${dif:,.0f}")
                            if st.button(f"📧 Pedir Diferencia", key=f"ask_{id_p}"):
                                if enviar_notificacion(mail, nom, 2, {'cupo': cupo, 'diferencia': dif}):
                                    actualizar_nota(id_p, nota, TAG_ESPERA)
                                    st.toast("Mail enviado.")
                                    del st.session_state['analisis_activo'][id_p]
                                    st.rerun()

                            if modo_pendientes:
                                valor_cuota = cupo / 3
                                st.code(f"ID: {id_aria}\nImporte: ${valor_cuota:,.2f}\nCuotas: 3")
                                if st.button(f"✅ Cargado Cupo", key=f"ok_p_{id_p}"):
                                    enviar_notificacion(mail, nom, 3)
                                    del st.session_state['analisis_activo'][id_p]
                                    eliminar_etiqueta(id_p, nota)
                                    st.rerun()

                    if st.button("Cerrar", key=f"x_{id_p}"):
                        del st.session_state['analisis_activo'][id_p]
                        st.rerun()
