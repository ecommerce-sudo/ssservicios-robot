import streamlit as st
import requests
import smtplib
import time
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ 1. CONFIGURACIÓN Y SECRETOS
# ==========================================
st.set_page_config(page_title="Gestor Cobranzas SSS", layout="wide", page_icon="🤖")

try:
    TN_TOKEN = st.secrets["TN_TOKEN"]
    TN_ID = st.secrets["TN_ID"]
    ARIA_KEY = st.secrets["ARIA_KEY"]
    
    # Configuración de Correo
    SMTP_SERVER = st.secrets["email"]["smtp_server"]
    SMTP_PORT = st.secrets["email"]["smtp_port"]
    SMTP_USER = st.secrets["email"]["smtp_user"]
    SMTP_PASS = st.secrets["email"]["smtp_password"]
except Exception as e:
    st.error(f"⚠️ Error de Configuración: Faltan claves en .streamlit/secrets.toml ({e})")
    st.stop()

# Constantes Globales
TN_URL = f"https://api.tiendanube.com/v1/{TN_ID}"
HEADERS_TN = {"Authentication": f"bearer {TN_TOKEN}", "User-Agent": "RobotCobranzas (2.0)"}
ARIA_URL_BASE = "https://api.anatod.ar/api"

# Etiquetas internas
TAG_PENDIENTE = "#PENDIENTE_PAGO"
TAG_ESPERA_COMPROBANTE = "#ESPERANDO_COMPROBANTE"
TAG_APROBADO = "#APROBADO"

# Estado de sesión para guardar análisis
if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}

# ==========================================
# 🧠 2. CEREBRO DE CROSS-SELLING (BASED DATOS)
# ==========================================
PERFILES_INTERES = {
    "GAMING": {
        "keywords": ["gamer", "juego", "playstation", "ps4", "ps5", "joystick", "rtx", "teclado", "mecanico", "redragon", "pc", "mouse"],
        "items": [
            {"titulo": "Mouse Redragon M703", "link": "https://ssstore.com.ar/productos/mouse-cerberus-redragon-m703/"},
            {"titulo": "Auricular Redragon H211", "link": "https://ssstore.com.ar/productos/auricular-vincha-cronus-redragon-h211w-rgb/"}
        ]
    },
    "CONECTIVIDAD": {
        "keywords": ["starlink", "router", "antena", "wifi", "ubiquiti", "internet", "mesh", "cable", "red"],
        "items": [
            {"titulo": "Router Huawei AX2", "link": "https://ssstore.com.ar/productos/router-wifi-huaweii-ax2s-ws700v2/"},
            {"titulo": "Cable Starlink USB-C", "link": "https://ssstore.com.ar/productos/cable-starlink-mini-usb-c-a-fuente-portatil-usa-tu-antena-con-power-bank-n9thq/"}
        ]
    },
    "MOVILIDAD": {
        "keywords": ["samsung", "iphone", "motorola", "celular", "xiaomi", "smartphone", "apple", "android"],
        "items": [
            {"titulo": "Cable Foxbox 100W", "link": "https://ssstore.com.ar/productos/cable-foxbox-pixel-100w-con-display-lcd-usb-c-a-usb-c-egdem/"},
            {"titulo": "Cargador Auto QC 3.0", "link": "https://ssstore.com.ar/productos/cargador-de-auto-foxbox-way-qc-3-0-30w-carga-rapida-qualcomm-rfgoa/"}
        ]
    },
    "HOGAR": {
        "keywords": ["tv", "smart", "televisor", "google", "android tv", "4k", "led", "ups", "casa"],
        "items": [
            {"titulo": "UPS Marsriva KP2", "link": "https://ssstore.com.ar/productos/ups-marsriva-kp2-ultra-16000mah-5v-12v-bivolt/"},
            {"titulo": "Freidora Aire Foxbox", "link": "https://ssstore.com.ar/productos/freidora-de-aire-foxbox-aeris-6l-digital-1500w-sin-aceite-yufou/"}
        ]
    }
}

