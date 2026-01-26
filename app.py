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
NUMERO_WHATSAPP = "5492966840059"
FILE_CONFIG = "recomendados.json"

# ETIQUETAS INTERNAS
TAG_PENDIENTE = "#PENDIENTE_PAGO"
TAG_APROBADO = "#APROBADO"

# Inicializar estados de memoria
if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}
if 'expanded_oid' not in st.session_state:
    st.session_state['expanded_oid'] = None # Para recordar cual desplegable abrir

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

def generar_link_ws(telefono, mensaje):
    msg_encoded = urllib.parse.quote(mensaje)
    return f"https://wa.me/{telefono}?text={msg_encoded}"

# --- APIs ---
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
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders?status={estado}&per_page=200"
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

# === 🛒 CATÁLOGO INTELIGENTE TN ===
@st.cache_data(ttl=600)
def get_catalogo_tn_filtrado():
    url = f"https://api.tiendanube.com/v1/{TN_ID}/products?per_page=200"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            lista = []
            for p in res.json():
                if not p.get('published'): continue
                if not p.get('images') or len(p['images']) == 0: continue
                
                foto_src = p['images'][0]['src']
                
                p_original = safe_float(p.get('price')) 
                p_promo = safe_float(p.get('promotional_price'))
                
                if (p_original == 0 and p_promo == 0) and p.get('variants'):
                    v = p['variants'][0]
                    p_original = safe_float(v.get('price'))
                    p_promo = safe_float(v.get('promotional_price'))

                precio_venta = 0.0
                precio_tachado = 0.0
                
                if p_promo > 0 and p_promo < p_original:
                    precio_venta = p_promo
                    precio_tachado = p_original
                elif p_original > 0:
                    precio_venta = p_original
                    precio_tachado = 0.0 
                elif p_promo > 0:
                    precio_venta = p_promo
                    precio_tachado = 0.0

                if precio_venta <= 0: continue 

                tiene_stock = False
                stock_val = int(p.get('stock', 0) or 0)
                if not p.get('stock_control'): tiene_stock = True
                elif stock_val > 0: tiene_stock = True

                if not tiene_stock: continue

                lista.append({
                    "id": str(p['id']),
                    "nombre": p['name']['es'],
                    "precio_venta": precio_venta,    
                    "precio_lista": precio_tachado,  
                    "foto": foto_src,
                    "link": p.get('canonical_url', '#')
                })
            return lista
        return []
    except: return []

