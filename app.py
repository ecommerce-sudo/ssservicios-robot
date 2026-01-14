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
    # Configuración de correo (Opcional, no rompe si falta)
    EMAIL_USER = st.secrets.get("EMAIL_USER", "")
    EMAIL_PASS = st.secrets.get("EMAIL_PASS", "")
except FileNotFoundError:
    st.error("⚠️ ERROR CRÍTICO: No se encontraron los Secrets (.streamlit/secrets.toml).")
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
    """Deja solo dígitos 0-9"""
    if texto is None: return ""
    return re.sub(r'\D', '', str(texto))

def consultar_api_aria(params):
    """
    Consulta genérica a /clientes usando parámetros (q, ident, etc).
    Maneja la respuesta { data: [...] } o lista directa.
    """
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        # Timeout de 8s para dar tiempo a la base de datos
        res = requests.get(f"{ARIA_URL_BASE}/clientes", headers=headers, params=params, timeout=8)
        
        if res.status_code == 200:
            d = res.json()
            if isinstance(d, dict) and "data" in d: return d["data"]
            if isinstance(d, list): return d
            if isinstance(d, dict): return [d]
        return []
    except Exception as e:
        print(f"Error conexión Aria: {e}")
        return []

def consultar_api_aria_id(cliente_id):
    """Consulta directa por ID (Endpoint singular /cliente/{id})"""
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get(f"{ARIA_URL_BASE}/cliente/{cliente_id}", headers=headers, timeout=5)
        if res.status_code == 200:
            # A veces devuelve el objeto directo, a veces lista
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
        st.warning("⚠️ No se envió el mail: Faltan credenciales en secrets.")
        return True 

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = email_cliente
    
    # 🔴 ESCENARIO 1: RECHAZADO
    if escenario == 1:
        msg['Subject'] = "Información importante sobre tu pedido en SSServicios"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        Muchas gracias por tu compra en nuestra tienda online.<br><br>
        <b>Te informamos que hemos realizado el análisis crediticio correspondiente y, por el momento, no es posible procesar la financiación de este pedido a través de tu factura de servicios; podés probar nuevamente en unos meses.</b><br><br>
        ¡No te preocupes! Si deseas continuar con la compra, puedes hacerlo abonando con <b>tarjeta de crédito, débito o transferencia bancaria</b>. Por favor, avísanos respondiendo a este correo si prefieres cambiar el medio de pago.<br><br>
        Quedamos a tu disposición.<br><br>
        Saludos cordiales,<br>El equipo de SSServicios
        """

    # 🟡 ESCENARIO 2: DIFERENCIA
    elif escenario == 2:
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        alias = "TU.ALIAS.AQUI" # <--- CAMBIAR
        cbu = "0000000000000000000000" # <--- CAMBIAR
        
        msg['Subject'] = "Acción requerida: Tu pedido en SSServicios (Cupo Disponible)"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        ¡Tenemos buenas noticias! Hemos verificado tu cuenta y tienes un cupo disponible de <b>${cupo:,.0f}</b> para financiar tu compra en cuotas sin interés.<br><br>
        Como el total de tu pedido supera ese monto, para aprobar el envío necesitamos que abones la diferencia de <b>${dif:,.0f}</b> mediante transferencia bancaria.<br><br>
        <b>Datos para la transferencia:</b><br>
        <ul>
            <li><b>Alias:</b> {alias}</li>
            <li><b>CBU:</b> {cbu}</li>
        </ul>
        Por favor, <b>responde a este correo adjuntando el comprobante de pago</b>. Una vez recibido, procesaremos el resto de la compra en tu próxima factura y despacharemos tu pedido.<br><br>
        ¡Esperamos tu confirmación!<br>Saludos,<br>El equipo de SSServicios
        """

    # 🟢 ESCENARIO 3: APROBADO
    elif escenario == 3:
        msg['Subject'] = "¡Felicitaciones! Tu compra fue aprobada ✅"
        cuerpo = f"""
        Hola {nombre_cliente},<br><br>
        Te confirmamos que tu solicitud de financiación ha sido <b>aprobada exitosamente</b>.<br><br>
        El importe de tu compra se verá reflejado en tu próxima factura de SSServicios. Tal como se indicó en la tienda, el cobro se realizará en <b>3 cuotas sin interés</b>.<br><br>
        Ya estamos preparando tu pedido. Pronto recibirás novedades sobre el envío o retiro.<br><br>
        ¡Muchas gracias por confiar en nosotros!<br>Saludos,<br>El equipo de SSServicios
        """

    msg.attach(MIMEText(cuerpo, 'html'))
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, email_cliente, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"Error enviando mail: {e}")
        return False

