import streamlit as st
import requests
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(page_title="Gestor de Cobranzas", layout="wide", page_icon="🤖")

# ==========================================
# 🔐 SECRETOS Y CONSTANTES
# ==========================================
try:
    TN_TOKEN = st.secrets["TN_TOKEN"]
    TN_ID = st.secrets["TN_ID"]
    ARIA_KEY = st.secrets["ARIA_KEY"]
    
    # Configuración de Email
    SMTP_SERVER = st.secrets["email"]["smtp_server"]
    SMTP_PORT = st.secrets["email"]["smtp_port"]
    SMTP_USER = st.secrets["email"]["smtp_user"]
    SMTP_PASS = st.secrets["email"]["smtp_password"]
except Exception as e:
    st.error(f"⚠️ Error de Configuración: Faltan claves en .streamlit/secrets.toml ({e})")
    st.stop()

TN_URL = f"https://api.tiendanube.com/v1/{TN_ID}"
HEADERS_TN = {"Authentication": f"bearer {TN_TOKEN}", "User-Agent": "RobotCobranzas (1.0)"}
ARIA_URL_BASE = "https://api.anatod.ar/api"

# Tags para ignorar pedidos ya gestionados
TAG_PENDIENTE = "#PENDIENTE_PAGO"
TAG_ESPERA_COMPROBANTE = "#ESPERANDO_COMPROBANTE"
TAG_APROBADO = "#APROBADO"

# Inicializar estado de sesión
if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}

# ==========================================
# 🧠 CEREBRO DE CROSS-SELLING
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
# 📨 FUNCIONES DE CORREO
# ==========================================
def enviar_correo(destinatario, asunto, cuerpo_html):
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
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
        st.error(f"Error enviando correo: {e}")
        return False

def generar_html_cross_selling(orden):
    productos_comprados = " ".join([p['name'].lower() for p in orden['products']]).lower()
    recomendaciones = []
    
    for categoria, datos in PERFILES_INTERES.items():
        if any(kw in productos_comprados for kw in datos['keywords']):
            recomendaciones.extend(datos['items'])
            break 
    
    if not recomendaciones: return ""

    html_items = ""
    for item in recomendaciones[:2]: 
        html_items += f'<li><a href="{item["link"]}" style="color: #d35400;">👉 {item["titulo"]}</a></li>'
    
    return f"""
    <div style="background-color: #fff3e0; padding: 10px; border: 1px dashed #ef6c00; margin-top: 15px;">
        <p style="margin:0; font-weight:bold; color: #ef6c00;">¡Completa tu experiencia!</p>
        <ul style="margin-top:5px; padding-left: 20px;">{html_items}</ul>
    </div>
    """

def enviar_mail_solicitar_comprobante(orden):
    nombre = orden['billing_name'].split()[0]
    email = orden['customer']['email']
    cross = generar_html_cross_selling(orden)
    
    asunto = f"Hola {nombre} - Esperamos tu comprobante (Pedido #{orden['id']})"
    cuerpo = f"""
    <html><body>
        <h3>¡Hola {nombre}! 👋</h3>
        <p>Recibimos tu pedido <strong>#{orden['id']}</strong>.</p>
        <div style="background-color: #e3f2fd; padding: 15px; border-left: 4px solid #2196F3;">
            <strong>🏦 Pago por Transferencia/Depósito</strong><br>
            Total: <strong>${orden['total']}</strong>.<br><br>
            Para despachar, por favor <strong>responde este mail con el comprobante</strong>.
        </div>
        {cross}
        <p>Saludos,<br>Equipo SSServicios</p>
    </body></html>
    """
    return enviar_correo(email, asunto, cuerpo)

# ==========================================
# 🌐 FUNCIONES API
# ==========================================
def get_ordenes():
    # FILTRO IMPORTANTE: status=open Y payment_status=pending
    # Esto evita traer pedidos viejos o ya pagados.
    url = f"{TN_URL}/orders"
    params = {
        "status": "open",
        "payment_status": "pending",
        "per_page": 20
    }
    try:
        r = requests.get(url, headers=HEADERS_TN, params=params)
        return r.json()
    except:
        return []

def agregar_nota_tn(order_id, nota_actual, nueva_nota):
    if nueva_nota in nota_actual: return # Evitar duplicados
    url = f"{TN_URL}/orders/{order_id}"
    data = {"note": f"{nota_actual} {nueva_nota}"}
    requests.put(url, json=data, headers=HEADERS_TN)