# ==========================================
# 💾 3. GESTIÓN DE CONFIGURACIÓN
# ==========================================
DEFAULT_CONFIG = {
    "GAMING": {"keywords": ["gamer", "juego", "play", "ps4", "pc"], "items": []},
    "CONECTIVIDAD": {"keywords": ["wifi", "router", "internet"], "items": []},
    "MOVILIDAD": {"keywords": ["celular", "samsung", "iphone"], "items": []},
    "HOGAR": {"keywords": ["tv", "smart", "casa", "electro"], "items": []}
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
    perfil_elegido = "HOGAR"
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
    link_ws_general = f"https://wa.me/{NUMERO_WHATSAPP}"
    link_ws_comprobante = f"https://wa.me/{NUMERO_WHATSAPP}?text={urllib.parse.quote(f'Hola, envío diferencia pedido #{id_visual}')}"
    
    html_cross = ""
    nombre_prod_base = datos_extra.get('nombre_producto_base', '')
    
    if nombre_prod_base:
        perfil = detectar_perfil(nombre_prod_base)
        config = cargar_configuracion()
        categoria_data = config.get(perfil, config["HOGAR"])
        items = categoria_data["items"]
        
        if items:
            filas = ""
            for item in items[:3]:
                p_venta = item.get('precio_venta', 0)
                p_lista = item.get('precio_lista', 0)
                
                if p_lista > p_venta:
                    pct_off = int((1 - (p_venta / p_lista)) * 100)
                    bloque_precio = f"""
                        <p style="color:#999;font-size:11px;text-decoration:line-through;margin:0;">${p_lista:,.0f}</p>
                        <p style="color:#28a745;font-weight:bold;font-size:14px;margin:0;">
                            ${p_venta:,.0f} <span style="background:#dc3545;color:white;padding:1px 3px;border-radius:3px;font-size:10px;">{pct_off}% OFF</span>
                        </p>
                    """
                else:
                    bloque_precio = f"""<p style="color:#28a745;font-weight:bold;margin:0;">${p_venta:,.0f}</p>"""

                filas += f"""
                <td style="width:33%;padding:10px;text-align:center;border:1px solid #f0f0f0;border-radius:8px;background:#fff;">
                    <a href="{item['link']}" style="text-decoration:none;color:#333;display:block;">
                        <img src="{item['foto']}" style="width:100%;max-width:120px;height:120px;object-fit:contain;margin-bottom:10px;">
                        <p style="font-size:12px;margin:0 0 5px;height:32px;overflow:hidden;line-height:1.2;"><strong>{item['nombre']}</strong></p>
                        {bloque_precio}
                        <div style="background:#007bff;color:white;padding:5px 10px;border-radius:4px;font-size:11px;margin-top:5px;display:inline-block;">VER OFERTA</div>
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

    html_footer = f"""
        <p style="border-top: 1px solid #eee; padding-top: 20px; margin-top: 30px; font-size: 13px; color: #777; text-align: center;">
            ¿Tenés dudas? <a href="{link_ws_general}" style="color: #007bff; text-decoration: none; font-weight: bold;">Escribinos por WhatsApp</a>
        </p>
    """

    cuerpo = ""
    asunto = ""

    if escenario == 1: # RECHAZO (Por Cupo o Por Mora)
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
    elif escenario == 2: # DIFERENCIA
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
    elif escenario == 3: # APROBADO
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
                origen = "API (Real)"
                
                st.sidebar.success(f"{c.get('cliente_nombre')} {c.get('cliente_apellido')}")
                st.sidebar.metric("Cupo", f"${cupo:,.0f}", help=origen)
                
                meses = int(c.get('cliente_meses_atraso', 0) or 0)
                if meses > 0: st.sidebar.warning(f"⚠️ Mora: {meses} meses (Cupo habilitado)")
                else: st.sidebar.info("Al día")
            else: 
                # CLIENTE EXTERNO
                st.info("🌍 Cliente Externo (No registrado en ARIA).")
                st.caption("Verificar manualmente si corresponde a una venta con Tarjeta o Transferencia desde otra provincia.")

if st.sidebar.button("🔄 Actualizar Todo (Recargar)"): st.rerun()

# === CARGA INICIAL DE PEDIDOS ===
with st.spinner("⏳ Sincronizando pedidos con Tiendanube..."):
    # Traemos todos los pedidos abiertos
    pedidos_open = obtener_pedidos("open")

# === PESTAÑAS ===
tabs = st.tabs(["📥 NUEVOS", "⏳ PENDIENTES (Comprobantes/Dif)", "⚙️ CONFIGURAR RECOMENDADOS", "✅ APROBADOS", "🚫 CANCELADOS"])

# --- LÓGICA DE CLASIFICACIÓN ---
aprobados_lista = [p for p in pedidos_open if p['payment_status'] == 'paid']
pendientes_dif_lista = [p for p in pedidos_open if TAG_PENDIENTE in (p.get('owner_note') or "")]
nuevos_lista = [
    p for p in pedidos_open 
    if p['payment_status'] == 'pending' 
    and TAG_PENDIENTE not in (p.get('owner_note') or "") 
    and TAG_APROBADO not in (p.get('owner_note') or "")
]

# --- TAB 1: NUEVOS (ANALISIS) ---
with tabs[0]:
    if not nuevos_lista: 
        st.info("✅ No hay pedidos nuevos para analizar.")
    else:
        st.write(f"Encontrados: {len(nuevos_lista)} pedidos nuevos.")
        for p in nuevos_lista:
            oid = p['id']
            nom = p['customer']['name']
            total = float(p['total'])
            nota = p.get('owner_note') or ""
            prod_nom = p['products'][0]['name'] if p['products'] else ""
            
            # --- DETECCIÓN DE PAGO ---
            gateway = str(p.get('gateway', '')).lower()
            gateway_name = str(p.get('gateway_name', '')).lower()
            payment_title = str(p.get('payment_details', {}).get('title', '')).lower()
            texto_pago = f"{gateway} {gateway_name} {payment_title}"

            # 1. CRÉDITO/FINANCIACIÓN
            es_financiacion = (
                'financiación' in texto_pago or 
                'factura' in texto_pago or 
                'ssservicios' in texto_pago or 
                'convenir' in texto_pago or 
                'acordar' in texto_pago
            )

            # 2. TRANSFERENCIA
            es_transferencia = False
            if not es_financiacion:
                es_transferencia = 'transfer' in texto_pago or 'depó' in texto_pago or 'wire' in gateway

            # 3. TARJETA
            es_tarjeta = not (es_financiacion or es_transferencia)
            
            # RENDERIZADO VISUAL
            if es_financiacion:
                titulo = f"🤝 Financiación/Crédito | #{p.get('number')} | {nom} | ${total:,.0f}"
            elif es_transferencia:
                titulo = f"🏦 Transferencia | #{p.get('number')} | {nom} | ${total:,.0f}"
            else:
                titulo = f"💳 Tarjeta/Pasarela | #{p.get('number')} | {nom} | ${total:,.0f}"

            # MEMORIA VISUAL: Chequeamos si este expander debe estar abierto
            esta_abierto = (st.session_state['expanded_oid'] == oid)

            with st.expander(titulo, expanded=esta_abierto):
                
                # === CASO 1: FINANCIACIÓN (Crédito) ===
                if es_financiacion:
                    st.info("ℹ️ Solicitud de Financiación en Factura. Requiere Análisis.")
                    
                    # Botón que activa el análisis y "traba" el expander abierto
                    if st.button("🔍 Analizar Cliente (Cupo)", key=f"a_{oid}"): 
                        st.session_state[f"analizar_{oid}"] = True
                        st.session_state['expanded_oid'] = oid # GUARDAMOS EL ESTADO
                        st.rerun() # RECARGAMOS PARA APLICAR EL EXPANDED=TRUE
                    
                    if st.session_state.get(f"analizar_{oid}"):
                        st.markdown("---")
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
                        
                        # -> CLIENTE EXTERNO
                        if not cli:
                            st.info("🌍 Cliente Externo (No registrado en ARIA).")
                            st.caption("Verificar manualmente si es una venta externa.")
                            
                            c_m1, c_m2 = st.columns(2)
                            if c_m1.button("✅ Aprobar Manual", key=f"ok_man_{oid}"):
                                tn_action(oid, "approve", f"{nota} {TAG_APROBADO}")
                                st.success("Aprobado manual."); time.sleep(1); st.rerun()
                            if c_m2.button("🚫 Cancelar", key=f"cx_man_{oid}"):
                                tn_action(oid, "cancel")
                                st.error("Cancelado."); time.sleep(1); st.rerun()
                        else:
                            # -> CLIENTE ARIA
                            cupo = safe_float(cli.get('clienteScoringFinanciable'))
                            origen = "API (Aria)"
                            meses = int(cli.get('cliente_meses_atraso', 0) or 0)
                            st.success(f"Encontrado por {msg}")

                            dif = total - cupo
                            col1, col2, col3 = st.columns(3)
                            col1.metric("Cupo", f"${cupo:,.0f}", help=origen)
                            col2.metric("Pedido", f"${total:,.0f}")
                            col3.metric("Mora", f"{meses}m")
                            
                            # --- LÓGICA DE DECISIÓN (NUEVA POLÍTICA MORA) ---
                            esc = 0
                            
                            # Si tiene MORA > 0, Bloqueamos la aprobación automática
                            tiene_mora = (meses > 0)

                            if cupo == 0: 
                                esc = 1 # RECHAZO CUPO 0
                            elif total <= cupo: 
                                esc = 3 # APROBABLE (Si no tuviera mora)
                            else: 
                                esc = 2 # DIFERENCIA

                            # RENDERIZADO DE ACCIONES
                            if esc == 1:
                                st.error("⛔ Rechazo Automático (Cupo $0)")
                                if st.button("Rechazar y Cancelar", key=f"b1_{oid}"):
                                    tn_action(oid, "cancel")
                                    enviar_notificacion(p['customer']['email'], nom, 1, {'id_visual':p.get('number')})
                                    st.toast("Cancelado."); time.sleep(2); st.rerun()

                            elif esc == 2:
                                st.warning("⚠️ Cupo Parcial (Requiere Diferencia)")
                                if st.button("Solicitar Diferencia", key=f"b2_{oid}"):
                                    tn_action(oid, "update_note", f"{nota} {TAG_PENDIENTE}")
                                    enviar_notificacion(p['customer']['email'], nom, 2, {'cupo':cupo, 'diferencia':dif, 'id_visual':p.get('number')})
                                    st.toast("Mail enviado."); time.sleep(2); st.rerun()

                            elif esc == 3: # Cupo cubre todo
                                if tiene_mora:
                                    st.error(f"🛑 ALERTA DE RIESGO: Cliente con {meses} meses de Mora.")
                                    st.write("El sistema ha pausado la aprobación automática.")
                                    
                                    col_mora_1, col_mora_2 = st.columns(2)
                                    
                                    # Opción A: Rechazar por Mora
                                    if col_mora_1.button("🚫 Rechazar por Mora", key=f"rej_mora_{oid}"):
                                        tn_action(oid, "cancel")
                                        # Usamos escenario 1 (Rechazo genérico)
                                        enviar_notificacion(p['customer']['email'], nom, 1, {'id_visual':p.get('number')})
                                        st.error("Rechazado por Mora."); time.sleep(2); st.rerun()

                                    # Opción B: Aprobar Excepción
                                    if col_mora_2.button("✅ Aprobar (Excepción)", key=f"ok_mora_{oid}"):
                                        tn_action(oid, "approve", f"{nota} {TAG_APROBADO}")
                                        enviar_notificacion(p['customer']['email'], nom, 3, {'id_visual':p.get('number')})
                                        st.success("Excepción Aprobada."); time.sleep(2); st.rerun()
                                    
                                    # Preview del mail (Muestra el de rechazo por defecto si hay mora)
                                    subj, html = generar_html_correo(nom, 1, {'id_visual':p.get('number')})
                                    with st.expander("👁️ Ver Email de Rechazo"): components.html(html, height=450, scrolling=True)

                                else:
                                    st.success("🚀 Aprobable (Sin Deuda)")
                                    if st.button("Aprobar", key=f"b3_{oid}"):
                                        tn_action(oid, "approve", f"{nota} {TAG_APROBADO}")
                                        enviar_notificacion(p['customer']['email'], nom, 3, {'id_visual':p.get('number')})
                                        st.balloons(); time.sleep(2); st.rerun()
                                    
                                    subj, html = generar_html_correo(nom, 3, {'id_visual':p.get('number')})
                                    with st.expander("👁️ Ver Preview Email"): components.html(html, height=450, scrolling=True)


                # === CASO 2: TRANSFERENCIA (Pedir Comprobante) ===
                elif es_transferencia:
                    st.info("ℹ️ Pago por Transferencia Pendiente.")
                    msg_ws = f"Hola {nom}, gracias por tu compra #{p.get('number')}. Para procesar el envío necesitamos que nos envíes el comprobante de transferencia por este medio. ¡Gracias!"
                    phone_clean = solo_numeros(p['customer'].get('phone', ''))
                    if not phone_clean: phone_clean = "" 
                    
                    st.link_button("📲 Pedir Comprobante por WhatsApp", generar_link_ws(phone_clean, msg_ws))
                    
                    # BOTÓN NUEVO: Mover a Pendientes
                    st.write("")
                    if st.button("✅ Ya solicité comprobante (Mover a Pendientes)", key=f"mov_pend_{oid}"):
                        tn_action(oid, "update_note", f"{nota} {TAG_PENDIENTE}")
                        st.toast("Movido a Pendientes"); time.sleep(1); st.rerun()


                # === CASO 3: TARJETA/PASARELA (Listo para despacho) ===
                else:
                    st.success("✅ Pago con Tarjeta/Pasarela detectado. Listo para despacho.")
                    st.caption("Si ya ves el pago en MP/Billetera, confirmá acá para archivarlo.")
                    
                    if st.button("📦 Confirmar y Archivar (Aprobar)", key=f"card_ok_{oid}"):
                        tn_action(oid, "approve", f"{nota} {TAG_APROBADO}")
                        st.balloons()
                        st.toast("Pedido aprobado y archivado."); time.sleep(2); st.rerun()

# --- TAB 2: PENDIENTES ---
with tabs[1]:
    st.subheader("⏳ Esperando Diferencia de Pago")
    if not pendientes_dif_lista:
        st.info("No hay pedidos esperando diferencia.")
    else:
        for p in pendientes_dif_lista:
            prod_nom = p['products'][0]['name'] if p['products'] else ""
            with st.expander(f"💰 #{p.get('number')} | {p['customer']['name']} | ${float(p['total']):,.0f}"):
                 col_ok, col_x = st.columns(2)
                 if col_ok.button("✅ Confirmar Pago Manual", key=f"ok_{p['id']}"):
                     tn_action(p['id'], "approve", f"{p.get('owner_note')} {TAG_APROBADO}")
                     enviar_notificacion(p['customer']['email'], p['customer']['name'], 3, {'id_visual':p.get('number'), 'nombre_producto_base': prod_nom})
                     st.success("Aprobado y Mail Enviado"); time.sleep(2); st.rerun()
                 if col_x.button("🚫 Cancelar", key=f"cx_{p['id']}"):
                     tn_action(p['id'], "cancel")
                     st.error("Cancelado"); time.sleep(2); st.rerun()

# --- TAB 3: CONFIGURADOR ---
with tabs[2]:
    st.header("🛒 Panel de Recomendados")
    config_actual = cargar_configuracion()
    
    if st.button("🔄 Recargar Catálogo de Tiendanube"):
        catalogo = get_catalogo_tn_filtrado()
        if not catalogo: st.warning("Error o catálogo vacío.")
        else:
            st.session_state['catalogo_tn'] = catalogo
            st.success(f"Cargados {len(catalogo)} productos.")

    catalogo = st.session_state.get('catalogo_tn', [])
    
    if catalogo:
        opciones = {p['nombre']: p for p in catalogo}
        nombres = list(opciones.keys())
        col_a, col_b = st.columns(2)
        categorias = ["GAMING", "CONECTIVIDAD", "MOVILIDAD", "HOGAR"]
        
        for i, perfil in enumerate(categorias):
            with (col_a if i % 2 == 0 else col_b):
                st.subheader(f"📂 {perfil}")
                items_guardados = config_actual.get(perfil, {}).get("items", [])
                defaults = [x['nombre'] for x in items_guardados if x['nombre'] in nombres]
                seleccion = st.multiselect(f"Productos {perfil}:", options=nombres, default=defaults, max_selections=3, key=f"sel_{perfil}")
                
                if st.button(f"Guardar {perfil}", key=f"save_{perfil}"):
                    nuevos = []
                    for nom in seleccion:
                        d = opciones[nom]
                        nuevos.append({"nombre":d['nombre'], "link":d['link'], "foto":d['foto'], "precio_venta":d['precio_venta'], "precio_lista":d['precio_lista']})
                    config_actual[perfil]["items"] = nuevos
                    guardar_configuracion(config_actual)
                    st.success("Guardado!")
                
                if items_guardados:
                    c1, c2, c3 = st.columns(3)
                    for j, item in enumerate(items_guardados[:3]):
                        with [c1, c2, c3][j]:
                            st.image(item['foto'], width=60)
                            p_v = item.get('precio_venta', 0)
                            p_l = item.get('precio_lista', 0)
                            if p_l > p_v:
                                pct = int((1 - (p_v/p_l)) * 100)
                                st.caption(f"~~${p_l:,.0f}~~")
                                st.markdown(f"**${p_v:,.0f}** :red[{pct}% OFF]")
                            else:
                                st.markdown(f"**${p_v:,.0f}**")
                st.markdown("---")

# --- TAB 4: APROBADOS ---
with tabs[3]:
    st.subheader("✅ Pedidos Listos para Despacho")
    if not aprobados_lista:
        st.info("No hay pedidos aprobados recientemente.")
    else:
        st.success(f"{len(aprobados_lista)} pedidos pagados.")
        for p in aprobados_lista:
            gateway = p.get('gateway', '').lower()
            tipo_pago = "💳 Tarjeta/MP" if not ('wire' in gateway or 'transfer' in gateway) else "🏦 Transferencia"
            with st.expander(f"#{p.get('number')} | {p['customer']['name']} | ${float(p['total']):,.0f} | {tipo_pago}"):
                st.write(f"**Estado:** {p.get('payment_status').upper()}")
                st.write(f"**Productos:**")
                for prod in p['products']:
                    st.write(f"- {prod['name']} x{prod['quantity']}")
                st.caption("Este pedido ya está cobrado y listo.")

with tabs[4]: st.write("Historial Cancelados...")
