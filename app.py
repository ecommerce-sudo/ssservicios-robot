import streamlit as st
import requests
import re
import smtplib
import time
import json
import os
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

TN_USER_AGENT = "RobotWeb (24705)"
ARIA_URL_BASE = "https://api.anatod.ar/api"
NUMERO_WHATSAPP = "5492966840059" # 👈 TU NÚMERO
FILE_CONFIG = "recomendados.json"   # Memoria del robot

# ETIQUETAS
TAG_PENDIENTE = "#PENDIENTE_PAGO"
TAG_APROBADO = "#APROBADO"

# === 🛡️ CUPOS DE RESPALDO ===
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

def tn_action(oid, action, note=None):
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{oid}"
    data = {}
    if action == "approve": 
        data = {"payment_status": "paid", "owner_note": note}
    elif action == "cancel": 
        requests.post(f"{url}/cancel", headers=headers, json={"reason": "other"})
        return
    elif action == "update_note": 
        data = {"owner_note": note}
    
    requests.put(url, headers=headers, json=data)

# === 🛒 NUEVO: CATÁLOGO INTELIGENTE TN ===
@st.cache_data(ttl=600)
def get_catalogo_tn_filtrado():
    """
    Trae productos de TN y aplica filtros estrictos:
    1. Que tenga FOTO.
    2. Que esté PUBLICADO.
    3. Que tenga STOCK (si controla stock).
    """
    url = f"https://api.tiendanube.com/v1/{TN_ID}/products?per_page=200"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            lista = []
            for p in res.json():
                # 1. Filtro Publicado
                if not p.get('published'): continue
                
                # 2. Filtro Foto (Evita imagen rota)
                if not p.get('images') or len(p['images']) == 0: continue
                foto_src = p['images'][0]['src']

                # 3. Filtro Stock
                tiene_stock = False
                stock_val = int(p.get('stock', 0) or 0)
                if not p.get('stock_control'): tiene_stock = True # Stock infinito
                elif stock_val > 0: tiene_stock = True

                if not tiene_stock: continue

                # Si pasa todo, lo guardamos
                lista.append({
                    "id": str(p['id']),
                    "nombre": p['name']['es'],
                    "precio": float(p.get('price', 0)) if p.get('price') else 0.0,
                    "foto": foto_src,
                    "link": p.get('canonical_url', '#')
                })
            return lista
        return []
    except: return []

# ==========================================
# 💾 3. GESTIÓN DE CONFIGURACIÓN (JSON)
# ==========================================

DEFAULT_CONFIG = {
    "GAMING": {"keywords": ["gamer", "juego", "play", "ps4", "pc", "mouse"], "items": []},
    "CONECTIVIDAD": {"keywords": ["wifi", "router", "internet", "cable", "starlink"], "items": []},
    "MOVILIDAD": {"keywords": ["celular", "samsung", "iphone", "cargador", "usb"], "items": []},
    "HOGAR": {"keywords": ["tv", "smart", "casa", "electro", "freidora"], "items": []}
}

def cargar_configuracion():
    if os.path.exists(FILE_CONFIG):
        with open(FILE_CONFIG, "r") as f:
            return json.load(f)
    return DEFAULT_CONFIG

def guardar_configuracion(config):
    with open(FILE_CONFIG, "w") as f:
        json.dump(config, f)

def detectar_perfil(nombre_prod):
    nombre_lower = str(nombre_prod).lower()
    config = cargar_configuracion()
    
    perfil_elegido = "HOGAR" # Default
    for perfil, data in config.items():
        for k in data['keywords']:
            if k in nombre_lower:
                return perfil
    return perfil_elegido

# ==========================================
# 📧 4. GESTOR DE CORREOS
# ==========================================

