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

# --- FUNCIONES DE ACCIÓN ---

def aprobar_orden_completa(id_pedido, nota_actual, etiqueta_poner, etiqueta_sacar=None):
    """
    SUPER FUNCIÓN: Marca como PAGADO y actualiza la NOTA al mismo tiempo.
    Evita que Tiendanube acepte una cosa y rechace la otra.
    """
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {
        'Authentication': f'bearer {TN_TOKEN}', 
        'User-Agent': TN_USER_AGENT,
        'Content-Type': 'application/json'
    }
    
    # 1. Preparamos el texto de la nota
    nota_str = str(nota_actual) if nota_actual is not None else ""
    if etiqueta_sacar:
        nota_str = nota_str.replace(etiqueta_sacar, "")
    if etiqueta_poner and etiqueta_poner not in nota_str:
        nota_str = f"{nota_str} {etiqueta_poner}"
    nota_final = nota_str.strip()
    
    # 2. Preparamos el paquete completo (Pago + Nota)
    payload = {
        "payment_status": "paid",
        "owner_note": nota_final
    }
    
    # 3. Enviamos UN solo disparo
    try:
        res = requests.put(url, headers=headers, json=payload)
        if res.status_code == 200:
            return True
        else:
            # Si falla (ej: bloqueo gateway offline), intentamos al menos salvar la nota
            if res.status_code == 422: 
                requests.put(url, headers=headers, json={"owner_note": nota_final})
                return True # Retornamos True porque visualmente "Aprobamos" con la etiqueta
            
            st.error(f"❌ Error Tiendanube: {res.status_code} - {res.text}")
            return False
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return False