# ==========================================
# 🧠 LÓGICA DE BÚSQUEDA (EL CEREBRO)
# ==========================================
def buscar_cliente_cascada(nombre_tn, dni_tn, nota_tn):
    
    # --- 1️⃣ NIVEL 1: ID EN NOTA (Prioridad Absoluta) ---
    # Busca números aislados de 3 a 7 cifras
    ids_en_nota = re.findall(r'\b\d{3,7}\b', str(nota_tn))
    for posible_id in ids_en_nota:
        res = consultar_api_aria_id(posible_id) 
        if res and len(res) > 0 and res[0].get('cliente_id'):
            return res[0], f"✅ ID {posible_id} (Encontrado en Nota)"

    # --- 2️⃣ NIVEL 2: DNI / CUIT (Uso de 'ident') ---
    dni_input = solo_numeros(dni_tn) 
    numeros_a_probar = []
    
    # A. Agregamos el número tal cual viene (Ej: 20301441313)
    if len(dni_input) > 5:
        numeros_a_probar.append(dni_input)
    
    # B. Si es CUIT (11 dígitos), extraemos el DNI del medio (Ej: 30144131)
    # Esto soluciona el problema de que Aria tenga DNI y TN mande CUIT
    if len(dni_input) == 11:
        dni_puro = dni_input[2:10]
        numeros_a_probar.append(dni_puro)

    for numero in numeros_a_probar:
        # Usamos 'ident' que busca coincidencia exacta de documento
        res = consultar_api_aria({'ident': numero}) 
        
        if res:
            # Validación de seguridad (Match inverso)
            for c in res:
                dni_aria = solo_numeros(c.get('cliente_dnicuit', ''))
                # ¿El número buscado está contenido en el de Aria o viceversa?
                if numero in dni_aria or dni_aria in numero:
                    return c, f"✅ Encontrado por DNI/CUIT: {numero}"
        
        # Si 'ident' falla, probamos 'q' (texto libre) como respaldo
        res_q = consultar_api_aria({'q': numero})
        if res_q:
             for c in res_q:
                dni_aria = solo_numeros(c.get('cliente_dnicuit', ''))
                if numero in dni_aria or dni_aria in numero:
                    return c, f"✅ Encontrado por TEXTO (Q): {numero}"

    # --- 3️⃣ NIVEL 3: APELLIDO (Último Recurso) ---
    partes = nombre_tn.replace(",","").split()
    if len(partes) >= 1:
        apellido = partes[-1]
        if len(apellido) > 3:
            res = consultar_api_aria({'q': apellido})
            if res:
                # Filtro estricto: Si TN tenía un DNI, debe coincidir
                if numeros_a_probar:
                    dni_objetivo = numeros_a_probar[-1] # DNI puro
                    for c in res:
                        dni_c = solo_numeros(c.get('cliente_dnicuit', ''))
                        if dni_objetivo in dni_c:
                            return c, "✅ Apellido + Coincidencia DNI"
                
                # Si TN no tenía DNI, chequeamos coincidencia de Nombre
                else:
                     palabras_tn = set(nombre_tn.lower().split())
                     for c in res:
                        nombre_aria = (str(c.get('cliente_nombre','')) + " " + str(c.get('cliente_apellido',''))).lower()
                        palabras_aria = set(nombre_aria.split())
                        if len(palabras_tn.intersection(palabras_aria)) >= 2:
                             return c, "✅ Apellido + Nombre Coincidentes"

    return None, "❌ No encontrado."

def extraer_productos(pedido):
    return ", ".join([f"{i.get('name')} ({i.get('quantity')})" for i in pedido.get('products', [])])

# ==========================================
# 🖥️ INTERFAZ DE USUARIO
# ==========================================
st.set_page_config(page_title="Asistente Ventas", page_icon="🤖", layout="wide")

st.title("🤖 Asistente de Ventas Contrafactura")
st.markdown("**Modo:** Validación y Asistencia de Carga.")

# --- SIDEBAR ---
st.sidebar.header("Panel de Control")
opcion = st.sidebar.radio("Bandeja de Trabajo:", ["Nuevos (Abiertos)", "Pendientes (Diferencia)"])
if st.sidebar.button("🔄 Actualizar Pedidos"): st.rerun()

modo_pendientes = opcion == "Pendientes (Diferencia)"
estado_tn = "any" if modo_pendientes else "open"

# --- CARGA ---
with st.spinner('Conectando con Tiendanube...'):
    pedidos_raw = obtener_pedidos(estado_tn)

pedidos_filtrados = []
if pedidos_raw:
    for p in pedidos_raw:
        nota = p.get('owner_note') or ""
        es_espera = TAG_ESPERA in nota
        if modo_pendientes and es_espera: pedidos_filtrados.append(p)
        elif not modo_pendientes and not es_espera: pedidos_filtrados.append(p)

# --- LISTADO ---
if not pedidos_filtrados:
    st.info("✅ Bandeja al día. No hay pedidos pendientes de acción.")