def generar_html_correo(nombre_cliente, escenario, datos_extra={}):
    id_visual = datos_extra.get('id_visual', 'S/N')
    
    # Links WhatsApp
    link_ws_general = f"https://wa.me/{NUMERO_WHATSAPP}"
    link_ws_comprobante = f"https://wa.me/{NUMERO_WHATSAPP}?text={urllib.parse.quote(f'Hola, envío diferencia pedido #{id_visual}')}"
    
    # === CROSS SELLING DINÁMICO ===
    html_cross = ""
    nombre_prod_base = datos_extra.get('nombre_producto_base', '')
    
    if nombre_prod_base:
        perfil = detectar_perfil(nombre_prod_base)
        config = cargar_configuracion()
        items = config.get(perfil, config["HOGAR"])["items"]
        
        if items:
            filas = ""
            for item in items[:3]: # Max 3 productos
                precio_fmt = f"${item['precio']:,.0f}"
                filas += f"""
                <td style="width:33%;padding:10px;text-align:center;border:1px solid #f0f0f0;border-radius:8px;background:#fff;">
                    <a href="{item['link']}" style="text-decoration:none;color:#333;display:block;">
                        <img src="{item['foto']}" style="width:100%;max-width:120px;height:120px;object-fit:contain;margin-bottom:10px;">
                        <p style="font-size:12px;margin:0 0 5px;height:32px;overflow:hidden;line-height:1.2;"><strong>{item['nombre']}</strong></p>
                        <p style="color:#28a745;font-weight:bold;margin:0;">{precio_fmt}</p>
                        <div style="background:#007bff;color:white;padding:5px 10px;border-radius:4px;font-size:11px;margin-top:5px;display:inline-block;">VER</div>
                    </a>
                </td>
                """
            html_cross = f"""
            <div style="background-color:#f8f9fa;padding:15px;border-radius:8px;margin-top:25px;border:1px solid #e9ecef;">
                <h3 style="text-align:center;color:#495057;margin-top:0;font-size:16px;">🔥 Recomendados para vos ({perfil})</h3>
                <table width="100%" cellpadding="0" cellspacing="5" style="border-collapse:separate;">
                    <tr>{filas}</tr>
                </table>
            </div>
            """

    # === PIE DE PÁGINA ===
    html_footer = f"""
        <p style="border-top: 1px solid #eee; padding-top: 20px; margin-top: 30px; font-size: 13px; color: #777; text-align: center;">
            ¿Tenés dudas? <a href="{link_ws_general}" style="color: #007bff; text-decoration: none; font-weight: bold;">Escribinos por WhatsApp</a>
        </p>
    """

    # === CUERPOS DE TEXTO ===
    cuerpo = ""
    asunto = ""

    # CASO 1: RECHAZO (CANCELACIÓN)
    if escenario == 1:
        asunto = f"Información sobre tu pedido #{id_visual}"
        cuerpo = f"""
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p>Te contactamos para informarte sobre el pedido <strong>#{id_visual}</strong> que realizaste en nuestra tienda.</p>
            <p>Al procesar la solicitud, el sistema de validación administrativa no ha podido aprobar la financiación solicitada. Por este motivo, <strong>el pedido ha sido cancelado en el sistema.</strong></p>
            <p><strong>¡Pero podés tener tus productos igual!</strong> 🛒<br>
            Te invitamos a ingresar nuevamente a nuestra tienda online y realizar la compra utilizando los medios de pago directos habilitados:</p>
            <ul><li>Tarjeta de Crédito o Débito.</li><li>Transferencia Bancaria.</li></ul>
            <p>Esperamos tu nueva orden para prepararla cuanto antes.</p>
            <p>¡Saludos!<br><strong>Equipo SSServicios</strong></p>
        """
    
    # CASO 2: DIFERENCIA (ENRIQUECIDO)
    elif escenario == 2:
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        asunto = f"Acción requerida: Finalizá tu pedido #{id_visual}"
        cuerpo = f"""
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p><strong>¡Buenas noticias!</strong> Tu solicitud de financiación fue aprobada parcialmente.</p>
            <p>Te contamos que tu límite disponible cubre una gran parte del total, por lo que <strong>solo necesitás abonar la diferencia para que podamos despachar tu pedido.</strong></p>
            
            <div style="background: #f0f8ff; padding: 20px; border-radius: 8px; border-left: 5px solid #007bff; margin: 20px 0;">
                <h3 style="margin-top:0; color: #0056b3;">📉 Resumen de Financiación:</h3>
                <p style="margin:5px 0;">✅ Cubierto por cupo: <strong>${cupo:,.0f}</strong></p>
                <p style="margin:5px 0; font-size: 18px; color: #d9534f;">👉 <strong>Resta abonar: ${dif:,.0f}</strong></p>
            </div>

            <p><strong>⏳ ¿Cómo seguimos?</strong><br>Para liberar el pedido, transferí la diferencia a:</p>
            <p style="background:#f9f9f9; padding:15px; border:1px dashed #ccc;">
            <strong>Banco BBVA</strong><br>CBU: 0170272120000001018527<br>Alias: SSSERVICIOS.MP</p>
            
            <p style="text-align: center; margin-top: 25px;">
                <a href="{link_ws_comprobante}" style="background: #25D366; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 14px;">👉 ENVIAR COMPROBANTE POR WHATSAPP</a>
            </p>
        """

    # CASO 3: APROBADO
    elif escenario == 3:
        asunto = f"¡Aprobado! Tu pedido #{id_visual} está en camino ✅"
        cuerpo = f"""
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p>Confirmamos que la financiación de tu pedido <strong>#{id_visual}</strong> fue <strong>APROBADA CORRECTAMENTE</strong>.</p>
            <p>El importe total se verá reflejado en tu próxima factura en <strong>3 cuotas sin interés</strong>.</p>
            <p>Ya estamos preparando tu paquete. Te avisaremos apenas salga a despacho.</p>
            <p>¡Gracias por elegirnos!</p>
        """

    html_final = f"""<div style="font-family:Arial,sans-serif;color:#333;line-height:1.5;max-width:600px;margin:auto;border:1px solid #eee;padding:20px;border-radius:8px;">{cuerpo}{html_cross}{html_footer}</div>"""
    return asunto, html_final

