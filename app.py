import streamlit as st
import requests
import re
import smtplib
import time
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import streamlit.components.v1 as components

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

# ETIQUETAS
TAG_PENDIENTE = "#PENDIENTE_PAGO"
TAG_APROBADO = "#APROBADO"

# === 🛡️ CUPOS DE RESPALDO ===
# Si la API devuelve 0 o NULL, el robot usa estos valores según la categoría
CUPOS_POR_CATEGORIA = {
    1: 50000.0,
    2: 150000.0,
    3: 300000.0,
    4: 500000.0,
    "DEFAULT": 100000.0
}

if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}

# ==========================================
# 🧠 CEREBRO DE CROSS-SELLING
# ==========================================
PERFILES_INTERES = {
    "GAMING": {
        "keywords": ["gamer", "juego", "playstation", "ps4", "ps5", "joystick", "rtx", "teclado", "mecanico", "redragon", "pc", "mouse"],
        "items": [
            {"link": "https://ssstore.com.ar/productos/mouse-cerberus-redragon-m703/", "foto": ""},
            {"link": "https://ssstore.com.ar/productos/auricular-vincha-cronus-redragon-h211w-rgb/", "foto": ""},
            {"link": "https://ssstore.com.ar/productos/teclado-aditya-redragon-k513-rgb-sin-n/", "foto": ""}
        ]
    },
    "CONECTIVIDAD": {
        "keywords": ["starlink", "router", "antena", "wifi", "ubiquiti", "internet", "mesh", "cable", "red"],
        "items": [
            {"link": "https://ssstore.com.ar/productos/router-wifi-huaweii-ax2s-ws700v2/", "foto": ""},
            {"link": "https://ssstore.com.ar/productos/cable-starlink-mini-usb-c-a-fuente-portatil-usa-tu-antena-con-power-bank-n9thq/", "foto": ""},
            {"link": "https://ssstore.com.ar/productos/router-mesh-tp-link-deco-xe75-wifi-6e-ax5400-blanco-negro-1u/", "foto": ""}
        ]
    },
    "MOVILIDAD": {
        "keywords": ["samsung", "iphone", "motorola", "celular", "xiaomi", "smartphone", "apple", "android"],
        "items": [
            {"link": "https://ssstore.com.ar/productos/cable-foxbox-pixel-100w-con-display-lcd-usb-c-a-usb-c-egdem/", "foto": ""},
            {"link": "https://ssstore.com.ar/productos/cargador-de-auto-foxbox-way-qc-3-0-30w-carga-rapida-qualcomm-rfgoa/", "foto": ""},
            {"link": "https://ssstore.com.ar/productos/cargador-foxbox-mega-30w-gan-negro-para-iphone-cable-lightning-j8nie/", "foto": ""}
        ]
    },
    "HOGAR": {
        "keywords": ["tv", "smart", "televisor", "google", "android tv", "4k", "led", "ups", "casa"],
        "items": [
            {"link": "https://ssstore.com.ar/productos/auriculares-inalambricos-foxbox-clarity-negro-control-tactil-y-asistente-de-voz-qi0kh/", "foto": ""},
            {"link": "https://ssstore.com.ar/productos/ups-marsriva-kp2-ultra-16000mah-5v-12v-bivolt/", "foto": ""},
            {"link": "https://ssstore.com.ar/productos/freidora-de-aire-foxbox-aeris-6l-digital-1500w-sin-aceite-yufou/", "foto": ""}
        ]
    }
}

# ==========================================
# 🔌 2. FUNCIONES DE CONEXIÓN
# ==========================================

def safe_float(value):
    try:
        if value is None or value == "": return 0.0
        clean_val = str(value).replace("$", "").replace(" ", "").replace(",", ".")
        return float(clean_val)
    except: return 0.0

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
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders?status={estado}&per_page=100"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    try:
        res = requests.get(url, headers=headers)
        return res.json() if res.status_code == 200 else []
    except: return []

