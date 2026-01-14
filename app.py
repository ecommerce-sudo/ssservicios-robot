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
    # Si no configuras el mail, el sistema avisa pero no falla
    EMAIL_USER = st.secrets.get("EMAIL_USER", "")
    EMAIL_PASS = st.secrets.get("EMAIL_PASS", "")
except FileNotFoundError:
    st.error("⚠️ ERROR: No se encontró el archivo de secretos (.streamlit/secrets.toml).")
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
# 🔌 FUNCIONES DE CONEXIÓN (Low Level)
# ==========================================
def solo_numeros(texto):
    """Elimina todo lo que no sea dígito 0-9"""
    if texto is None: return ""
    return re.sub(r'\D', '', str(texto))

def consultar_api_aria(endpoint):
    """
    Conecta a Aria y maneja la estructura de respuesta.
    Soporta respuestas directas [], listas dentro de 'data', o dict único.
    """
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get(f"{ARIA_URL_BASE}/{endpoint}", headers=headers, timeout=8)
        if res.status_code == 200:
            d = res.json()
            # Caso 1: Paginación moderna de Laravel { data: [...] }
            if isinstance(d, dict) and "data" in d: return d["data"]
            # Caso 2: Lista directa [...]
            if isinstance(d, list): return d
            # Caso 3: Objeto único {...} -> Lo metemos en lista
            if isinstance(d, dict): return [d]
        return []
    except Exception as e:
        print(f"Error conexión Aria: {e}")
        return []

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
# 📧 GESTOR DE CORREOS (Textos Aprobados)
# ==========================================
def enviar_notificacion(email_cliente, nombre_cliente, escenario, datos_extra={}):
    if not EMAIL_USER or not EMAIL_PASS:
        st.warning("⚠️ Correo no enviado: Faltan credenciales en secrets.")
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

    # 🟡 ESCENARIO 2: DIFERENCIA (FALTA CUPO)
    elif escenario == 2:
        cupo = datos_extra.get('cupo', 0)
        dif = datos_extra.get('diferencia', 0)
        # --- DATOS BANCARIOS ---
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
        st.error(f"Error técnico enviando mail: {e}")
        return False

# ==========================================
# 🧠 LÓGICA DE BÚSQUEDA: "CASCADA BLINDADA"
# ==========================================
def buscar_cliente_cascada(nombre_tn, dni_tn, nota_tn):
    debug_info = [] # Para ver qué pasó internamente si falla
    
    # --- 1️⃣ NIVEL 1: ID EN NOTA (HARD MATCH) ---
    # Busca cualquier secuencia de 3 a 7 dígitos en la nota
    posibles_ids = re.findall(r'\b\d{3,7}\b', str(nota_tn))
    for pid in posibles_ids:
        res = consultar_api_aria(f"cliente/{pid}")
        # Si la API devuelve una lista con datos y tiene un ID válido
        if res and len(res) > 0 and res[0].get('cliente_id'):
            return res[0], f"✅ ID {pid} encontrado en nota"

    # --- 2️⃣ NIVEL 2: DNI / CUIT (SMART MATCH) ---
    dni_input_limpio = solo_numeros(dni_tn)
    lista_intentos = []

    if len(dni_input_limpio) > 5:
        # Intento A: Lo que escribió el usuario tal cual (limpio)
        lista_intentos.append(dni_input_limpio)
        
        # Intento B: Si es CUIT (11 dígitos), extraemos el DNI del medio
        # Estructura XY-DNI-Z. Eliminamos 2 chars al inicio y 1 al final.
        if len(dni_input_limpio) == 11:
            dni_puro = dni_input_limpio[2:10]
            lista_intentos.append(dni_puro)
            
        for intento in lista_intentos:
            res = consultar_api_aria(f"clientes?q={intento}")
            if res:
                # VALIDACIÓN CRUZADA:
                # Chequeamos que el número buscado esté realmente en los datos de Aria
                for candidato in res:
                    dni_aria = solo_numeros(candidato.get('cliente_dnicuit', ''))
                    # ¿El intento está en Aria O Aria está en el intento?
                    if (intento in dni_aria) or (dni_aria in intento):
                        return candidato, f"✅ Encontrado por Doc: {intento}"

    # --- 3️⃣ NIVEL 3: NOMBRE (FUZZY MATCH) ---
    # Busca por apellido (última palabra) y valida cruzando palabras
    partes = nombre_tn.replace(",","").split()
    if len(partes) >= 1:
        apellido = partes[-1]
        if len(apellido) > 2:
            res = consultar_api_aria(f"clientes?q={apellido}")
            if res:
                palabras_tn = set(nombre_tn.lower().split())
                
                for c in res:
                    # Construimos nombre completo de Aria
                    nombre_aria = (str(c.get('cliente_nombre','')) + " " + str(c.get('cliente_apellido',''))).lower()
                    palabras_aria = set(nombre_aria.split())
                    
                    # Intersección de palabras
                    coincidencias = palabras_tn.intersection(palabras_aria)
                    
                    # Criterio: Al menos 2 palabras coinciden (Nombre + Apellido)
                    # O si el nombre TN es muy corto, coincidencia total
                    if len(coincidencias) >= 2:
                        return c, "✅ Encontrado por Nombre (Coincidencia)"

    return None, "❌ No encontrado (Revisar manualmente)"

