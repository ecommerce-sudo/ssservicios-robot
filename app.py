import streamlit as st
import requests
import re
import smtplib
import time
import urllib.parse
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

# ETIQUETAS
TAG_PENDIENTE = "#PENDIENTE_PAGO"
TAG_APROBADO = "#APROBADO"

if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}

# ==========================================
# 🧠 CEREBRO DE CROSS-SELLING (TUS REGLAS)
# ==========================================
# ⚠️ IMPORTANTE: PARA QUE LAS FOTOS NO SE ROMPAN, AGREGA EL CAMPO "foto" CON EL LINK DE LA IMAGEN
# Si no ponés foto, el robot intentará buscarla, pero puede fallar.

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
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders?status={estado}&per_page=100"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    try:
        res = requests.get(url, headers=headers)
        return res.json() if res.status_code == 200 else []
    except Exception as e:
        st.error(f"Error al traer pedidos: {e}")
        return []

# --- FUNCIONES INTELIGENTES PARA CROSS SELLING ---

@st.cache_data(ttl=3600)
def obtener_info_desde_item(item_dict):
    """
    Toma un diccionario {link, foto} y completa el precio y nombre desde TN.
    Si tiene foto manual, usa esa. Si no, la busca.
    """
    link_producto = item_dict.get('link', '#')
    foto_manual = item_dict.get('foto', '')
    
    # Valores por defecto
    resultado = {
        'nombre': "Producto Recomendado",
        'precio': 0,
        'foto': foto_manual if foto_manual else "https://via.placeholder.com/150?text=Ver+Web", # Placeholder simple
        'url': link_producto
    }

    try:
        # Extraer el 'handle' del link
        slug = link_producto.strip("/").split("/")[-1]
        nombre_busqueda = slug.replace("-", " ") 
        
        # Buscar en API TN para sacar precio y nombre real
        url = f"https://api.tiendanube.com/v1/{TN_ID}/products"
        params = {'q': nombre_busqueda, 'per_page': 1}
        headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
        
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200 and len(res.json()) > 0:
            p = res.json()[0]
            
            # Usamos foto de la API solo si no hay foto manual
            img_api = ""
            if p.get('images'): img_api = p['images'][0]['src']
            
            resultado['nombre'] = p['name']['es']
            resultado['precio'] = float(p.get('price', 0)) if p.get('price') else 0
            if not foto_manual:
                resultado['foto'] = img_api

    except Exception as e:
        print(f"Error buscando producto: {e}")
    
    return resultado

def generar_recomendaciones(nombre_producto_comprado):
    nombre_lower = str(nombre_producto_comprado).lower()
    perfil_detectado = "HOGAR" # Default
    
    # 1. Detección de Perfil
    for perfil, datos in PERFILES_INTERES.items():
        for kw in datos['keywords']:
            if kw in nombre_lower:
                perfil_detectado = perfil
                break
        if perfil_detectado != "HOGAR": break
    
    # 2. Obtener Items del perfil
    items_objetivo = PERFILES_INTERES[perfil_detectado]['items']
    
    # 3. Enriquecer info
    productos_finales = []
    for item in items_objetivo:
        info = obtener_info_desde_item(item)
        if info: productos_finales.append(info)
        
    return productos_finales, perfil_detectado

# --- FUNCIONES DE ACCIÓN ---

def aprobar_orden_completa(id_pedido, nota_actual, etiqueta_poner, etiqueta_sacar=None):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT, 'Content-Type': 'application/json'}
    
    nota_str = str(nota_actual) if nota_actual is not None else ""
    if etiqueta_sacar: nota_str = nota_str.replace(etiqueta_sacar, "")
    if etiqueta_poner and etiqueta_poner not in nota_str: nota_str = f"{nota_str} {etiqueta_poner}"
    nota_final = nota_str.strip()
    
    payload = {"payment_status": "paid", "owner_note": nota_final}
    
    try:
        res = requests.put(url, headers=headers, json=payload)
        if res.status_code == 200: return True
        else:
            if res.status_code == 422: 
                requests.put(url, headers=headers, json={"owner_note": nota_final})
                return True 
            st.error(f"❌ Error Tiendanube: {res.status_code} - {res.text}")
            return False
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return False