# ==========================================
# 📧 3. MÓDULO DE EMAILS (COMPLETO)
# ==========================================
def generar_html_cross_selling(orden):
    """Genera bloque HTML de recomendaciones basado en productos comprados"""
    productos_txt = " ".join([p['name'].lower() for p in orden['products']]).lower()
    recomendaciones = []
    
    for categoria, datos in PERFILES_INTERES.items():
        if any(kw in productos_txt for kw in datos['keywords']):
            recomendaciones.extend(datos['items'])
            break # Solo una categoría
    
    if not recomendaciones: return ""

    html_items = ""
    for item in recomendaciones[:2]: 
        html_items += f'<li><a href="{item["link"]}" style="color: #d35400; text-decoration:none; font-weight:bold;">👉 {item["titulo"]}</a></li>'
    
    return f"""
    <div style="background-color: #fff3e0; padding: 15px; border-radius: 8px; border: 1px dashed #ef6c00; margin-top: 20px;">
        <p style="margin:0 0 10px 0; font-weight:bold; color: #ef6c00;">🔥 ¡Completa tu experiencia con estos accesorios!</p>
        <ul style="margin:0; padding-left: 20px; line-height: 1.6;">{html_items}</ul>
    </div>
    """

def enviar_correo_base(destinatario, asunto, cuerpo_html):
    msg = MIMEMultipart()
    msg['From'] = f"Gestión SSServicios <{SMTP_USER}>"
    msg['To'] = destinatario
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo_html, 'html'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, destinatario, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"❌ Error SMTP: {e}")
        return False

# --- PLANTILLA 1: SOLICITAR COMPROBANTE (NUEVO) ---
def email_solicitar_comprobante(orden):
    nombre = orden['billing_name'].split()[0]
    cross_selling = generar_html_cross_selling(orden)
    
    html = f"""
    <html><body>
        <h3>Hola {nombre}, recibimos tu pedido #{orden['id']} 🚀</h3>
        <p>Seleccionaste pago por <strong>Transferencia / Depósito</strong>.</p>
        <div style="background-color: #e3f2fd; padding: 15px; border-left: 5px solid #2196F3; margin: 20px 0;">
            <strong>📝 Acción Requerida:</strong><br>
            El total es: <strong>${orden['total']}</strong>.<br>
            Por favor, responde a este correo adjuntando el comprobante para procesar el despacho.
        </div>
        {cross_selling}
        <p>Atte,<br>Equipo SSServicios</p>
    </body></html>
    """
    return enviar_correo_base(orden['customer']['email'], f"Pedido #{orden['id']} - Esperando Comprobante", html)

# --- PLANTILLA 2: APROBADO (CRÉDITO) ---
def email_aprobado(orden):
    nombre = orden['billing_name'].split()[0]
    cross_selling = generar_html_cross_selling(orden)
    
    html = f"""
    <html><body>
        <h3>¡Todo listo, {nombre}! ✅</h3>
        <p>Tu pedido <strong>#{orden['id']}</strong> fue aprobado correctamente mediante tu cuenta corriente.</p>
        <p>Pronto recibirás la notificación de envío.</p>
        {cross_selling}
        <p>Gracias por confiar en nosotros,<br>Equipo SSServicios</p>
    </body></html>
    """
    return enviar_correo_base(orden['customer']['email'], f"Pedido #{orden['id']} Aprobado", html)

# --- PLANTILLA 3: RECHAZO POR MORA ---
def email_rechazo_mora(orden, deuda):
    nombre = orden['billing_name'].split()[0]
    html = f"""
    <html><body>
        <h3>Hola {nombre}</h3>
        <p>Intentamos procesar tu pedido <strong>#{orden['id']}</strong>, pero el sistema indica una deuda pendiente.</p>
        <p>Por favor, contactate con administración para regularizar tu situación y liberar el pedido.</p>
        <p>Saludos,<br>Cobranzas SSServicios</p>
    </body></html>
    """
    return enviar_correo_base(orden['customer']['email'], f"Aviso sobre Pedido #{orden['id']}", html)