def extraer_productos(pedido):
    items = [f"{i.get('name')} x{i.get('quantity')}" for i in pedido.get('products', [])]
    return ", ".join(items)

# ==========================================
# 🖥️ INTERFAZ DE USUARIO (OPERADOR)
# ==========================================
st.set_page_config(page_title="Asistente de Ventas", page_icon="🤖", layout="wide")

st.title("🤖 Asistente de Ventas Contrafactura")
st.markdown("**Modo:** Validación y Asistencia de Carga.")

# --- SIDEBAR ---
st.sidebar.header("Panel de Control")
opcion = st.sidebar.radio("Bandeja de Trabajo:", ["Nuevos (Abiertos)", "Pendientes (Diferencia)"])

if st.sidebar.button("🔄 Actualizar Pedidos"):
    st.cache_data.clear()
    st.rerun()

modo_pendientes = opcion == "Pendientes (Diferencia)"
estado_tn = "any" if modo_pendientes else "open"

# --- CARGA DE DATOS ---
with st.spinner('Conectando con Tiendanube...'):
    pedidos_raw = obtener_pedidos(estado_tn)

# Filtrado local de etiquetas
pedidos_filtrados = []
if pedidos_raw:
    for p in pedidos_raw:
        nota = p.get('owner_note') or ""
        es_espera = TAG_ESPERA in nota
        
        if modo_pendientes and es_espera:
            pedidos_filtrados.append(p)
        elif not modo_pendientes and not es_espera:
            pedidos_filtrados.append(p)