def buscar_cliente_aria(dato):
    # (Tu función de búsqueda original - Simulada aquí para que el código corra)
    # Reemplaza con tu lógica real de requests.get(ARIA...)
    return {"id": 123, "nombre": "Cliente Simulado", "cupo": 80000, "mora": 0}

# ==========================================
# 🖥️ SIDEBAR (PANEL IZQUIERDO RESTAURADO)
# ==========================================
with st.sidebar:
    st.header("🤖 Robot Cobranzas")
    st.info("Herramienta interna SSServicios")
    
    st.markdown("---")
    st.write("📊 **Métricas Rápidas**")
    
    # Botón de refresco manual
    if st.button("🔄 Actualizar Lista"):
        st.rerun()

    st.markdown("---")
    st.caption("v2.1 - Filtro Transferencias Activo")

# ==========================================
# 🖥️ CUERPO PRINCIPAL
# ==========================================
st.title("Gestión de Pedidos Pendientes")

pedidos = get_ordenes()

if not pedidos:
    st.success("🎉 ¡No hay pedidos pendientes de pago!")
else:
    st.write(f"Se encontraron **{len(pedidos)}** pedidos por procesar.")
    
    for orden in pedidos:
        nota_interna = orden.get('note') or ""
        
        # Filtros para no mostrar lo ya procesado
        if TAG_APROBADO in nota_interna or TAG_ESPERA_COMPROBANTE in nota_interna:
            continue

        # Lógica de detección: Transferencia vs Crédito
        gateway = orden.get('payment_details', {}).get('method', '').lower()
        es_transferencia = any(x in gateway for x in ['transferencia', 'depósito', 'bancaria', 'cuenta'])
        
        titulo = f"#{orden['id']} | {orden['billing_name']} | ${orden['total']}"
        icono = "🏦" if es_transferencia else "💳"
        
        # CONTENEDOR DE LA ORDEN
        with st.expander(f"{icono} {titulo} ({gateway})", expanded=True):
            
            # ---------------------------------------------------
            # CASO 1: TRANSFERENCIA (Solo pedir comprobante)
            # ---------------------------------------------------
            if es_transferencia:
                st.info("ℹ️ Pedido por Transferencia. No requiere análisis de cupo.")
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write("Acción: Solicitar comprobante al cliente.")
                with col2:
                    if st.button("✉️ Pedir Comprobante", key=f"btn_tr_{orden['id']}"):
                        with st.spinner("Enviando..."):
                            if enviar_mail_solicitar_comprobante(orden):
                                agregar_nota_tn(orden['id'], nota_interna, TAG_ESPERA_COMPROBANTE)
                                st.success("¡Correo enviado!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("Error al enviar")

            # ---------------------------------------------------
            # CASO 2: CRÉDITO (Tu lógica original completa)
            # ---------------------------------------------------
            else:
                if st.button("🔍 Analizar Cliente", key=f"btn_cr_{orden['id']}"):
                    st.session_state['analisis_activo'][orden['id']] = True

                if st.session_state['analisis_activo'].get(orden['id']):
                    st.markdown("#### 📊 Análisis de Crédito")
                    
                    cliente_aria = buscar_cliente_aria(orden['billing_name'])
                    
                    if not cliente_aria:
                        st.warning("Cliente no encontrado en BD.")
                    else:
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Cupo", f"${cliente_aria['cupo']}")
                        c2.metric("Total", f"${orden['total']}")
                        c3.metric("Mora", f"{cliente_aria['mora']} días")

                        total_ped = float(orden['total'])
                        cupo = float(cliente_aria['cupo'])
                        
                        if cliente_aria['mora'] > 0:
                            st.error("🚫 Rechazar por Mora")
                            # Botón rechazo...
                        elif cupo >= total_ped:
                            st.success("✅ Aprobable")
                            if st.button("Aprobar", key=f"apr_{orden['id']}"):
                                agregar_nota_tn(orden['id'], nota_interna, TAG_APROBADO)
                                st.success("Aprobado")
                                st.rerun()
                        else:
                            st.warning(f"⚠️ Falta Cupo (${total_ped - cupo})")
                            # Botón solicitar diferencia...