@st.cache_data(ttl=3600)
def obtener_info_desde_item(item_dict):
    link_producto = item_dict.get('link', '#')
    foto_manual = item_dict.get('foto', '')
    resultado = {
        'nombre': "Producto Recomendado", 'precio': 0,
        'foto': foto_manual if foto_manual else "https://via.placeholder.com/150?text=Ver+Web",
        'url': link_producto
    }
    try:
        slug = link_producto.strip("/").split("/")[-1]
        nombre_busqueda = slug.replace("-", " ") 
        url = f"https://api.tiendanube.com/v1/{TN_ID}/products"
        params = {'q': nombre_busqueda, 'per_page': 1}
        headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200 and len(res.json()) > 0:
            p = res.json()[0]
            img_api = ""
            if p.get('images'): img_api = p['images'][0]['src']
            resultado['nombre'] = p['name']['es']
            resultado['precio'] = float(p.get('price', 0)) if p.get('price') else 0
            if not foto_manual: resultado['foto'] = img_api
    except: pass
    return resultado

def generar_recomendaciones(nombre_producto_comprado):
    nombre_lower = str(nombre_producto_comprado).lower()
    perfil_detectado = "HOGAR" 
    for perfil, datos in PERFILES_INTERES.items():
        for kw in datos['keywords']:
            if kw in nombre_lower:
                perfil_detectado = perfil
                break
        if perfil_detectado != "HOGAR": break
    items_objetivo = PERFILES_INTERES[perfil_detectado]['items']
    productos_finales = []
    for item in items_objetivo:
        info = obtener_info_desde_item(item)
        if info: productos_finales.append(info)
    return productos_finales, perfil_detectado

# ==========================================
# 📧 3. GESTOR DE CORREOS
# ==========================================

# Genera HTML y Asunto (Para Preview y Envío)
def generar_html_correo(nombre_cliente, escenario, datos_extra={}):
    NUMERO_WHATSAPP = "5491153748291" 
    id_visual = datos_extra.get('id_visual', 'S/N')
    
    # === CROSS SELLING ===
    html_cross = ""
    nombre_prod_base = datos_extra.get('nombre_producto_base', '')
    
    if nombre_prod_base:
        recomendados, perfil = generar_recomendaciones(nombre_prod_base)
        if recomendados:
            filas = ""
            for p in recomendados:
                precio_fmt = f"${p['precio']:,.0f}" if p['precio'] > 0 else "Ver Precio"
                filas += f"""<td style="width:33%;padding:10px;text-align:center;border:1px solid #f0f0f0;border-radius:8px;background:#fff;"><a href="{p['url']}" style="text-decoration:none;color:#333;display:block;"><img src="{p['foto']}" alt="{p['nombre']}" style="width:100%;max-width:120px;height:120px;object-fit:contain;margin-bottom:10px;"><p style="font-size:13px;margin:0 0 5px;height:36px;overflow:hidden;"><strong>{p['nombre']}</strong></p><p style="color:#28a745;font-weight:bold;">{precio_fmt}</p><div style="background:#007bff;color:white;padding:6px 10px;border-radius:4px;font-size:12px;display:inline-block;">VER OFERTA</div></a></td>"""
            html_cross = f"""<div style="background-color:#f9f9f9;padding:20px;border-radius:10px;margin-top:30px;border:1px solid #eee;"><h3 style="text-align:center;color:#444;margin-top:0;">🔥 Recomendados ({perfil}) 🔥</h3><table width="100%" cellpadding="5" cellspacing="5" style="border-collapse:separate;border-spacing:10px;"><tr>{filas}</tr></table></div>"""

    # === CUERPO ===
    cuerpo_txt = ""
    asunto = ""
    
    if escenario == 1: # RECHAZADO
        asunto = f"Actualización pedido #{id_visual}"
        cuerpo_txt = f"<p>Hola <strong>{nombre_cliente}</strong>, tu pedido <strong>#{id_visual}</strong> no pudo ser financiado por falta de cupo. Reservamos tu pedido 24hs. Respondé para pagar con otro medio.</p>"
    
    elif escenario == 2: # DIFERENCIA
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        link_ws = f"https://wa.me/{NUMERO_WHATSAPP}?text={urllib.parse.quote(f'Hola, envío diferencia pedido #{id_visual}')}"
        asunto = f"Finalizá tu pedido #{id_visual}"
        cuerpo_txt = f"<p>Hola <strong>{nombre_cliente}</strong>, aprobamos parcialmente tu financiación (Cupo: <strong>${cupo:,.0f}</strong>).<br>Resta abonar: <strong>${dif:,.0f}</strong>.</p><p>Transferencia: BBVA | CBU: 0170272120000001018527<br><a href='{link_ws}'>ENVIAR COMPROBANTE</a></p>"
    
    elif escenario == 3: # APROBADO
        asunto = f"¡Aprobado! Pedido #{id_visual} ✅"
        cuerpo_txt = f"<p>Hola <strong>{nombre_cliente}</strong>, confirmamos que la financiación de tu pedido <strong>#{id_visual}</strong> fue <strong>APROBADA</strong>.</p>"

    html_final = f"""<div style="font-family:Helvetica,Arial;color:#333;line-height:1.6;max-width:600px;margin:auto;">{cuerpo_txt}{html_cross}<br><hr style="border:0;border-top:1px solid #eee"><small style="color:#999">SSServicios Team</small></div>"""
    return asunto, html_final