# --- PLANTILLA 4: SOLICITAR DIFERENCIA (CUPO PARCIAL) ---
def email_solicitar_diferencia(orden, diferencia):
    nombre = orden['billing_name'].split()[0]
    html = f"""
    <html><body>
        <h3>Hola {nombre}</h3>
        <p>Tu cupo disponible cubre una parte del pedido <strong>#{orden['id']}</strong>.</p>
        <div style="background-color: #fff3e0; padding: 15px; border-left: 5px solid #ff9800;">
            <strong>Saldo restante a abonar: ${diferencia}</strong><br>
            Podés abonar la diferencia por transferencia para completar la compra.
        </div>
        <p>Quedamos a la espera del comprobante por la diferencia.</p>
        <p>Saludos,<br>Equipo SSServicios</p>
    </body></html>
    """
    return enviar_correo_base(orden['customer']['email'], f"Saldo pendiente Pedido #{orden['id']}", html)

# ==========================================
# 🌐 4. FUNCIONES API (TIENDANUBE & ARIA)
# ==========================================

def get_pedidos_activos():
    """Trae pedidos OPEN. El filtro de históricos se hace post-procesamiento o por fecha"""
    # IMPORTANTE: Tiendanube a veces deja 'open' pedidos viejos si no se archivaron.
    # Traemos los últimos 50 para asegurar.
    url = f"{TN_URL}/orders?status=open&per_page=50"
    try:
        r = requests.get(url, headers=HEADERS_TN)
        return r.json()
    except Exception as e:
        st.error(f"Error conectando con Tiendanube: {e}")
        return []

def agregar_nota_tn(order_id, nota_actual, nueva_nota):
    if nueva_nota in nota_actual: return 
    url = f"{TN_URL}/orders/{order_id}"
    data = {"note": f"{nota_actual} {nueva_nota}"}
    requests.put(url, json=data, headers=HEADERS_TN)

def buscar_cliente_cascada(orden):
    """
    Algoritmo de Cascada:
    1. Busca ID Numérico en la 'Nota del cliente'
    2. Busca por DNI (si está en custom_fields)
    3. Busca por Nombre Aproximado
    """
    # 1. Búsqueda por ID en Nota
    nota_cliente = orden.get('note', '')
    match_id = re.search(r'\b(\d{4,6})\b', str(nota_cliente)) # Busca número de 4 a 6 dígitos
    if match_id:
        # AQUÍ IRÍA: return requests.get(f"{ARIA_URL_BASE}/clientes/{match_id.group(0)}").json()
        pass # Placeholder logica real

    # 2. Búsqueda por DNI/CUIT (Si existe en TN)
    doc = orden.get('customer', {}).get('identification')
    if doc:
        # AQUÍ IRÍA: return requests.get(f"{ARIA_URL_BASE}/clientes?dni={doc}").json()
        pass

    # 3. Búsqueda por Nombre (Fallback)
    # Mockup para que el código funcione sin la API real de Aria conectada ahora mismo
    # Reemplaza este return con tu llamada real a Aria
    nombre = orden['billing_name']
    return {"id": 999, "nombre": nombre, "cupo": 100000, "mora": 0} # DATOS SIMULADOS

# ==========================================
# 🖥️ 5. INTERFAZ Y LÓGICA PRINCIPAL
# ==========================================

# --- SIDEBAR (Restaurado) ---
with st.sidebar:
    st.header("🏢 SSS Gestor")
    st.markdown("---")
    if st.button("🔄 Refrescar Pedidos"):
        st.rerun()
    st.markdown("---")
    st.info("Sistema v3.0\nFull Email Module + Transferencias")

# --- CUERPO PRINCIPAL ---
st.title("Gestión de Cobranzas y Pedidos")

pedidos = get_pedidos_activos()

if not pedidos:
    st.success("✅ No hay pedidos pendientes de gestión.")
    st.stop()

# Filtro de pedidos (Excluir Cerrados/Cancelados visualmente si la API trajo basura)
pedidos_filtrados = [p for p in pedidos if p['status'] == 'open']

st.write(f"📂 Pendientes en bandeja: **{len(pedidos_filtrados)}**")

