import streamlit as st
import requests
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ CONFIGURACIÓN Y SECRETS
# ==========================================
try:
    TN_TOKEN = st.secrets["TN_TOKEN"]
    TN_ID = st.secrets["TN_ID"]
    ARIA_KEY = st.secrets["ARIA_KEY"]
    EMAIL_USER = st.secrets.get("EMAIL_USER", "")
    EMAIL_PASS = st.secrets.get("EMAIL_PASS", "")
except FileNotFoundError:
    st.error("⚠️ ERROR: No se encontraron los Secrets.")
    st.stop()
except KeyError as e:
    st.error(f"⚠️ FALTA CLAVE: {e}")
    st.stop()

# Configuración fija
TN_USER_AGENT = "RobotWeb (24705)"
ARIA_URL_BASE = "https://api.anatod.ar/api"
TAG_ESPERA = "#ESPERANDO_DIFERENCIA"

if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}

# ==========================================
# 🔌 FUNCIONES DE CONEXIÓN
# ==========================================
def solo_numeros(texto):
    if texto is None: return ""
    return re.sub(r'\D', '', str(texto))

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
    except Exception as e:
        print(f"Error API: {e}")
        return []

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

def obtener_pedidos(estado="open"):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders?status={estado}&per_page=50"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    try:
        res = requests.get(url, headers=headers)
        return res.json() if res.status_code == 200 else []
    except: return []

def actualizar_nota(id_pedido, nota_actual, nueva_etiqueta):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    if nueva_etiqueta in nota_actual: return
    nota_final = f"{nota_actual} {nueva_etiqueta}".strip()
    requests.put(url, headers=headers, json={"owner_note": nota_final})

def eliminar_etiqueta(id_pedido, nota_actual):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    nota_limpia = nota_actual.replace(TAG_ESPERA, "").strip()
    requests.put(url, headers=headers, json={"owner_note": nota_limpia})