def actualizar_etiqueta(id_pedido, nota_actual, etiqueta_poner, etiqueta_sacar=None):
    # Esta función se mantiene para cuando SOLO queremos mover etiquetas (Rechazos, Pendientes)
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
    
    res = requests.put(url, headers=headers, json={"owner_note": nota_final})
    if res.status_code != 200:
        st.error(f"❌ Error al etiquetar: {res.status_code} - {res.text}")
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
# 📧 3. GESTOR DE CORREOS (MEJORADO)
# ==========================================
def enviar_notificacion(email_cliente, nombre_cliente, escenario, datos_extra={}):
    # --- CONFIGURACIÓN ---
    try:
        SMTP_SERVER = st.secrets["email"]["smtp_server"]
        SMTP_PORT = st.secrets["email"]["smtp_port"]
        SMTP_USER = st.secrets["email"]["smtp_user"]
        SMTP_PASS = st.secrets["email"]["smtp_password"]
    except:
        st.warning("⚠️ Faltan datos de email en Secrets.")
        return False
    
    # DATOS DE CONTACTO
    NUMERO_WHATSAPP = "5492966840059" 
    
    # Recuperamos datos clave
    id_visual = datos_extra.get('id_visual', 'S/N') # Número corto (#385)
    
    msg = MIMEMultipart()
    msg['From'] = f"SSServicios <{SMTP_USER}>"
    msg['To'] = email_cliente

    # --- PLANTILLAS DE EMAIL HTML ---
    
    if escenario == 1: # 🔴 RECHAZADO / MORA
        msg['Subject'] = f"Actualización sobre tu pedido #{id_visual} en SSServicios"
        cuerpo = f"""
        <div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p>Queremos contarte que ya recibimos tu pedido <strong>#{id_visual}</strong>.</p>
            <p>Al intentar procesar la financiación a través de tu factura de servicios, el sistema nos indica que momentáneamente no tenés cupo disponible para esta operación.</p>
            <p><strong>¡Pero no queremos que te quedes sin tus productos!</strong><br>
            Hemos reservado tu pedido por 24 horas para que puedas completarlo abonando con <strong>tarjeta de crédito, débito o transferencia bancaria</strong>.</p>
            <p>Si te interesa, respondé este correo y te enviamos el link de pago.</p>
            <br>
            <p>Atentamente,<br><strong>El equipo de SSServicios</strong></p>
        </div>
        """

    elif escenario == 2: # 🟡 DIFERENCIA (CON LINK WHATSAPP)
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        
        # Generar Link de WhatsApp Dinámico
        texto_ws = f"Hola SSServicios, envío el comprobante de pago por la diferencia del pedido #{id_visual}."
        texto_ws_encoded = urllib.parse.quote(texto_ws)
        link_ws = f"https://wa.me/{NUMERO_WHATSAPP}?text={texto_ws_encoded}"

        msg['Subject'] = f"Tu pedido #{id_visual}: Instrucciones para finalizar"
        cuerpo = f"""
        <div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p>¡Buenas noticias! Tu compra ha sido aprobada parcialmente.<br>
            Tenés un cupo disponible de <strong>${cupo:,.0f}</strong> para financiar en tu factura.</p>
            
            <div style="background-color: #fff8e1; padding: 15px; border-left: 5px solid #ffcc00; margin: 20px 0;">
                <p style="margin: 0;">Para que podamos despachar tu pedido, solo necesitamos que abones la diferencia de: <strong style="font-size: 1.1em;">${dif:,.0f}</strong></p>
            </div>

            <p><strong>Datos para la transferencia:</strong></p>
            <ul style="background-color: #f9f9f9; padding: 15px; list-style: none; border-radius: 5px;">
                <li><strong>Banco:</strong> BBVA</li>
                <li><strong>Número de cuenta:</strong> 272-010185/2</li>
                <li><strong>CBU:</strong> 0170272120000001018527</li>
                <li><strong>Titular:</strong> SSServicios Sas</li>
                <li><strong>CUIT:</strong> 30-71586345-2</li>
            </ul>

            <p><strong>¿Ya realizaste el pago?</strong><br>
            Hacé clic en el siguiente enlace para enviarnos el comprobante por WhatsApp (ya incluye tu número de orden):</p>
            
            <p style="text-align: center; margin-top: 25px;">
                <a href="{link_ws}" style="background-color: #25D366; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                👉 ENVIAR COMPROBANTE AHORA
                </a>
            </p>
            
            <hr style="border: 0; border-top: 1px solid #eee; margin-top: 30px;">
            <p style="font-size: 12px; color: #777;">
            <em>Nota de seguridad: Si tenés dudas sobre la veracidad de este correo, podés contactarnos directamente a través de nuestros canales oficiales.</em>
            </p>
            <br>
            <p>Atentamente,<br><strong>El equipo de SSServicios</strong></p>
        </div>
        """

    elif escenario == 3: # 🟢 APROBADO
        msg['Subject'] = f"¡Felicitaciones! Tu pedido #{id_visual} fue aprobado ✅"
        cuerpo = f"""
        <div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <p>Hola <strong>{nombre_cliente}</strong>,</p>
            <p>Te confirmamos que la financiación de tu compra <strong>#{id_visual}</strong> ha sido <strong>aprobada exitosamente</strong>.</p>
            <p>El importe se verá reflejado en tu próxima factura de servicios en <strong>3 cuotas sin interés</strong>.<br>
            Ya nuestro equipo de depósito está preparando tu paquete para despacharlo lo antes posible.</p>
            <p>¡Gracias por confiar en nosotros!</p>
            <br>
            <p>Atentamente,<br><strong>El equipo de SSServicios</strong></p>
        </div>
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
                                    if enviar_notificacion(mail, nom, 1, {'id_visual': id_visual}):
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
                                    # USAMOS LA SUPER FUNCIÓN
                                    exito = aprobar_orden_completa(id_real, nota, TAG_APROBADO)
                                    if exito:
                                        enviar_notificacion(mail, nom, 3, {'id_visual': id_visual})
                                        st.toast("¡Aprobado Exitosamente! 🚀")
                                        time.sleep(2); st.rerun()

                                if ca2.button("💾 Solo APROBAR", key=f"ok_s_{id_real}"):
                                    exito = aprobar_orden_completa(id_real, nota, TAG_APROBADO)
                                    if exito:
                                        st.toast("Aprobado.")
                                        time.sleep(2); st.rerun()

                            # 3. CASO DIFERENCIA
                            else:
                                dif = total - cupo
                                st.warning(f"⚠️ Faltan ${dif:,.0f}")
                                cd1, cd2 = st.columns(2)
                                if cd1.button("📧 Pedir Diferencia", key=f"dif_m_{id_real}"):
                                    # Pasamos ID Visual para el link de WhatsApp y el asunto
                                    if enviar_notificacion(mail, nom, 2, {'cupo':cupo, 'diferencia':dif, 'id_visual': id_visual}):
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
                        # USAMOS LA SUPER FUNCIÓN para borrar "PENDIENTE", poner "APROBADO" y marcar "PAID"
                        exito = aprobar_orden_completa(id_real, nota, TAG_APROBADO, TAG_PENDIENTE)
                        if exito:
                            enviar_notificacion(mail, nom, 3, {'id_visual': id_visual})
                            st.toast("Aprobado y Pagado.")
                            time.sleep(2); st.rerun()
                    
                    if st.button(f"💾 Solo Confirmar", key=f"p_ok_s_{id_real}"):
                        exito = aprobar_orden_completa(id_real, nota, TAG_APROBADO, TAG_PENDIENTE)
                        if exito:
                            st.toast("Aprobado y Pagado.")
                            time.sleep(2); st.rerun()

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
        status_gen = p.get('status')
        nota = p.get('owner_note') or ""
        
        # LÓGICA MAESTRA:
        # Entra si: (Está pagado REAL) O (Tiene la etiqueta #APROBADO)
        # Y ADEMÁS: No está cancelado.
        if (pay_status == 'paid' or TAG_APROBADO in nota) and status_gen != 'cancelled':
            p_ok.append(p)

    st.write(f"**{len(p_ok)}** aprobados (Pagados + Etiquetados).")
    
    for p in p_ok:
        id_vis = p.get('number', p['id'])
        nom = p['customer']['name']
        total = float(p['total'])
        pay_status = p.get('payment_status')
        nota = p.get('owner_note') or ""
        
        # DIFERENCIACIÓN VISUAL
        if pay_status == 'paid':
            icono = "🟢" # Pagado real en TN
            estado_txt = "PAGO CONFIRMADO"
        else:
            icono = "⚠️" # Aprobado por nosotros, pero pendiente en TN
            estado_txt = "APROBADO (Offline)"
            
        with st.expander(f"{icono} #{id_vis} | {nom} | ${total:,.0f} | {estado_txt}"):
            st.info(f"Nota: {nota}")
            if pay_status != 'paid':
                st.caption("💡 Este pedido figura 'Pendiente' en Tiendanube por ser Offline, pero ya tiene la etiqueta #APROBADO y el mail fue enviado.")

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