# --- VISUALIZACIÓN ---
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

        # Tarjeta del Pedido
        with st.expander(f"🛒 Pedido #{id_p} | {nombre} | ${total:,.0f}", expanded=True):
            col_info, col_action = st.columns([1, 1])
            
            with col_info:
                st.markdown(f"**Items:** {prod_str}")
                st.markdown(f"**DNI/CUIT:** `{dni_tn}`")
                st.markdown(f"**Nota:** {nota}")
            
            with col_action:
                mostrar_analisis = False
                
                # Botón de activación
                if st.button(f"🔍 Analizar Cliente", key=f"btn_{id_p}"):
                    st.session_state['analisis_activo'][id_p] = True
                    mostrar_analisis = True
                elif st.session_state['analisis_activo'].get(id_p):
                    mostrar_analisis = True

                # LÓGICA DE ANÁLISIS
                if mostrar_analisis:
                    st.markdown("---")
                    with st.spinner("Consultando Aria..."):
                        cliente, mensaje_hallazgo = buscar_cliente_cascada(nombre, dni_tn, nota)

                    if not cliente:
                        st.error(mensaje_hallazgo)
                        st.warning("💡 Acción Manual: Busca el ID en Aria y agrégalo a la nota del pedido.")
                    else:
                        # Extracción de datos
                        id_aria = cliente.get('cliente_id', 'Error')
                        try: cupo = float(cliente.get('clienteScoringFinanciable', 0))
                        except: cupo = 0.0
                        try: saldo = float(cliente.get('cliente_saldo', 0))
                        except: saldo = 0.0

                        # Resultado de Búsqueda
                        st.success(f"{mensaje_hallazgo} | **ID: {id_aria}**")
                        
                        # Métricas
                        c_saldo, c_cupo = st.columns(2)
                        c_saldo.metric("Saldo Deuda", f"${saldo:,.0f}", delta_color="inverse")
                        c_cupo.metric("Cupo Disponible", f"${cupo:,.0f}")

                        # SEMÁFORO DE DECISIÓN
                        
                        # 🔴 CASO 1: DEUDA (RECHAZADO)
                        if saldo > 100: 
                            st.error("⛔ RECHAZADO: Cliente con deuda vigente.")
                            st.info("No se puede financiar. Envía el aviso de rechazo.")
                            
                            if st.button("📧 Enviar Rechazo y Avisar", key=f"mail_r_{id_p}"):
                                if enviar_notificacion(email_tn, nombre, 1):
                                    st.success("✅ Correo enviado exitosamente.")
                        
                        # 🟢 CASO 3: APROBADO (TOTAL)
                        elif total <= cupo:
                            st.success("🚀 APROBADO: El cupo cubre el total.")
                            
                            st.markdown("### 📝 Instrucción de Carga Manual")
                            st.info("Copia estos datos exactos en Aria (Ítem Adicional):")
                            
                            valor_cuota = total / 3
                            st.code(f"""
                            ID Cliente: {id_aria}
                            ---
                            Importe (Valor Cuota): ${valor_cuota:,.2f}
                            Cantidad Cuotas: 3
                            Descripcion: Compra TN #{id_p}
                            """)
                            
                            if st.button(f"✅ Ya lo cargué manualmente", key=f"confirm_{id_p}"):
                                # Enviamos mail de éxito
                                if enviar_notificacion(email_tn, nombre, 3):
                                    st.toast("Notificación enviada al cliente.")
                                
                                # Limpieza
                                del st.session_state['analisis_activo'][id_p]
                                if modo_pendientes: eliminar_etiqueta(id_p, nota)
                                st.rerun()

                        # 🟡 CASO 2: DIFERENCIA (PENDIENTE)
                        else:
                            dif = total - cupo
                            st.warning(f"⚠️ FALTA SALDO: El cliente debe pagar ${dif:,.0f}")
                            
                            # Opción A: Pedir la plata
                            if st.button(f"📧 Pedir Diferencia (${dif:,.0f})", key=f"ask_{id_p}"):
                                datos = {'cupo': cupo, 'diferencia': dif}
                                if enviar_notificacion(email_tn, nombre, 2, datos):
                                    actualizar_nota(id_p, nota, TAG_ESPERA)
                                    st.toast("Correo enviado. Pedido pasado a 'Pendientes'.")
                                    del st.session_state['analisis_activo'][id_p]
                                    st.rerun()
                            
                            # Opción B (Solo en pendientes): Cargar el cupo si ya pagó
                            if modo_pendientes:
                                st.markdown("---")
                                st.markdown("### ¿Ya pagó la diferencia?")
                                st.info("Carga el monto financiado (Cupo) en Aria:")
                                
                                valor_cuota = cupo / 3
                                st.code(f"""
                                ID Cliente: {id_aria}
                                ---
                                Importe (Valor Cuota): ${valor_cuota:,.2f}
                                Cantidad Cuotas: 3
                                """)
                                
                                if st.button(f"✅ Ya cargué el Cupo", key=f"ok_partial_{id_p}"):
                                    enviar_notificacion(email_tn, nombre, 3)
                                    st.toast("Proceso finalizado.")
                                    eliminar_etiqueta(id_p, nota)
                                    del st.session_state['analisis_activo'][id_p]
                                    st.rerun()

                    # Botón cerrar
                    if st.button("Cerrar Panel", key=f"close_{id_p}"):
                        del st.session_state['analisis_activo'][id_p]
                        st.rerun()