def enviar_notificacion(email, nombre, escenario, datos_extra={}):
    asunto, html = generar_html_correo(nombre, escenario, datos_extra)
    try:
        msg = MIMEMultipart()
        msg['From'] = st.secrets["email"]["smtp_user"]
        msg['To'] = email
        msg['Subject'] = asunto
        msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP(st.secrets["email"]["smtp_server"], st.secrets["email"]["smtp_port"])
        server.starttls()
        server.login(st.secrets["email"]["smtp_user"], st.secrets["email"]["smtp_password"])
        server.sendmail(st.secrets["email"]["smtp_user"], email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"Error SMTP: {e}")
        return False

# ==========================================
# 🚀 5. UI PRINCIPAL
# ==========================================
st.set_page_config(page_title="Gestor SSServicios", page_icon="🤖", layout="wide")
st.title("🤖 Gestor de Cobranzas")

# === SIDEBAR ===
st.sidebar.header("🔎 Consulta Manual")
id_m = st.sidebar.text_input("ID Cliente")
if st.sidebar.button("Consultar"):
    if not id_m: st.sidebar.warning("Poné un ID")
    else:
        with st.spinner("Consultando..."):
            res = consultar_api_aria_id(id_m)
            if res and res[0].get('cliente_id'):
                c = res[0]
                with st.sidebar.expander("Datos Crudos"): st.json(c)
                
                cupo = safe_float(c.get('clienteScoringFinanciable'))
                origen = "API"
                if cupo == 0: 
                    cat = int(c.get('cliente_categoria', 0) or 0)
                    cupo = CUPOS_POR_CATEGORIA.get(cat, 100000)
                    origen = f"Respaldo Cat {cat}"
                
                st.sidebar.success(f"{c.get('cliente_nombre')} {c.get('cliente_apellido')}")
                st.sidebar.metric("Cupo", f"${cupo:,.0f}", help=origen)
                
                meses = int(c.get('cliente_meses_atraso', 0) or 0)
                if meses > 0: st.sidebar.error(f"Mora: {meses} meses")
                else: st.sidebar.info("Al día")
            else: st.sidebar.error("No existe")

