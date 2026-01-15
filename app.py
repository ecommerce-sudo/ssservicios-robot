import streamlit as st
import requests
import re
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ 1. CONFIGURACIÓN Y SECRETOS
# ==========================================
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

# ETIQUETAS QUE USARÁ EL ROBOT PARA MOVER PEDIDOS DE PESTAÑA
TAG_PENDIENTE = "#PENDIENTE_PAGO"
TAG_APROBADO = "#APROBADO"

if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}

# ==========================================
# 🔌 2. FUNCIONES DE CONEXIÓN (API)
# ==========================================
def solo_numeros(texto):
    if texto is None: return ""
    return re.sub(r'\D', '', str(texto))

def consultar_api_aria_id(cliente_id):
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get(f"{ARIA_URL_BASE}/cliente/{cliente_id}", headers=headers, timeout=5)
        if res.status_code == 200:
            d = res.json()
            if isinstance(d, list): return d
            if isinstance(d, dict): return [d]
        return []
    except: return []

def consultar_api_aria(params):
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get(f"{ARIA_URL_BASE}/clientes", headers=headers, params=params, timeout=8)
        if res.status_code == 200:
            d = res.json()
            if isinstance(d, dict) and "data" in d: return d["data"]
            if isinstance(d, list): return d
            if isinstance(d, dict): return [d]
        return []
    except: return []

def obtener_pedidos(estado="open"):
    # Traemos más pedidos (100) para asegurar que llenamos las pestañas
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders?status={estado}&per_page=100"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    try:
        res = requests.get(url, headers=headers)
        return res.json() if res.status_code == 200 else []
    except: return []

# --- FUNCIONES DE ACCIÓN EN TIENDANUBE ---

def actualizar_etiqueta(id_pedido, nota_actual, etiqueta_poner, etiqueta_sacar=None):
    """Agrega una etiqueta y borra otra (opcional) para mover de bandeja."""
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {
        'Authentication': f'bearer {TN_TOKEN}', 
        'User-Agent': TN_USER_AGENT,
        'Content-Type': 'application/json'
    }
    
    nota_str = str(nota_actual) if nota_actual is not None else ""
    
    # 1. Sacar etiqueta vieja (si existe)
    if etiqueta_sacar:
        nota_str = nota_str.replace(etiqueta_sacar, "")
    
    # 2. Poner etiqueta nueva (si no está ya puesta)
    if etiqueta_poner and etiqueta_poner not in nota_str:
        nota_str = f"{nota_str} {etiqueta_poner}"
    
    nota_final = nota_str.strip()
    requests.put(url, headers=headers, json={"owner_note": nota_final})

def marcar_pagado_tn(id_pedido):
    """AVISA A TIENDANUBE QUE SE PAGÓ (Libera stock, cambia a 'paid')"""
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {
        'Authentication': f'bearer {TN_TOKEN}', 
        'User-Agent': TN_USER_AGENT,
        'Content-Type': 'application/json'
    }
    requests.put(url, headers=headers, json={"payment_status": "paid"})

def cancelar_orden_tn(id_pedido):
    """CANCELA LA ORDEN REALMENTE (Devuelve Stock, cambia a 'cancelled')"""
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}/cancel"
    headers = {
        'Authentication': f'bearer {TN_TOKEN}', 
        'User-Agent': TN_USER_AGENT,
        'Content-Type': 'application/json'
    }
    # Enviamos razón: 'other' (Otros motivos)
    requests.post(url, headers=headers, json={"reason": "other"})

# ==========================================
# 📧 3. GESTOR DE CORREOS
# ==========================================
def enviar_notificacion(email_cliente, nombre_cliente, escenario, datos_extra={}):
    try:
        SMTP_SERVER = st.secrets["email"]["smtp_server"]
        SMTP_PORT = st.secrets["email"]["smtp_port"]
        SMTP_USER = st.secrets["email"]["smtp_user"]
        SMTP_PASS = st.secrets["email"]["smtp_password"]
    except:
        st.warning("⚠️ Faltan datos de email en Secrets.")
        return False

    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = email_cliente
    
    if escenario == 1: # RECHAZADO (Invitación a pagar)
        msg['Subject'] = "Información importante sobre tu pedido en SSServicios"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        Muchas gracias por tu compra.<br><br>
        Te informamos que por el momento no es posible procesar la financiación a través de tu factura de servicios.<br><br>
        ¡No te preocupes! <b>Reservamos tu pedido</b> para que puedas completarlo abonando con <b>tarjeta o transferencia</b>. Si deseas hacerlo, respóndenos este correo.<br><br>
        Saludos,<br>El equipo de SSServicios
        """
    elif escenario == 2: # DIFERENCIA
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        
        # ⚠️⚠️⚠️ ¡EDITA TUS DATOS AQUÍ! ⚠️⚠️⚠️
        alias = "TU.ALIAS.AQUI" 
        cbu = "0000000000000000000000" 
        
        msg['Subject'] = "Acción requerida: Tu pedido en SSServicios (Cupo Disponible)"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        ¡Buenas noticias! Tienes un cupo de <b>${cupo:,.0f}</b> para financiar tu compra.<br><br>
        Para aprobar el envío, necesitamos que abones la diferencia de <b>${dif:,.0f}</b>.<br><br>
        <b>Datos transferencia:</b><br>Alias: {alias}<br>CBU: {cbu}<br><br>
        Por favor, responde con el comprobante.<br><br>
        Saludos,<br>El equipo de SSServicios
        """
    elif escenario == 3: # APROBADO
        msg['Subject'] = "¡Felicitaciones! Tu compra fue aprobada ✅"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        Confirmamos que tu solicitud de financiación ha sido <b>aprobada exitosamente</b>.<br><br>
        El importe se verá en tu próxima factura en <b>3 cuotas sin interés</b>.<br><br>
        Ya estamos preparando tu pedido.<br><br>
        Saludos,<br>El equipo de SSServicios
        """
    else: return False

    msg.attach(MIMEText(cuerpo, 'html'))
    try:
        if SMTP_PORT == 465: server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, email_cliente, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"❌ Error envío: {e}")
        return False

# ==========================================
# 🧠 4. LÓGICA DE BÚSQUEDA
# ==========================================
def buscar_cliente_cascada(nombre_tn, dni_tn, nota_tn):
    nota_segura = str(nota_tn) if nota_tn is not None else ""
    ids_en_nota = re.findall(r'\b\d{3,7