def enviar_notificacion(email_cliente, nombre_cliente, escenario, datos_extra={}):
    asunto, html_content = generar_html_correo(nombre_cliente, escenario, datos_extra)
    try:
        SMTP_SERVER = st.secrets["email"]["smtp_server"]
        SMTP_PORT = st.secrets["email"]["smtp_port"]
        SMTP_USER = st.secrets["email"]["smtp_user"]
        SMTP_PASS = st.secrets["email"]["smtp_password"]
        
        msg = MIMEMultipart()
        msg['From'] = f"SSServicios <{SMTP_USER}>"
        msg['To'] = email_cliente
        msg['Subject'] = asunto
        msg.attach(MIMEText(html_content, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, email_cliente, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"Error mail: {e}")
        return False

# --- FUNCIONES ACCIÓN TN ---
def aprobar_orden_completa(id_pedido, nota_actual, etiqueta_poner, etiqueta_sacar=None):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT, 'Content-Type': 'application/json'}
    nota_str = str(nota_actual) if nota_actual is not None else ""
    if etiqueta_sacar: nota_str = nota_str.replace(etiqueta_sacar, "")
    if etiqueta_poner and etiqueta_poner not in nota_str: nota_str = f"{nota_str} {etiqueta_poner}"
    payload = {"payment_status": "paid", "owner_note": nota_str.strip()}
    try:
        res = requests.put(url, headers=headers, json=payload)
        return res.status_code == 200 or res.status_code == 422
    except: return False

def actualizar_etiqueta(id_pedido, nota_actual, etiqueta_poner, etiqueta_sacar=None):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT, 'Content-Type': 'application/json'}
    nota_str = str(nota_actual) if nota_actual is not None else ""
    if etiqueta_sacar: nota_str = nota_str.replace(etiqueta_sacar, "")
    if etiqueta_poner and etiqueta_poner not in nota_str: nota_str = f"{nota_str} {etiqueta_poner}"
    requests.put(url, headers=headers, json={"owner_note": nota_str.strip()})

def cancelar_orden_tn(id_pedido):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}/cancel"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT, 'Content-Type': 'application/json'}
    requests.post(url, headers=headers, json={"reason": "other"})