if st.sidebar.button("🔄 Actualizar Todo"): st.rerun()

# === PESTAÑAS ===
tabs = st.tabs(["📥 NUEVOS", "⚙️ CONFIGURAR RECOMENDADOS", "⏳ PENDIENTES", "✅ APROBADOS", "🚫 CANCELADOS"])

# --- TAB 1: NUEVOS ---
with tabs[0]:
    if st.button("Buscar Pedidos Nuevos"):
        with st.spinner("Leyendo Tiendanube..."):
            pedidos = obtener_pedidos("open")
            nuevos = [p for p in pedidos if p['payment_status']=='pending' and TAG_PENDIENTE not in (p.get('owner_note') or "") and TAG_APROBADO not in (p.get('owner_note') or "")]
            
            if not nuevos: st.info("Todo limpio.")
            for p in nuevos:
                oid = p['id']
                nom = p['customer']['name']
                total = float(p['total'])
                nota = p.get('owner_note') or ""
                prod_nom = p['products'][0]['name'] if p['products'] else ""
                
                with st.expander(f"🆕 #{p.get('number')} | {nom} | ${total:,.0f}"):
                    if st.button("Analizar", key=f"a_{oid}"): st.session_state[f"analizar_{oid}"] = True
                    
                    if st.session_state.get(f"analizar_{oid}"):
                        st.markdown("---")
                        # Busqueda Cascada
                        cli, msg = None, "No encontrado"
                        ids_nota = re.findall(r'\b\d{3,7}\b', str(nota))
                        for pid in ids_nota:
                            r = consultar_api_aria_id(pid)
                            if r and r[0].get('cliente_id'): cli, msg = r[0], f"ID {pid}"; break
                        
                        if not cli:
                            dni = solo_numeros(p['customer'].get('identification'))
                            if len(dni) > 5:
                                r = consultar_api_aria({'ident': dni})
                                if r: cli, msg = r[0], f"DNI {dni}"
                        
                        if not cli:
                            st.error(msg)
                            with st.expander("Datos TN"): st.write(p['customer'])
                        else:
                            # Lógica Cupo
                            cupo = safe_float(cli.get('clienteScoringFinanciable'))
                            origen = "API"
                            if cupo == 0:
                                cat = int(cli.get('cliente_categoria', 0) or 0)
                                cupo = CUPOS_POR_CATEGORIA.get(cat, 100000)
                                origen = f"Respaldo Cat {cat}"
                            
                            meses = int(cli.get('cliente_meses_atraso', 0) or 0)
                            dif = total - cupo
                            
                            st.success(f"Encontrado por {msg}")
                            col1, col2, col3 = st.columns(3)
                            col1.metric("Cupo", f"${cupo:,.0f}", help=origen)
                            col2.metric("Pedido", f"${total:,.0f}")
                            col3.metric("Mora", f"{meses}m")

                            # Escenarios
                            esc = 0
                            if meses > 0: esc = 1
                            elif total <= cupo: esc = 3
                            else: esc = 2
                            
                            # Preview
                            subj, html = generar_html_correo(nom, esc, {'cupo':cupo, 'diferencia':dif, 'id_visual':p.get('number'), 'nombre_producto_base': prod_nom})
                            with st.expander("👁️ Ver Preview Email"): components.html(html, height=450, scrolling=True)
                            
                            # Botones Acción
                            if esc == 1:
                                st.error("⛔ Tiene Mora")
                                if st.button("Cancelar Pedido", key=f"b1_{oid}"):
                                    tn_action(oid, "cancel")
                                    enviar_notificacion(p['customer']['email'], nom, 1, {'id_visual':p.get('number')})
                                    st.toast("Cancelado."); time.sleep(2); st.rerun()
                            elif esc == 2:
                                st.warning("⚠️ Cupo Parcial")
                                if st.button("Solicitar Diferencia", key=f"b2_{oid}"):
                                    tn_action(oid, "update_note", f"{nota} {TAG_PENDIENTE}")
                                    enviar_notificacion(p['customer']['email'], nom, 2, {'cupo':cupo, 'diferencia':dif, 'id_visual':p.get('number')})
                                    st.toast("Mail enviado."); time.sleep(2); st.rerun()
                            elif esc == 3:
                                st.success("🚀 Aprobable")
                                if st.button("Aprobar", key=f"b3_{oid}"):
                                    tn_action(oid, "approve", f"{nota} {TAG_APROBADO}")
                                    enviar_notificacion(p['customer']['email'], nom, 3, {'id_visual':p.get('number')})
                                    st.balloons(); time.sleep(2); st.rerun()