for orden in pedidos_filtrados:
    # Evitar procesar lo ya gestionado
    nota_interna = orden.get('note') or ""
    if TAG_APROBADO in nota_interna or TAG_ESPERA_COMPROBANTE in nota_interna:
        continue

    # DETECCIÓN DE TIPO DE PAGO
    gateway = orden.get('payment_details', {}).get('method', '').lower()
    es_transferencia = any(x in gateway for x in ['transferencia', 'depósito', 'bancaria', 'cuenta'])

    # CABECERA VISUAL
    titulo = f"#{orden['id']} | {orden['billing_name']} | ${orden['total']}"
    icono = "🏦" if es_transferencia else "💳"
    color_borde = "blue" if es_transferencia else "red"

    with st.expander(f"{icono} {titulo} ({gateway})", expanded=True):
        
        # ============================================================
        # FLUJO A: TRANSFERENCIA BANCARIA (SOLO PEDIR COMPROBANTE)
        # ============================================================
        if es_transferencia:
            st.info("ℹ️ Pago manual (Transferencia). No requiere análisis crediticio.")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write("**Acción:** Solicitar comprobante y marcar como 'Esperando'.")
            with col2:
                if st.button("✉️ Pedir Comprobante", key=f"btn_tr_{orden['id']}"):
                    with st.spinner("Enviando correo..."):
                        if email_solicitar_comprobante(orden):
                            agregar_nota_tn(orden['id'], nota_interna, TAG_ESPERA_COMPROBANTE)
                            st.success("Correo enviado. Pedido actualizado.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("Error al enviar.")

        # ============================================================
        # FLUJO B: CRÉDITO CONTRA-FACTURA (ANÁLISIS ARIA COMPLETO)
        # ============================================================
        else:
            if st.button("🔍 Analizar Cliente", key=f"btn_an_{orden['id']}"):
                st.session_state['analisis_activo'][orden['id']] = True
            
            if st.session_state['analisis_activo'].get(orden['id']):
                st.markdown("#### 📊 Situación Financiera")
                
                # 1. Buscar Cliente (Cascada)
                cliente = buscar_cliente_cascada(orden)
                
                if not cliente:
                    st.error("❌ Cliente no encontrado en BD Aria (ID/DNI/Nombre). Revisar manualmente.")
                else:
                    # 2. Mostrar Semáforos
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Cupo Disponible", f"${cliente['cupo']}")
                    c2.metric("Total Pedido", f"${orden['total']}")
                    mora_color = "inverse" if cliente['mora'] > 0 else "normal"
                    c3.metric("Días Mora", f"{cliente['mora']} días", delta_color=mora_color)
                    
                    # 3. Acciones de Decisión
                    total = float(orden['total'])
                    cupo = float(cliente['cupo'])
                    mora = int(cliente['mora'])
                    
                    st.divider()
                    
                    # CASO MORA
                    if mora > 0:
                        st.error("🚫 CLIENTE CON DEUDA VENCIDA")
                        if st.button("📧 Rechazar por Mora", key=f"rej_{orden['id']}"):
                            if email_rechazo_mora(orden, mora):
                                st.toast("Rechazo enviado.")
                    
                    # CASO CUPO SUFICIENTE
                    elif cupo >= total:
                        st.success("✅ APTO PARA APROBACIÓN AUTOMÁTICA")
                        if st.button("🚀 Aprobar y Notificar", key=f"apr_{orden['id']}"):
                            # Aquí llamarías a la API de TN para marcar 'paid' si quisieras
                            agregar_nota_tn(orden['id'], nota_interna, TAG_APROBADO)
                            if email_aprobado(orden):
                                st.balloons()
                                st.success("Pedido Aprobado y Cliente Notificado.")
                                time.sleep(2)
                                st.rerun()

                    # CASO CUPO INSUFICIENTE
                    else:
                        dif = total - cupo
                        st.warning(f"⚠️ CUPO PARCIAL (Faltan ${dif})")
                        if st.button(f"📧 Pedir Diferencia (${dif})", key=f"dif_{orden['id']}"):
                            if email_solicitar_diferencia(orden, dif):
                                st.toast("Solicitud de diferencia enviada.")
