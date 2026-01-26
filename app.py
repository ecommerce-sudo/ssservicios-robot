import streamlit as st
import requests
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ CONFIGURACIÓN DE PÁGINA Y SECRETOS
# ==========================================
st.set_page_config(page_title="Gestor de Cobranzas SSS", layout="wide", page_icon="🤖")

try:
    TN_TOKEN = st.secrets["TN_TOKEN"]
    TN_ID = st.secrets["TN_ID"]
    ARIA_KEY = st.secrets["ARIA_KEY"]
    SMTP_SERVER = st.secrets["email"]["smtp_server"]
    SMTP_PORT = st.secrets["email"]["smtp_port"]
    SMTP_USER = st.secrets["email"]["smtp_user"]
    SMTP_PASS = st.secrets["email"]["smtp_password"]
except Exception as e:
    st.error(f"⚠️ Error de Configuración: Faltan claves en .streamlit/secrets.toml ({e})")
    st.stop()

# Constantes
TN_URL = f"https://api.tiendanube.com/v1/{TN_ID}"
HEADERS_TN = {"Authentication": f"bearer {TN_TOKEN}", "User-Agent": "RobotCobranzas (1.0)"}
ARIA_URL_BASE = "https://api.anatod.ar/api"

TAG_PENDIENTE = "#PENDIENTE_PAGO"
TAG_ESPERA_COMPROBANTE = "#ESPERANDO_COMPROBANTE"
TAG_APROBADO = "#APROBADO"

# Inicializar estado
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
    """Analiza productos comprados e inyecta recomendaciones"""
    productos_comprados = " ".join([p['name'].lower() for p in orden['products']]).lower()
    recomendaciones = []
    
    for categoria, datos in PERFILES_INTERES.items():
        if any(kw in productos_comprados for kw in datos['keywords']):
            recomendaciones.extend(datos['items'])
            break # Solo una categoría para no saturar
    
    if not recomendaciones:
        return ""

    html_items = ""
    for item in recomendaciones[:2]: # Máximo 2 items
        html_items += f"""
        <li><a href="{item['link']}" style="color: #d35400; text-decoration: none;">👉 {item['titulo']}</a></li>
        """
    
    return f"""
    <div style="background-color: #fff3e0; padding: 10px; border: 1px dashed #ef6c00; margin-top: 15px;">
        <p style="margin:0; font-weight:bold; color: #ef6c00;">¡Completa tu experiencia!</p>
        <ul style="margin-top:5px; padding-left: 20px;">{html_items}</ul>
    </div>
    """

def enviar_mail_solicitar_comprobante(orden):
    nombre = orden['billing_name'].split()[0]
    email = orden['customer']['email']
    cross_selling = generar_html_cross_selling(orden)
    
    asunto = f"Hola {nombre} - Esperamos tu comprobante (Pedido #{orden['id']})"
    cuerpo = f"""
    <html><body>
        <h3>¡Hola {nombre}! 👋</h3>
        <p>Gracias por tu compra en SSServicios. Hemos recibido tu pedido <strong>#{orden['id']}</strong>.</p>
        
        <div style="background-color: #e3f2fd; padding: 15px; border-left: 4px solid #2196F3; margin: 10px 0;">
            <strong>🏦 Pago por Transferencia/Depósito</strong><br>
            El total es: <strong>${orden['total']}</strong>.<br><br>
            Para procesar el envío, por favor <strong>responde a este correo adjuntando el comprobante de pago</strong>.
        </div>
        
        {cross_selling}
        
        <p>Saludos,<br>Equipo SSServicios</p>
    </body></html>
    """
    return enviar_correo(email, asunto, cuerpo)

# ==========================================
# 🌐 FUNCIONES API (TN & ARIA)
# ==========================================
def get_ordenes():
    # Traemos 'open' (A convenir)
    url = f"{TN_URL}/orders?status=open&per_page=20" 
    try:
        r = requests.get(url, headers=HEADERS_TN)
        return r.json()
    except:
        return []

def agregar_nota_tn(order_id, nota):
    url = f"{TN_URL}/orders/{order_id}"
    data = {"note": nota}
    requests.put(url, json=data, headers=HEADERS_TN)

def buscar_cliente_aria(dato):
    # Mockup para simular Aria (Reemplazar con llamada real si tienes el endpoint exacto)
    # Aquí deberías poner tu lógica de requests.get(ARIA...)
    # Retorno simulado para pruebas:
    if "Juan" in dato: return {"id": 123, "nombre": "Juan Perez", "cupo": 100000, "mora": 0}
    return None