def actualizar_etiqueta(id_pedido, nota_actual, etiqueta_poner, etiqueta_sacar=None):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT, 'Content-Type': 'application/json'}
    nota_str = str(nota_actual) if nota_actual is not None else ""
    if etiqueta_sacar: nota_str = nota_str.replace(etiqueta_sacar, "")
    if etiqueta_poner and etiqueta_poner not in nota_str: nota_str = f"{nota_str} {etiqueta_poner}"
    res = requests.put(url, headers=headers, json={"owner_note": nota_str.strip()})
    if res.status_code != 200: return False
    return True

def cancelar_orden_tn(id_pedido):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}/cancel"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT, 'Content-Type': 'application/json'}
    res = requests.post(url, headers=headers, json={"reason": "other"})
    return res.status_code == 200

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
    
    NUMERO_WHATSAPP = "5491153748291" 
    id_visual = datos_extra.get('id_visual', 'S/N')
    
    # === GENERADOR DE CROSS SELLING ===
    html_cross = ""
    nombre_prod_base = datos_extra.get('nombre_producto_base', '')
    
    if nombre_prod_base:
        recomendados, perfil = generar_recomendaciones(nombre_prod_base)
        if recomendados:
            filas = ""
            for p in recomendados:
                precio_fmt = f"${p['precio']:,.0f}" if p['precio'] > 0 else "Ver Precio"
                
                # Diseño de tarjeta de producto
                filas += f"""
                <td style="width: 33%; padding: 10px; text-align: center; border: 1px solid #f0f0f0; border-radius: 8px; background: #fff;">
                    <a href="{p['url']}" style="text-decoration: none; color: #333; display: block;">
                        <img src="{p['foto']}" alt="{p['nombre']}" style="width: 100%; max-width: 120px; height: 120px; object-fit: contain; margin-bottom: 10px;">
                        <p style="font-size: 13px; margin: 0 0 5px; height: 36px; overflow: hidden; line-height: 1.2;"><strong>{p['nombre']}</strong></p>
                        <p style="color: #28a745; font-weight: bold; font-size: 14px; margin: 5px 0;">{precio_fmt}</p>
                        <div style="background: #007bff; color: white; padding: 6px 10px; border-radius: 4px; font-size: 12px; display: inline-block;">VER OFERTA</div>
                    </a>
                </td>
                """
            
            html_cross = f"""
            <div style="background-color: #f9f9f9; padding: 20px; border-radius: 10px; margin-top: 30px; border: 1px solid #eee;">
                <h3 style="text-align: center; color: #444; margin-top: 0;">🔥 Recomendados para vos ({perfil}) 🔥</h3>
                <p style="text-align: center; font-size: 13px; color: #777; margin-bottom: 15px;">Completá tu experiencia con estos accesorios:</p>
                <table width="100%" cellpadding="5" cellspacing="5" style="border-collapse: separate; border-spacing: 10px;">
                    <tr>{filas}</tr>
                </table>
            </div>
            """
    # ==================================

    msg = MIMEMultipart()
    msg['From'] = f"SSServicios <{SMTP_USER}>"
    msg['To'] = email_cliente
    style_base = "font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: auto;"
    
    if escenario == 1: # RECHAZADO
        msg['Subject'] = f"Actualización pedido #{id_visual}"
        cuerpo_txt = f"""
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p>Recibimos tu pedido <strong>#{id_visual}</strong>. Al procesar la financiación, el sistema indica que no tenés cupo disponible actualmente.</p>
            <p><strong>¡No pierdas tu compra!</strong> Reservamos tu pedido 24hs para que abones con transferencia o tarjeta.</p>
            <p>Respondé este mail para solicitar el link de pago.</p>
        """
    elif escenario == 2: # DIFERENCIA
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        texto_ws = f"Hola SSServicios, envío comprobante diferencia pedido #{id_visual}."
        link_ws = f"https://wa.me/{NUMERO_WHATSAPP}?text={urllib.parse.quote(texto_ws)}"
        
        msg['Subject'] = f"Finalizá tu pedido #{id_visual}"
        cuerpo_txt = f"""
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p>¡Buenas noticias! Aprobamos parcialmente tu financiación.<br>
            Cupo disponible: <strong>${cupo:,.0f}</strong></p>
            <div style="background: #fff3cd; padding: 15px; border-left: 5px solid #ffc107; margin: 15px 0;">
                <p style="margin:0">Resta abonar una diferencia de: <strong style="font-size:1.2em">${dif:,.0f}</strong></p>
            </div>
            <p><strong>Transferencia:</strong><br>Banco BBVA | CBU: 0170272120000001018527<br>Alias: SSSERVICIOS.MP</p>
            <p style="text-align: center; margin-top: 20px;">
                <a href="{link_ws}" style="background: #25D366; color: white; padding: 12px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">👉 ENVIAR COMPROBANTE</a>
            </p>
        """
    elif escenario == 3: # APROBADO
        msg['Subject'] = f"¡Aprobado! Pedido #{id_visual} ✅"
        cuerpo_txt = f"""
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p>Confirmamos que la financiación de tu pedido <strong>#{id_visual}</strong> fue <strong>APROBADA</strong>.</p>
            <p>El importe se verá en tu próxima factura en 3 cuotas sin interés. Ya estamos preparando tu paquete.</p>
            <p>¡Gracias por elegirnos!</p>
        """
    else: return False

    html_final = f"""<div style="{style_base}">{cuerpo_txt}{html_cross}<br><hr style="border:0;border-top:1px solid #eee"><small style="color:#999">SSServicios Team</small></div>"""
    msg.attach(MIMEText(html_final, 'html'))
    
    try:
        if SMTP_PORT == 465: server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, email_cliente, msg.as_string())
        server.quit()
        return True
    except: return False

