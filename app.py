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

# ETIQUETAS
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
    # Traemos más pedidos para asegurar
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders?status={estado}&per_page=100"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    try:
        res = requests.get(url, headers=headers)
        return res.json() if res.status_code == 200 else []
    except Exception as e:
        st.error(f"Error al traer pedidos: {e}")
        return []

# --- FUNCIONES DE ACCIÓN CON REPORTE DE ERRORES ---

def actualizar_etiqueta(id_pedido, nota_actual, etiqueta_poner, etiqueta_sacar=None):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {
        'Authentication': f'bearer {TN_TOKEN}', 
        'User-Agent': TN_USER_AGENT,
        'Content-Type': 'application/json'
    }
    
    nota_str = str(nota_actual) if nota_actual is not None else ""
    if etiqueta_sacar:
        nota_str = nota_str.replace(etiqueta_sacar, "")
    if etiqueta_poner and etiqueta_poner not in nota_str:
        nota_str = f"{nota_str} {etiqueta_poner}"
    
    nota_final = nota_str.strip()
    
    # EJECUCIÓN CON DEBUG
    res = requests.put(url, headers=headers, json={"owner_note": nota_final})
    if res.status_code != 200:
        st.error(f"❌ Error al etiquetar: {res.status_code} - {res.text}")
        return False
    return True

def marcar_pagado_tn(id_pedido):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {
        'Authentication': f'bearer {TN_TOKEN}', 
        'User-Agent': TN_USER_AGENT,
        'Content-Type': 'application/json'
    }
    # EJECUCIÓN CON DEBUG
    res = requests.put(url, headers=headers, json={"payment_status": "paid"})
    if res.status_code != 200:
        st.error(f"❌ Error al marcar pagado: {res.status_code} - {res.text}")
        return False
    return True

def cancelar_orden_tn(id_pedido):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}/cancel"
    headers = {
        'Authentication': f'bearer {TN_TOKEN}', 
        'User-Agent': TN_USER_AGENT,
        'Content-Type': 'application/json'
    }
    res = requests.post(url, headers=headers, json={"reason": "other"})
    if res.status_code != 200:
        st.error(f"❌ Error al cancelar: {res.status_code} - {res.text}")
        return False
    return True

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
    
    if escenario == 1: # RECHAZADO
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
        st.error(f"❌ Error envío mail: {e}")
        return False

# ==========================================
# 🧠 4. LÓGICA DE BÚSQUEDA
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

# ==========================================
# 🖥️ 5. INTERFAZ OPERATIVA
# ==========================================
st.set_page_config(page_title="Gestor SSServicios", page_icon="🤖", layout="wide")
st.title("🤖 Gestor de Ventas Contrafactura")

# --- SIDEBAR ---
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
                try: meses_m = int(cli_m.get('cliente_meses_atraso', 0))
                except: meses_m = 0
                st.sidebar.success(f"✅ **{nom_m}**")
                st.sidebar.metric("Cupo Disponible", f"${cupo_m:,.0f}")
                if meses_m > 0: st.sidebar.error(f"⛔ Mora: {meses_m} meses")
                else: st.sidebar.info("✅ Al día")
            else: st.sidebar.error("❌ Cliente no existe.")

if st.sidebar.button("🔄 Actualizar Todo"): st.rerun()

# --- ESTRUCTURA DE PESTAÑAS ---
tab_nuevos, tab_pendientes, tab_aprobados, tab_cancelados = st.tabs([
    "📥 NUEVOS", 
    "⏳ PENDIENTES", 
    "✅ APROBADOS", 
    "🚫 CANCELADOS"
])

# --- OBTENCIÓN DE DATOS ---
with st.spinner('Sincronizando Tiendanube...'):
    pedidos_open = obtener_pedidos("open")
    pedidos_closed = obtener_pedidos("closed")
    pedidos_todos = pedidos_open + pedidos_closed