# ==========================================
# 🖥️ INTERFAZ PRINCIPAL
# ==========================================
st.title("🤖 Gestor de Cobranzas & Transferencias")
st.markdown("---")

if st.button("🔄 Actualizar Pedidos"):
    st.rerun()

pedidos = get_ordenes()

if not pedidos:
    st.info("No hay pedidos pendientes en estado 'Open'.")
else:
    st.success(f"Se encontraron {len(pedidos)} pedidos para procesar.")

    for orden in pedidos:
        # Filtros de seguridad (para no procesar lo ya procesado)
        nota_interna = orden.get('note') or ""
        if TAG_APROBADO in nota_interna or TAG_ESPERA_COMPROBANTE in nota_interna:
            continue

        # Detección de Tipo de Pago
        gateway = orden.get('payment_details', {}).get('method', '').lower()
        es_transferencia = any(x in gateway for x in ['transferencia', 'depósito', 'bancaria', 'cuenta'])
        
        titulo = f"#{orden['id']} | {orden['billing_name']} | ${orden['total']}"
        icono = "🏦" if es_transferencia else "💳"
        
        with st.expander(f"{icono} {titulo} ({gateway})", expanded=True):
            
            # ---------------------------------------------------------
            # CAMINO A: ES TRANSFERENCIA (SOLO PEDIR COMPROBANTE)
            # ---------------------------------------------------------
            if es_transferencia:
                st.info("ℹ️ Pedido mediante Transferencia Bancaria. No requiere análisis crediticio.")
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write("**Acción:** Enviar correo solicitando el comprobante de pago.")
                    st.caption("Al enviar, se marcará el pedido con la nota #ESPERANDO_COMPROBANTE en Tiendanube.")
                
                with col2:
                    if st.button("✉️ Pedir Comprobante", key=f"btn_tr_{orden['id']}"):
                        with st.spinner("Enviando correo..."):
                            if enviar_mail_solicitar_comprobante(orden):
                                agregar_nota_tn(orden['id'], f"{nota_interna} {TAG_ESPERA_COMPROBANTE}")
                                st.toast("✅ Correo enviado y pedido actualizado!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("Falló el envío del correo.")

            # ---------------------------------------------------------
            # CAMINO B: ES CRÉDITO (TU LÓGICA DE ANÁLISIS)
            # ---------------------------------------------------------
            else:
                if st.button("🔍 Analizar Cliente (Aria)", key=f"btn_cr_{orden['id']}"):
                    st.session_state['analisis_activo'][orden['id']] = True

                if st.session_state['analisis_activo'].get(orden['id']):
                    st.markdown("#### 📊 Análisis Financiero")
                    
                    # 1. Buscar Cliente
                    cliente_aria = buscar_cliente_aria(orden['billing_name']) # O usar DNI/ID
                    
                    if not cliente_aria:
                        st.warning("⚠️ Cliente no encontrado en Base de Datos Aria.")
                        st.stop() # O lógica de respaldo
                    
                    # 2. Mostrar Datos
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Cupo Disponible", f"${cliente_aria['cupo']}")
                    c2.metric("Total Pedido", f"${orden['total']}")
                    c3.metric("Mora", f"{cliente_aria['mora']} días", delta_color="inverse")

                    # 3. Lógica de Decisión
                    total_pedido = float(orden['total'])
                    cupo = float(cliente_aria['cupo'])
                    
                    if cliente_aria['mora'] > 0:
                        st.error("🚫 Cliente con Mora. Se recomienda rechazar.")
                        if st.button("Enviar Rechazo por Mora", key=f"rej_{orden['id']}"):
                            st.write("Enviando rechazo...") # Tu funcion de rechazo
                    
                    elif cupo >= total_pedido:
                        st.success("✅ Cupo Suficiente. Aprobable.")
                        if st.button("Aprobar Pedido", key=f"apr_{orden['id']}"):
                            agregar_nota_tn(orden['id'], f"{nota_interna} {TAG_APROBADO}")
                            # enviar_mail_aprobado(orden)...
                            st.success("Pedido Aprobado")
                            st.rerun()
                    else:
                        diferencia = total_pedido - cupo
                        st.warning(f"⚠️ Cupo Insuficiente. Faltan ${diferencia}.")
                        if st.button(f"Solicitar Diferencia (${diferencia})", key=f"dif_{orden['id']}"):
                             st.write("Solicitando diferencia...") # Tu funcion de diferencia