# ==========================================
# 🧠 4. LÓGICA DE BÚSQUEDA Y FRONTEND
# ==========================================
def buscar_cliente_cascada(nombre_tn, dni_tn, nota_tn):
    nota_segura = str(nota_tn) if nota_tn is not None else ""
    ids_en_nota = re.findall(r'\b\d{3,7}\b', nota_segura)
    for pid in ids_en_nota:
        res = consultar_api_aria_id(pid)
        if res and res[0].get('cliente_id'): return res[0], f"✅ ID {pid} (Nota)"

    dni_input = solo_numeros(dni_tn)
    numeros_a_probar = []
    if len(dni_input) > 5: numeros_a_probar.append(dni_input)
    if len(dni_input) == 11: numeros_a_probar.append(dni_input[2:10])

    for n in numeros_a_probar:
        res = consultar_api_aria({'ident': n})
        if res:
            for c in res:
                da = solo_numeros(c.get('cliente_dnicuit',''))
                if n in da or da in n: return c, f"✅ Doc {n}"
        res_q = consultar_api_aria({'q': n})
        if res_q:
            for c in res_q:
                da = solo_numeros(c.get('cliente_dnicuit',''))
                if n in da or da in n: return c, f"✅ Doc Q {n}"

    partes = nombre_tn.replace(",","").split()
    if len(partes) >= 1:
        ape = partes[-1]
        if len(ape) > 3:
            res = consultar_api_aria({'q': ape})
            if res:
                if numeros_a_probar:
                    dni_obj = numeros_a_probar[-1]
                    for c in res:
                        if dni_obj in solo_numeros(c.get('cliente_dnicuit','')): return c, "✅ Apellido + DNI"
                else:
                    ptn = set(nombre_tn.lower().split())
                    for c in res:
                        nom_aria = (str(c.get('cliente_nombre',''))+" "+str(c.get('cliente_apellido',''))).lower()
                        if len(ptn.intersection(set(nom_aria.split()))) >= 2: return c, "✅ Nombre Coincidente"
    return None, "❌ No encontrado"

def extraer_productos(pedido):
    return ", ".join([f"{i.get('name')} ({i.get('quantity')})" for i in pedido.get('products', [])])

# --- INTERFAZ ---
st.set_page_config(page_title="Gestor SSServicios", page_icon="🤖", layout="wide")
st.title("🤖 Gestor de Ventas Contrafactura")

st.sidebar.header("🔎 Consulta Rápida")
id_manual = st.sidebar.text_input("ID Cliente:", placeholder="Ej: 7113")
if st.sidebar.button("Consultar Cupo"):
    if not id_manual: st.sidebar.warning("Ingresa un número.")
    else:
        with st.spinner("Buscando..."):
            res_manual = consultar_api_aria_id(id_manual)
            if res_manual and res_manual[0].get('cliente_id'):
                cli_m = res_manual[0]
                nom_m = f"{cli_m.get('cliente_nombre','')} {cli_m.get('cliente_apellido','')}"
                try: cupo_m = float(cli_m.get('clienteScoringFinanciable', 0))
                except: cupo_m = 0.0
                meses_m = int(cli_m.get('cliente_meses_atraso', 0) or 0)
                st.sidebar.success(f"✅ **{nom_m}**")
                st.sidebar.metric("Cupo Disponible", f"${cupo_m:,.0f}")
                if meses_m > 0: st.sidebar.error(f"⛔ Mora: {meses_m} meses")
                else: st.sidebar.info("✅ Al día")
            else: st.sidebar.error("❌ Cliente no existe.")