# --- TAB 2: CONFIGURADOR (NUEVO) ---
with tabs[1]:
    st.header("🛒 Panel de Recomendados")
    st.caption("Seleccioná productos reales de tu tienda. Solo aparecen los que tienen foto y stock.")
    
    config_actual = cargar_configuracion()
    
    if st.button("🔄 Cargar Productos de Tiendanube"):
        catalogo = get_catalogo_tn_filtrado()
        if not catalogo:
            st.warning("No se encontraron productos o hubo error de conexión.")
        else:
            st.session_state['catalogo_tn'] = catalogo
            st.success(f"Cargados {len(catalogo)} productos aptos.")

    catalogo = st.session_state.get('catalogo_tn', [])
    
    if catalogo:
        opciones = {p['nombre']: p for p in catalogo}
        nombres = list(opciones.keys())
        
        col_a, col_b = st.columns(2)
        categorias = ["GAMING", "CONECTIVIDAD", "MOVILIDAD", "HOGAR"]
        
        for i, perfil in enumerate(categorias):
            with (col_a if i % 2 == 0 else col_b):
                st.subheader(f"📂 {perfil}")
                
                # Items actuales en config
                items_guardados = config_actual.get(perfil, {}).get("items", [])
                defaults = [x['nombre'] for x in items_guardados if x['nombre'] in nombres]
                
                seleccion = st.multiselect(
                    f"Elegí 3 productos:",
                    options=nombres,
                    default=defaults,
                    max_selections=3,
                    key=f"sel_{perfil}"
                )
                
                if st.button(f"Guardar {perfil}", key=f"save_{perfil}"):
                    nuevos = []
                    for nom in seleccion:
                        d = opciones[nom]
                        nuevos.append({"nombre":d['nombre'], "link":d['link'], "foto":d['foto'], "precio":d['precio']})
                    
                    config_actual[perfil]["items"] = nuevos
                    guardar_configuracion(config_actual)
                    st.success("Guardado!")
                
                # Mini preview visual
                if items_guardados:
                    c1, c2, c3 = st.columns(3)
                    for j, item in enumerate(items_guardados[:3]):
                        with [c1, c2, c3][j]:
                            st.image(item['foto'], width=60)
                            st.caption(f"${item['precio']:,.0f}")
                st.markdown("---")

# --- OTRAS TABS ---
with tabs[2]: # Pendientes
    if st.button("Refrescar Pendientes"):
        pedidos = obtener_pedidos("open")
        pends = [p for p in pedidos if TAG_PENDIENTE in (p.get('owner_note') or "")]
        for p in pends:
            with st.expander(f"⏳ #{p.get('number')} | {p['customer']['name']}"):
                 if st.button("Confirmar Manualmente", key=f"ok_{p['id']}"):
                     tn_action(p['id'], "approve", f"{p.get('owner_note')} {TAG_APROBADO}")
                     st.success("Aprobado"); time.sleep(1); st.rerun()

with tabs[3]: st.write("Historial de Aprobados recientes...") # Aprobados
with tabs[4]: st.write("Historial de Cancelados recientes...") # Cancelados