# ==========================================
# 📧 GESTOR DE CORREOS
# ==========================================
def enviar_notificacion(email_cliente, nombre_cliente, escenario, datos_extra={}):
    if not EMAIL_USER or not EMAIL_PASS:
        st.warning("⚠️ No se envió mail (Faltan credenciales).")
        return True 

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = email_cliente
    
    if escenario == 1: # RECHAZADO
        msg['Subject'] = "Información importante sobre tu pedido en SSServicios"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        Muchas gracias por tu compra en nuestra tienda online.<br><br>
        <b>Te informamos que hemos realizado el análisis crediticio correspondiente y, por el momento, no es posible procesar la financiación de este pedido a través de tu factura de servicios; podés probar nuevamente en unos meses.</b><br><br>
        ¡No te preocupes! Si deseas continuar con la compra, puedes hacerlo abonando con <b>tarjeta de crédito, débito o transferencia bancaria</b>. Por favor, avísanos respondiendo a este correo si prefieres cambiar el medio de pago.<br><br>
        Saludos cordiales,<br>El equipo de SSServicios
        """
    elif escenario == 2: # DIFERENCIA
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        alias = "TU.ALIAS.AQUI" 
        cbu = "0000000000000000000000" 
        msg['Subject'] = "Acción requerida: Tu pedido en SSServicios (Cupo Disponible)"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        ¡Tenemos buenas noticias! Hemos verificado tu cuenta y tienes un cupo disponible de <b>${cupo:,.0f}</b> para financiar tu compra en cuotas sin interés.<br><br>
        Como el total de tu pedido supera ese monto, para aprobar el envío necesitamos que abones la diferencia de <b>${dif:,.0f}</b> mediante transferencia bancaria.<br><br>
        <b>Datos para la transferencia:</b><br><ul><li>Alias: {alias}</li><li>CBU: {cbu}</li></ul>
        Por favor, <b>responde a este correo adjuntando el comprobante de pago</b>.<br><br>
        Saludos,<br>El equipo de SSServicios
        """
    elif escenario == 3: # APROBADO
        msg['Subject'] = "¡Felicitaciones! Tu compra fue aprobada ✅"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        Te confirmamos que tu solicitud de financiación ha sido <b>aprobada exitosamente</b>.<br><br>
        El importe de tu compra se verá reflejado en tu próxima factura de SSServicios en <b>3 cuotas sin interés</b>.<br><br>
        Ya estamos preparando tu pedido.<br><br>
        Saludos,<br>El equipo de SSServicios
        """

    msg.attach(MIMEText(cuerpo, 'html'))
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, email_cliente, msg.as_string())
        server.quit()
        return True
    except: return False

# ==========================================
# 🧠 LÓGICA DE BÚSQUEDA (Cascada Mejorada)
# ==========================================
def buscar_cliente_cascada(nombre_tn, dni_tn, nota_tn):
    # 1. ID en Nota
    ids = re.findall(r'\b\d{3,7}\b', str(nota_tn))
    for pid in ids:
        res = consultar_api_aria_id(pid)
        if res and res[0].get('cliente_id'): return res[0], f"✅ ID {pid} (Nota)"

    # 2. DNI / CUIT (Con fallback)
    dni_input = solo_numeros(dni_tn)
    numeros = []
    if len(dni_input) > 5: numeros.append(dni_input)
    if len(dni_input) == 11: numeros.append(dni_input[2:10]) # Extraer DNI de CUIT

    for n in numeros:
        # Intento con IDENT (Exacto)
        res = consultar_api_aria({'ident': n})
        if res:
            for c in res:
                da = solo_numeros(c.get('cliente_dnicuit',''))
                if n in da or da in n: return c, f"✅ Match IDENT: {n}"
        
        # Intento con Q (Texto)
        res_q = consultar_api_aria({'q': n})
        if res_q:
            for c in res_q:
                da = solo_numeros(c.get('cliente_dnicuit',''))
                if n in da or da in n: return c, f"✅ Match Q: {n}"

    # 3. Apellido
    partes = nombre_tn.replace(",","").split()
    if len(partes) >= 1:
        ape = partes[-1]
        if len(ape) > 3:
            res = consultar_api_aria({'q': ape})
            if res:
                if numeros: # Si había DNI en TN, validar match
                    dni_obj = numeros[-1]
                    for c in res:
                        if dni_obj in solo_numeros(c.get('cliente_dnicuit','')): return c, "✅ Apellido + DNI"
                else: # Validación por nombre
                    ptn = set(nombre_tn.lower().split())
                    for c in res:
                        nom_aria = (str(c.get('cliente_nombre',''))+" "+str(c.get('cliente_apellido',''))).lower()
                        if len(ptn.intersection(set(nom_aria.split()))) >= 2: return c, "✅ Nombre Coincidente"

    return None, "❌ No encontrado"

def extraer_productos(pedido):
    return ", ".join([f"{i.get('name')} ({i.get('quantity')})" for i in pedido.get('products', [])])

# ==========================================
# 🖥️ INTERFAZ WEB
# ==========================================
st.set_page_config(page_title="Asistente Ventas", page_icon="🤖", layout="wide")
st.title("🤖 Asistente de Ventas Contrafactura")

st.sidebar.header("Panel")
opcion = st.sidebar.radio("Bandeja:", ["Nuevos", "Pendientes Diferencia"])
if st.sidebar.button("🔄 Actualizar"): st.rerun()

modo_pendientes = opcion == "Pendientes Diferencia"
estado_tn = "any" if modo_pendientes else "open"

with st.spinner('Cargando Tiendanube...'):
    pedidos_raw = obtener_pedidos(estado_tn)

pedidos = []
if pedidos_raw:
    for p in pedidos_raw:
        nota = p.get('owner_note') or ""
        es_espera = TAG_ESPERA in nota
        if modo_pendientes and es_espera: pedidos.append(p)
        elif not modo_pendientes and not es_espera: pedidos.append(p)

if not pedidos:
    st.info("✅ Bandeja al día.")
else:
    st.success(f"Gestión: {len(pedidos)} pedidos")

    for p in pedidos:
        id_p = p['id']
        nom = p['customer']['name']
        dni = p['customer'].get('identification') or "S/D"
        mail = p['customer'].get('email')
        total = float(p['total'])
        nota = p.get('owner_note', '')
        prods = extraer_productos(p)

        with st.expander(f"🛒 #{id_p} | {nom} | ${total:,.0f}", expanded=True):
            c1, c2 = st.columns([1, 1])
            c1.markdown(f"**Items:** {prods}")
            c1.markdown(f"**Doc:** `{dni}` | **Nota:** {nota}")

            with c2:
                if st.button(f"🔍 Analizar", key=f"b_{id_p}"):
                    st.session_state['analisis_activo'][id_p] = True
                
                if st.session_state['analisis_activo'].get(id_p):
                    with st.spinner("Consultando..."):
                        cli, msg = buscar_cliente_cascada(nom, dni, nota)
                    
                    if not cli:
                        st.error(msg)
                        st.info("💡 Buscar ID manual en Aria.")
                    else:
                        id_aria = cli.get('cliente_id')
                        # --- EXTRACCIÓN DE DATOS ---
                        try: cupo = float(cli.get('clienteScoringFinanciable', 0))
                        except: cupo = 0.0
                        try: saldo = float(cli.get('cliente_saldo', 0))
                        except: saldo = 0.0
                        # --- NUEVO DATO CLAVE: MESES DE ATRASO ---
                        try: meses_atraso = int(cli.get('cliente_meses_atraso', 0))
                        except: meses_atraso = 0

                        st.success(f"{msg} | ID: **{id_aria}**")
                        
                        col_s, col_c = st.columns(2)
                        
                        # Mostramos el saldo con un indicador de estado
                        lbl_saldo = f"${saldo:,.0f}"
                        if meses_atraso > 0:
                            col_s.metric("Saldo Vencido", lbl_saldo, f"{meses_atraso} Meses Atraso", delta_color="inverse")
                        else:
                            col_s.metric("Saldo Actual", lbl_saldo, "Al día (Corriente)", delta_color="normal")
                            
                        col_c.metric("Cupo Disp.", f"${cupo:,.0f}")
                        st.markdown("---")

                        # === LÓGICA DE DECISIÓN CORREGIDA ===
                        
                        # 🔴 RECHAZADO: SOLO SI TIENE MESES DE ATRASO (> 0)
                        if meses_atraso > 0:
                            st.error(f"⛔ RECHAZADO: Tiene deuda vencida ({meses_atraso} meses).")
                            if st.button("📧 Enviar Rechazo", key=f"r_{id_p}"):
                                if enviar_notificacion(mail, nom, 1): st.success("Enviado.")
                        
                        # 🟢 APROBADO: Si está al día (meses=0) y le da el cupo
                        elif total <= cupo:
                            st.success("🚀 APROBADO: Al día y con cupo.")
                            if saldo > 0:
                                st.caption(f"ℹ️ Nota: Tiene saldo de ${saldo:,.0f} pero es deuda corriente (no vencida).")

                            valor_cuota = total / 3
                            st.code(f"ID: {id_aria}\nImporte: ${valor_cuota:,.2f}\nCuotas: 3")
                            
                            if st.button(f"✅ Cargado Manualmente", key=f"ok_{id_p}"):
                                enviar_notificacion(mail, nom, 3)
                                st.toast("Notificado.")
                                del st.session_state['analisis_activo'][id_p]
                                if modo_pendientes: eliminar_etiqueta(id_p, nota)
                                st.rerun()

                        # 🟡 DIFERENCIA: Al día pero sin cupo
                        else:
                            dif = total - cupo
                            st.warning(f"⚠️ FALTA SALDO: Pagar ${dif:,.0f}")
                            
                            if st.button(f"📧 Pedir Diferencia", key=f"ask_{id_p}"):
                                if enviar_notificacion(mail, nom, 2, {'cupo': cupo, 'diferencia': dif}):
                                    actualizar_nota(id_p, nota, TAG_ESPERA)
                                    st.toast("Enviado.")
                                    del st.session_state['analisis_activo'][id_p]
                                    st.rerun()

                            if modo_pendientes:
                                valor_cuota = cupo / 3
                                st.code(f"ID: {id_aria}\nImporte: ${valor_cuota:,.2f}\nCuotas: 3")
                                if st.button(f"✅ Cargado Cupo", key=f"ok_p_{id_p}"):
                                    enviar_notificacion(mail, nom, 3)
                                    del st.session_state['analisis_activo'][id_p]
                                    eliminar_etiqueta(id_p, nota)
                                    st.rerun()

                    if st.button("Cerrar", key=f"x_{id_p}"):
                        del st.session_state['analisis_activo'][id_p]
                        st.rerun()