if st.sidebar.button("🔄 Actualizar Todo"): st.rerun()

tab_nuevos, tab_pendientes, tab_aprobados, tab_cancelados = st.tabs(["📥 NUEVOS", "⏳ PENDIENTES", "✅ APROBADOS", "🚫 CANCELADOS"])

with st.spinner('Sincronizando Tiendanube...'):
    pedidos_open = obtener_pedidos("open")
    pedidos_closed = obtener_pedidos("closed")
    pedidos_todos = pedidos_open + pedidos_closed

# --- PESTAÑA: NUEVOS ---
with tab_nuevos:
    p_nuevos = [p for p in pedidos_todos if p['status']=='open' and p['payment_status']=='pending' and TAG_PENDIENTE not in (p.get('owner_note') or "") and TAG_APROBADO not in (p.get('owner_note') or "")]
    
    if not p_nuevos: st.info("✅ Bandeja limpia.")
    else:
        st.write(f"**{len(p_nuevos)}** pedidos nuevos.")
        for p in p_nuevos:
            id_real = p['id']
            id_visual = p.get('number', id_real)
            nom = p['customer']['name']
            mail = p['customer'].get('email')
            total = float(p['total'])
            nota = p.get('owner_note') or ""
            prods_txt = extraer_productos(p)
            nombre_prod_principal = p['products'][0]['name'] if p['products'] else ""

            with st.expander(f"🆕 #{id_visual} | {nom} | ${total:,.0f}", expanded=True):
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.markdown(f"**Items:** {prods_txt}")
                    st.markdown(f"**Nota:** {nota}")
                with c2:
                    if st.button(f"🔍 Analizar", key=f"an_{id_real}"): st.session_state['analisis_activo'][id_real] = True
                    
                    if st.session_state['analisis_activo'].get(id_real):
                        st.markdown("---")
                        cli, msg = buscar_cliente_cascada(nom, p['customer'].get('identification'), nota)
                        
                        if not cli:
                            st.error(msg)
                            st.warning("Busca ID Manual 👈")
                        else:
                            cupo = float(cli.get('clienteScoringFinanciable', 0))
                            meses = int(cli.get('cliente_meses_atraso', 0) or 0)
                            st.success(f"{msg} (Cupo: ${cupo:,.0f})")
                            
                            if meses > 0:
                                st.error(f"⛔ MORA: {meses} meses")
                                if st.button("📧 Rechazar (Mora)", key=f"r_{id_real}"):
                                    if enviar_notificacion(mail, nom, 1, {'id_visual': id_visual, 'nombre_producto_base': nombre_prod_principal}):
                                        actualizar_etiqueta(id_real, nota, TAG_PENDIENTE)
                                        st.toast("Rechazado enviado."); time.sleep(2); st.rerun()
                            elif total <= cupo:
                                st.success("🚀 APROBABLE")
                                if st.button("📧 APROBAR + Mail", key=f"ok_{id_real}"):
                                    if aprobar_orden_completa(id_real, nota, TAG_APROBADO):
                                        enviar_notificacion(mail, nom, 3, {'id_visual': id_visual, 'nombre_producto_base': nombre_prod_principal})
                                        st.toast("¡Aprobado!"); time.sleep(2); st.rerun()
                            else:
                                dif = total - cupo
                                st.warning(f"⚠️ Faltan ${dif:,.0f}")
                                if st.button("📧 Pedir Diferencia", key=f"dif_{id_real}"):
                                    if enviar_notificacion(mail, nom, 2, {'cupo': cupo, 'diferencia': dif, 'id_visual': id_visual, 'nombre_producto_base': nombre_prod_principal}):
                                        actualizar_etiqueta(id_real, nota, TAG_PENDIENTE)
                                        st.toast("Solicitud enviada."); time.sleep(2); st.rerun()
                        
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
        nombre_prod_principal = p['products'][0]['name'] if p['products'] else ""
        
        with st.expander(f"⏳ #{id_visual} | {nom}", expanded=True):
            c_ok, c_kill = st.columns(2)
            if c_ok.button("✅ Confirmar + Mail", key=f"pok_{id_real}"):
                if aprobar_orden_completa(id_real, p.get('owner_note'), TAG_APROBADO, TAG_PENDIENTE):
                    enviar_notificacion(p['customer'].get('email'), nom, 3, {'id_visual': id_visual, 'nombre_producto_base': nombre_prod_principal})
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