# ==========================================
# 🧠 4. UI Y FLUJO
# ==========================================
def buscar_cliente_cascada(nombre_tn, dni_tn, nota_tn):
    nota_segura = str(nota_tn) if nota_tn is not None else ""
    ids_en_nota = re.findall(r'\b\d{3,7}\b', nota_segura)
    for pid in ids_en_nota:
        res = consultar_api_aria_id(pid)
        if res and res[0].get('cliente_id'): return res[0], f"✅ ID {pid}"
    
    dni_input = solo_numeros(dni_tn)
    numeros = [dni_input] if len(dni_input) > 5 else []
    for n in numeros:
        res = consultar_api_aria({'ident': n})
        if res: return res[0], f"✅ Doc {n}"
        res_q = consultar_api_aria({'q': n})
        if res_q: return res_q[0], f"✅ Doc Q {n}"

    if len(nombre_tn.split()) > 1:
        res = consultar_api_aria({'q': nombre_tn.split()[-1]})
        if res: return res[0], "✅ Apellido"
    return None, "❌ No encontrado"

def extraer_productos(pedido):
    return ", ".join([f"{i.get('name')} ({i.get('quantity')})" for i in pedido.get('products', [])])

# --- APP ---
st.set_page_config(page_title="Gestor SSServicios", page_icon="🤖", layout="wide")
st.title("🤖 Gestor de Ventas Contrafactura")

if st.sidebar.button("🔄 Actualizar Todo"): st.rerun()

tab_nuevos, tab_pendientes, tab_aprobados, tab_cancelados = st.tabs(["📥 NUEVOS", "⏳ PENDIENTES", "✅ APROBADOS", "🚫 CANCELADOS"])

with st.spinner('Sincronizando...'):
    pedidos_todos = obtener_pedidos("open") + obtener_pedidos("closed")

# --- PESTAÑA: NUEVOS ---
with tab_nuevos:
    p_nuevos = [p for p in pedidos_todos if p['status']=='open' and p['payment_status']=='pending' and TAG_PENDIENTE not in (p.get('owner_note') or "") and TAG_APROBADO not in (p.get('owner_note') or "")]
    
    if not p_nuevos: st.info("✅ Bandeja limpia.")
    for p in p_nuevos:
        id_real = p['id']
        id_visual = p.get('number', id_real)
        nom = p['customer']['name']
        mail = p['customer'].get('email')
        total = float(p['total'])
        nota = p.get('owner_note') or ""
        prod_prin = p['products'][0]['name'] if p['products'] else ""

        with st.expander(f"🆕 #{id_visual} | {nom} | ${total:,.0f}", expanded=True):
            if st.button(f"🔍 Analizar", key=f"an_{id_real}"): st.session_state['analisis_activo'][id_real] = True
            
            if st.session_state['analisis_activo'].get(id_real):
                st.markdown("---")
                cli, msg = buscar_cliente_cascada(nom, p['customer'].get('identification'), nota)
                
                if not cli:
                    st.error(msg)
                    with st.expander("Ver Datos Crudos"): st.write(cli)
                else:
                    # LÓGICA DE CUPO (RESPALDO + API)
                    cupo = safe_float(cli.get('clienteScoringFinanciable'))
                    origen = "API"
                    if cupo == 0:
                        cat = int(cli.get('cliente_categoria', 0) or 0)
                        cupo = CUPOS_POR_CATEGORIA.get(cat, CUPOS_POR_CATEGORIA["DEFAULT"])
                        origen = f"Respaldo Cat {cat}"
                    
                    meses = int(cli.get('cliente_meses_atraso', 0) or 0)
                    
                    st.success(f"{msg}")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Cupo", f"${cupo:,.0f}", help=origen)
                    c2.metric("Pedido", f"${total:,.0f}")
                    c3.metric("Mora", f"{meses}m")

                    # DETERMINAR ESCENARIO
                    escenario_calc = 0
                    if meses > 0: escenario_calc = 1
                    elif total <= cupo: escenario_calc = 3
                    else: escenario_calc = 2
                    
                    dif_calc = total - cupo

                    # PREVIEW EMAIL
                    with st.expander("👁️ Ver Preview del Email"):
                        asunto_prev, html_prev = generar_html_correo(nom, escenario_calc, {
                            'cupo': cupo, 'diferencia': dif_calc, 
                            'id_visual': id_visual, 'nombre_producto_base': prod_prin
                        })
                        st.markdown(f"**Asunto:** {asunto_prev}")
                        components.html(html_prev, height=400, scrolling=True)

                    # BOTONES DE ACCIÓN
                    if escenario_calc == 1:
                        st.error("⛔ Cliente con MORA.")
                        if st.button("📧 Rechazar", key=f"btn_{id_real}"):
                            enviar_notificacion(mail, nom, 1, {'id_visual': id_visual, 'nombre_producto_base': prod_prin})
                            actualizar_etiqueta(id_real, nota, TAG_PENDIENTE)
                            st.rerun()
                    
                    elif escenario_calc == 3:
                        st.success("🚀 APROBABLE")
                        if st.button("📧 APROBAR", key=f"btn_{id_real}"):
                            aprobar_orden_completa(id_real, nota, TAG_APROBADO)
                            enviar_notificacion(mail, nom, 3, {'id_visual': id_visual, 'nombre_producto_base': prod_prin})
                            st.balloons()
                            time.sleep(2)
                            st.rerun()
                    
                    elif escenario_calc == 2:
                        st.warning(f"⚠️ Faltan ${dif_calc:,.0f}")
                        if st.button("📧 Pedir Diferencia", key=f"btn_{id_real}"):
                            enviar_notificacion(mail, nom, 2, {'cupo': cupo, 'diferencia': dif_calc, 'id_visual': id_visual, 'nombre_producto_base': prod_prin})
                            actualizar_etiqueta(id_real, nota, TAG_PENDIENTE)
                            st.rerun()

                if st.button("Cerrar", key=f"x_{id_real}"):
                    del st.session_state['analisis_activo'][id_real]
                    st.rerun()