# --- 1. PESTAÑA: NUEVOS 📥 ---
with tab_nuevos:
    p_nuevos = []
    for p in pedidos_todos:
        status = p.get('status')
        pay_status = p.get('payment_status')
        nota = p.get('owner_note') or ""
        # Filtro
        if status == 'open' and pay_status == 'pending':
            if TAG_PENDIENTE not in nota and TAG_APROBADO not in nota:
                p_nuevos.append(p)
    
    if not p_nuevos:
        st.info("✅ Bandeja limpia.")
    else:
        st.write(f"**{len(p_nuevos)}** pedidos nuevos.")
        for p in p_nuevos:
            id_real = p['id']  # ID TECNICO
            id_visual = p.get('number', id_real) # ID CORTO (VISUAL)
            nom = p['customer']['name']
            dni = p['customer'].get('identification') or "S/D"
            mail = p['customer'].get('email')
            total = float(p['total'])
            nota = p.get('owner_note') or ""
            prods = extraer_productos(p)

            # Usamos id_visual para el titulo
            with st.expander(f"🆕 #{id_visual} | {nom} | ${total:,.0f}", expanded=True):
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.markdown(f"**Prod:** {prods}")
                    st.markdown(f"**Doc:** `{dni}`")
                    st.markdown(f"**Nota:** {nota}")
                
                with c2:
                    if st.button(f"🔍 Analizar", key=f"an_{id_real}"):
                        st.session_state['analisis_activo'][id_real] = True
                    
                    if st.session_state['analisis_activo'].get(id_real):
                        st.markdown("---")
                        cli, msg = buscar_cliente_cascada(nom, dni, nota)
                        
                        if not cli:
                            st.error(msg)
                            st.warning("Busca ID Manual 👈")
                        else:
                            id_aria = cli.get('cliente_id')
                            cupo = float(cli.get('clienteScoringFinanciable', 0))
                            meses = int(cli.get('cliente_meses_atraso', 0))
                            
                            st.success(f"{msg} (ID: {id_aria})")
                            st.metric("Cupo", f"${cupo:,.0f}")
                            if meses > 0: st.error(f"Mora: {meses} meses")

                            st.markdown("#### Acciones:")
                            
                            # 1. CASO RECHAZO
                            if meses > 0:
                                cr1, cr2 = st.columns(2)
                                if cr1.button("📧 Rechazar + Mail", key=f"r_m_{id_real}"):
                                    if enviar_notificacion(mail, nom, 1):
                                        if actualizar_etiqueta(id_real, nota, TAG_PENDIENTE):
                                            st.toast("Procesado.")
                                            time.sleep(3); st.rerun()
                                if cr2.button("💾 Solo Mover", key=f"r_s_{id_real}"):
                                    if actualizar_etiqueta(id_real, nota, TAG_PENDIENTE):
                                        st.toast("Movido.")
                                        time.sleep(3); st.rerun()

                            # 2. CASO APROBADO
                            elif total <= cupo:
                                st.success("🚀 ALCANZA EL CUPO")
                                ca1, ca2 = st.columns(2)
                                if ca1.button("📧 APROBAR + Mail", key=f"ok_m_{id_real}"):
                                    # Intentamos pagar y etiquetar. Si falla, vemos el error.
                                    pago_ok = marcar_pagado_tn(id_real)
                                    etiq_ok = actualizar_etiqueta(id_real, nota, TAG_APROBADO)
                                    mail_ok = enviar_notificacion(mail, nom, 3)
                                    
                                    if pago_ok and etiq_ok:
                                        st.toast("¡Éxito Total!")
                                        time.sleep(3); st.rerun()

                                if ca2.button("💾 Solo APROBAR", key=f"ok_s_{id_real}"):
                                    pago_ok = marcar_pagado_tn(id_real)
                                    etiq_ok = actualizar_etiqueta(id_real, nota, TAG_APROBADO)
                                    
                                    if pago_ok and etiq_ok:
                                        st.toast("Aprobado.")
                                        time.sleep(3); st.rerun()

                            # 3. CASO DIFERENCIA
                            else:
                                dif = total - cupo
                                st.warning(f"⚠️ Faltan ${dif:,.0f}")
                                cd1, cd2 = st.columns(2)
                                if cd1.button("📧 Pedir Diferencia", key=f"dif_m_{id_real}"):
                                    if enviar_notificacion(mail, nom, 2, {'cupo':cupo, 'diferencia':dif}):
                                        if actualizar_etiqueta(id_real, nota, TAG_PENDIENTE):
                                            st.toast("Enviado.")
                                            time.sleep(3); st.rerun()
                                if cd2.button("💾 Solo Mover", key=f"dif_s_{id_real}"):
                                    if actualizar_etiqueta(id_real, nota, TAG_PENDIENTE):
                                        st.toast("Movido.")
                                        time.sleep(3); st.rerun()
                        
                        if st.button("Cerrar", key=f"x_{id_real}"):
                            del st.session_state['analisis_activo'][id_real]
                            st.rerun()