else:
    st.success(f"Gestión: {len(pedidos_filtrados)} pedidos en bandeja.")

    for p in pedidos_filtrados:
        id_p = p['id']
        nombre = p['customer']['name']
        dni_tn = p['customer'].get('identification') or "No indica"
        email_tn = p['customer'].get('email')
        total = float(p['total'])
        nota = p.get('owner_note', '')
        prod_str = extraer_productos(p)

        with st.expander(f"🛒 Pedido #{id_p} | {nombre} | ${total:,.0f}", expanded=True):
            col_info, col_action = st.columns([1, 1])
            
            with col_info:
                st.markdown(f"**Items:** {prod_str}")
                st.markdown(f"**DNI/CUIT:** `{dni_tn}`")
                st.markdown(f"**Nota:** {nota}")
            
            with col_action:
                mostrar = False
                if st.button(f"🔍 Analizar Cliente", key=f"btn_{id_p}"):
                    st.session_state['analisis_activo'][id_p] = True
                    mostrar = True
                elif st.session_state['analisis_activo'].get(id_p): mostrar = True

                if mostrar:
                    st.markdown("---")
                    with st.spinner("Consultando Aria..."):
                        cliente, mensaje = buscar_cliente_cascada(nombre, dni_tn, nota)

                    if not cliente:
                        st.error(mensaje)
                        st.warning("💡 No se encontró. Busca manualmente el ID en Aria y agrégalo a la nota.")
                    else:
                        # Extracción segura
                        id_aria = cliente.get('cliente_id', 'Error')
                        try: cupo = float(cliente.get('clienteScoringFinanciable', 0))
                        except: cupo = 0.0
                        try: saldo = float(cliente.get('cliente_saldo', 0))
                        except: saldo = 0.0

                        # RESULTADO DE LA BÚSQUEDA
                        st.success(f"{mensaje}")
                        st.success(f"🆔 ID CLIENTE ARIA: **{id_aria}**") # Aquí devolvemos el ID recuperado
                        
                        c_saldo, c_cupo = st.columns(2)
                        c_saldo.metric("Saldo Deuda", f"${saldo:,.0f}", delta_color="inverse")
                        c_cupo.metric("Cupo Disponible", f"${cupo:,.0f}")

                        # SEMÁFORO DE DECISIÓN
                        
                        # 🔴 CASO 1: DEUDA
                        if saldo > 100: 
                            st.error("⛔ RECHAZADO: Cliente con deuda vigente.")
                            if st.button("📧 Enviar Rechazo y Avisar", key=f"mail_r_{id_p}"):
                                if enviar_notificacion(email_tn, nombre, 1):
                                    st.success("✅ Correo enviado.")
                        
                        # 🟢 CASO 3: APROBADO (TOTAL)
                        elif total <= cupo:
                            st.success("🚀 APROBADO: El cupo cubre el total.")
                            st.info("📝 **Instrucción de Carga Manual en Aria:**")
                            
                            valor_cuota = total / 3
                            st.code(f"""
                            ID Cliente: {id_aria}
                            ---
                            CARGAR ÍTEM ADICIONAL:
                            > Importe (Valor Cuota): ${valor_cuota:,.2f}
                            > Cantidad Cuotas: 3
                            > Descripcion: Compra TN #{id_p}
                            """)
                            
                            if st.button(f"✅ Ya lo cargué manualmente", key=f"confirm_{id_p}"):
                                if enviar_notificacion(email_tn, nombre, 3):
                                    st.toast("Notificación enviada.")
                                del st.session_state['analisis_activo'][id_p]
                                if modo_pendientes: eliminar_etiqueta(id_p, nota)
                                st.rerun()

                        # 🟡 CASO 2: DIFERENCIA (PENDIENTE)
                        else:
                            dif = total - cupo
                            st.warning(f"⚠️ FALTA SALDO: El cliente debe pagar ${dif:,.0f}")
                            
                            # Opción A: Pedir plata
                            if st.button(f"📧 Pedir Diferencia (${dif:,.0f})", key=f"ask_{id_p}"):
                                datos = {'cupo': cupo, 'diferencia': dif}
                                if enviar_notificacion(email_tn, nombre, 2, datos):
                                    actualizar_nota(id_p, nota, TAG_ESPERA)
                                    st.toast("Correo enviado. Pedido pasado a 'Pendientes'.")
                                    del st.session_state['analisis_activo'][id_p]
                                    st.rerun()
                            
                            # Opción B (Solo en pendientes): Cargar Cupo
                            if modo_pendientes:
                                st.markdown("---")
                                st.info("📝 **Si ya pagó, carga esto:**")
                                valor_cuota = cupo / 3
                                st.code(f"""
                                ID Cliente: {id_aria}
                                ---
                                CARGAR ÍTEM ADICIONAL:
                                > Importe (Valor Cuota): ${valor_cuota:,.2f}
                                > Cantidad Cuotas: 3
                                """)
                                
                                if st.button(f"✅ Ya cargué el Cupo", key=f"ok_partial_{id_p}"):
                                    enviar_notificacion(email_tn, nombre, 3)
                                    st.toast("Proceso finalizado.")
                                    eliminar_etiqueta(id_p, nota)
                                    del st.session_state['analisis_activo'][id_p]
                                    st.rerun()

                    if st.button("Cerrar Panel", key=f"close_{id_p}"):
                        del st.session_state['analisis_activo'][id_p]
                        st.rerun()