# --- PESTAÑA: PENDIENTES ---
with tab_pendientes:
    p_pend = [p for p in pedidos_todos if p['status']=='open' and p['payment_status']=='pending' and TAG_PENDIENTE in (p.get('owner_note') or "")]
    st.write(f"**{len(p_pend)}** esperando.")
    for p in p_pend:
        id_real = p['id']
        id_visual = p.get('number', id_real)
        nom = p['customer']['name']
        prod_prin = p['products'][0]['name'] if p['products'] else ""
        
        with st.expander(f"⏳ #{id_visual} | {nom}", expanded=True):
            c_ok, c_kill = st.columns(2)
            if c_ok.button("✅ Confirmar + Mail", key=f"pok_{id_real}"):
                if aprobar_orden_completa(id_real, p.get('owner_note'), TAG_APROBADO, TAG_PENDIENTE):
                    enviar_notificacion(p['customer'].get('email'), nom, 3, {'id_visual': id_visual, 'nombre_producto_base': prod_prin})
                    st.toast("Confirmado!"); time.sleep(2); st.rerun()
            if c_kill.button("🚫 Cancelar", key=f"kill_{id_real}"):
                cancelar_orden_tn(id_real)
                st.toast("Cancelado."); time.sleep(2); st.rerun()

# --- PESTAÑA: APROBADOS ---
with tab_aprobados:
    p_ok = [p for p in pedidos_todos if ((p.get('payment_status')=='paid' or TAG_APROBADO in (p.get('owner_note') or "")) and p['status']!='cancelled')]
    st.write(f"**{len(p_ok)}** aprobados.")
    for p in p_ok[:20]:
        icono = "🟢" if p.get('payment_status')=='paid' else "⚠️"
        st.caption(f"{icono} #{p.get('number')} - {p['customer']['name']} - ${float(p['total']):,.0f}")

# --- PESTAÑA: CANCELADOS ---
with tab_cancelados:
    p_can = [p for p in pedidos_todos if p['status']=='cancelled']
    st.write(f"**{len(p_can)}** cancelados.")
    for p in p_can[:10]: st.caption(f"🚫 #{p.get('number')} - {p['customer']['name']}")