# --- 2. PESTAÑA: PENDIENTES ⏳ ---
with tab_pendientes:
    p_pend = []
    for p in pedidos_todos:
        status = p.get('status')
        pay_status = p.get('payment_status')
        nota = p.get('owner_note') or ""
        if status == 'open' and pay_status == 'pending' and TAG_PENDIENTE in nota:
            p_pend.append(p)

    if not p_pend:
        st.info("No hay pendientes.")
    else:
        st.write(f"**{len(p_pend)}** esperando.")
        for p in p_pend:
            id_real = p['id']
            id_visual = p.get('number', id_real)
            nom = p['customer']['name']
            mail = p['customer'].get('email')
            total = float(p['total'])
            nota = p.get('owner_note') or ""

            with st.expander(f"⏳ #{id_visual} | {nom} | ${total:,.0f}", expanded=True):
                st.write(f"Nota: {nota}")
                c_ok, c_cancel = st.columns(2)
                
                with c_ok:
                    st.success("✅ ¿Pagó?")
                    if st.button(f"📧 Confirmar + Mail", key=f"p_ok_m_{id_real}"):
                        pago_ok = marcar_pagado_tn(id_real)
                        etiq_ok = actualizar_etiqueta(id_real, nota, TAG_APROBADO, TAG_PENDIENTE)
                        enviar_notificacion(mail, nom, 3)
                        if pago_ok and etiq_ok:
                            st.toast("Aprobado!")
                            time.sleep(3); st.rerun()
                    
                    if st.button(f"💾 Solo Confirmar", key=f"p_ok_s_{id_real}"):
                        pago_ok = marcar_pagado_tn(id_real)
                        etiq_ok = actualizar_etiqueta(id_real, nota, TAG_APROBADO, TAG_PENDIENTE)
                        if pago_ok and etiq_ok:
                            st.toast("Aprobado.")
                            time.sleep(3); st.rerun()

                with c_cancel:
                    st.error("🚫 ¿Cancelar?")
                    if st.button(f"💀 CANCELAR REALMENTE", key=f"kill_{id_real}"):
                        if cancelar_orden_tn(id_real):
                            st.toast("Cancelada.")
                            time.sleep(3); st.rerun()

# --- 3. PESTAÑA: APROBADOS ✅ ---
with tab_aprobados:
    p_ok = []
    for p in pedidos_todos:
        pay_status = p.get('payment_status')
        nota = p.get('owner_note') or ""
        if pay_status == 'paid' or TAG_APROBADO in nota:
            p_ok.append(p)
    st.write(f"**{len(p_ok)}** aprobados recientes.")
    for p in p_ok[:15]: 
        id_vis = p.get('number', p['id'])
        st.caption(f"✅ #{id_vis} - {p['customer']['name']} - ${float(p['total']):,.0f}")

# --- 4. PESTAÑA: CANCELADOS 🚫 ---
with tab_cancelados:
    p_cancel = []
    for p in pedidos_todos:
        if p.get('status') == 'cancelled':
            p_cancel.append(p)
    st.write(f"**{len(p_cancel)}** cancelados recientes.")
    for p in p_cancel[:15]:
        id_vis = p.get('number', p['id'])
        st.caption(f"🚫 #{id_vis} - {p['customer']['name']} - ${float(p['total']):,.0f}")
