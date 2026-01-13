import streamlit as st
import requests
import re
import urllib.parse
from datetime import datetime, timezone

# ==========================================
# ⚙️ CONFIGURACIÓN SEGURA
# ==========================================
try:
    TN_TOKEN = st.secrets["TN_TOKEN"]
    TN_ID = st.secrets["TN_ID"]
    ARIA_KEY = st.secrets["ARIA_KEY"]
except FileNotFoundError:
    st.error("⚠️ ERROR CRÍTICO: No se configuraron las claves secretas (Secrets).")
    st.stop()
except KeyError as e:
    st.error(f"⚠️ FALTA UNA CLAVE: No encontré {e} en los Secrets.")
    st.stop()

# Configuración fija
TN_USER_AGENT = "RobotWeb (24705)"
ARIA_URL_BASE = "https://api.anatod.ar/api"
ARIA_USUARIO_ID = 374
HORAS_PARA_VENCIMIENTO = 24  
TAG_ESPERA = "#ESPERANDO_DIFERENCIA"
CUOTAS_A_GENERAR = 3

# ==========================================
# 🧠 MEMORIA DE SESIÓN (Para recordar IDs)
# ==========================================
if 'clientes_identificados' not in st.session_state:
    st.session_state['clientes_identificados'] = {}

# ==========================================
# 🔌 FUNCIONES
# ==========================================
def consultar_api_aria(endpoint):
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get(f"{ARIA_URL_BASE}/{endpoint}", headers=headers)
        if res.status_code == 200:
            datos = res.json()
            if isinstance(datos, dict): return [datos]
            if isinstance(datos, list): return datos
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
    payload = {"owner_note": nota_final}
    requests.put(url, headers=headers, json=payload)

def eliminar_etiqueta(id_pedido, nota_actual):
    url = f"https://api.tiendanube.com/v1/{TN_ID}/orders/{id_pedido}"
    headers = {'Authentication': f'bearer {TN_TOKEN}', 'User-Agent': TN_USER_AGENT}
    nota_limpia = nota_actual.replace(TAG_ESPERA, "").strip()
    payload = {"owner_note": nota_limpia}
    requests.put(url, headers=headers, json=payload)

def cargar_deuda_aria(id_cliente, monto_total, orden_id, lista_productos):
    valor_cuota = round(monto_total / CUOTAS_A_GENERAR, 2)
    descripcion = f"Compra en TN #{orden_id}: {lista_productos}"
    if len(descripcion) > 250: descripcion = descripcion[:247] + "..."

    url = f"{ARIA_URL_BASE}/adicional"
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json", "Accept": "application/json"}
    
    payload = {
        "adicional_cliente": id_cliente,
        "adicional_descripcion": descripcion,
        "adicional_tipo": "M",          
        "adicional_moneda": "ML",       
        "adicional_importe": str(valor_cuota),
        "adicional_meses": str(CUOTAS_A_GENERAR), 
        "adicional_cotizacion": "0",
        "adicional_usuario": ARIA_USUARIO_ID 
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload)
        return res.status_code in [200, 201], res.text
    except Exception as e: 
        return False, str(e)

def buscar_cliente(nombre, dni, nota):
    dni_limpio = str(dni).replace(".", "").replace(" ", "").strip()
    nombre_limpio = nombre.strip().lower()
    
    if dni_limpio and len(dni_limpio) > 5:
        res = consultar_api_aria(f"clientes?q={dni_limpio}")
        for c in res:
            dni_aria = str(c.get('cliente_dnicuit','')).replace(".","").strip()
            if dni_aria == dni_limpio:
                return c, "✅ Encontrado por DNI (Tiendanube)"

    match = re.search(r'\b\d{3,6}\b', str(nota))
    if match:
        posible_id = match.group()
        res = consultar_api_aria(f"cliente/{posible_id}")
        if res and isinstance(res, list) and len(res) > 0:
            apellido_aria = res[0].get('cliente_apellido', '').lower()
            if apellido_aria in nombre_limpio:
                return res[0], f"✅ Encontrado por ID en Nota ({posible_id})"

    partes_nombre = nombre.split()
    if len(partes_nombre) >= 1:
        apellido = partes_nombre[-1].lower() 
        if len(apellido) > 3: 
            res = consultar_api_aria(f"clientes?q={apellido}")
            for c in res:
                nombre_aria = c.get('cliente_nombre', '').lower()
                apellido_aria_full = c.get('cliente_apellido', '').lower()
                if apellido_aria_full in nombre_limpio:
                    return c, "⚠️ Coincidencia por Apellido (Verificar DNI)"

    return None, None

def extraer_productos(pedido):
    lista = []
    for item in pedido.get('products', []):
        lista.append(f"{item.get('name')} ({item.get('quantity')})")
    return ", ".join(lista)

# ==========================================
# 🖥️ INTERFAZ WEB
# ==========================================

st.set_page_config(page_title="Robot Cobranzas SSS", page_icon="🤖", layout="wide")

st.title("🤖 SSServicios - Robot de Cobranzas")

st.sidebar.header("Panel de Control")
opcion = st.sidebar.radio("Ver:", ["Nuevos (Abiertos)", "Pendientes (Seguimiento)"])

if st.sidebar.button("🔄 Actualizar Lista"):
    st.rerun()

modo_pendientes = opcion == "Pendientes (Seguimiento)"
estado_api = "any" if modo_pendientes else "open"

with st.spinner('Conectando con Tiendanube...'):
    pedidos = obtener_pedidos(estado_api)

if not pedidos:
    st.info("💤 No se encontraron pedidos.")
else:
    pedidos_filtrados = []
    for p in pedidos:
        nota = p.get('owner_note') or ""
        es_espera = TAG_ESPERA in nota
        
        if modo_pendientes and es_espera:
            pedidos_filtrados.append(p)
        elif not modo_pendientes and not es_espera:
            pedidos_filtrados.append(p)

    st.success(f"Se encontraron {len(pedidos_filtrados)} pedidos en esta bandeja.")

    for p in pedidos_filtrados:
        id_p = p['id']
        nombre = p['customer']['name']
        total = float(p['total'])
        nota = p.get('owner_note', '')
        metodo = p.get('payment_details', {}).get('method', '').lower()
        es_manual = 'custom' in metodo or 'convenir' in metodo
        prod_str = extraer_productos(p)

        # --- LÓGICA DEL TÍTULO DINÁMICO ---
        # Verificamos si ya "recordamos" el ID de este cliente en esta sesión
        id_memoria = st.session_state['clientes_identificados'].get(id_p)
        
        if id_memoria:
            # Si lo recordamos, lo mostramos en el título
            titulo_tarjeta = f"🛒 #{id_p} | {nombre} | 🆔 CL: {id_memoria} | ${total:,.0f}"
        else:
            titulo_tarjeta = f"🛒 #{id_p} | {nombre} | ${total:,.0f}"

        with st.expander(titulo_tarjeta, expanded=True):
            
            if not es_manual and not modo_pendientes:
                st.warning(f"⚠️ Pago: '{metodo}'. El robot suele ignorar esto por seguridad.")

            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Productos:** {prod_str}")
                st.write(f"**DNI (TN):** {p['customer'].get('identification')}")
                st.write(f"**Nota:** {nota}")
            
            with col2:
                # Botón de Análisis
                if st.button(f"🔍 Analizar Cliente", key=f"btn_{id_p}"):
                    
                    cliente_aria, metodo_hallazgo = buscar_cliente(nombre, p['customer'].get('identification'), nota)
                    
                    if not cliente_aria:
                        st.error("❌ Cliente no encontrado en ARIA.")
                    else:
                        id_aria = cliente_aria.get('cliente_id')
                        # --- GUARDAMOS EN MEMORIA ---
                        st.session_state['clientes_identificados'][id_p] = id_aria
                        
                        cupo = float(cliente_aria.get('clienteScoringFinanciable', 0))
                        saldo = float(cliente_aria.get('cliente_saldo', 0))
                        
                        st.info(f"{metodo_hallazgo}")
                        st.success(f"✅ CLIENTE: **{id_aria}**") 
                        st.info(f"💰 Cupo: **${cupo:,.0f}** | Saldo: ${saldo:,.0f}")
                        
                        if saldo > 0:
                            st.error("⛔ RECHAZADO: Tiene deuda vigente.")
                        elif total <= cupo:
                            st.success("🚀 APROBADO: Tiene cupo suficiente.")
                            
                            if st.button(f"💸 COBRAR AHORA", key=f"cobrar_{id_p}"):
                                ok, msg = cargar_deuda_aria(id_aria, total, id_p, prod_str)
                                if ok:
                                    st.toast("✅ ¡Cobrado exitosamente!", icon="🎉")
                                    if modo_pendientes:
                                        eliminar_etiqueta(id_p, nota)
                                        st.rerun()
                                    else:
                                        st.rerun()
                                else:
                                    st.error(f"Fallo Aria: {msg}")
                        else:
                            dif = total - cupo
                            st.warning(f"⚠️ FALTA SALDO: ${dif:,.0f}")
                            telefono = p['customer'].get('phone') or p['billing_address'].get('phone')
                            msj_wa = f"Hola {nombre}, falta abonar ${dif:,.0f} para tu pedido #{id_p}."
                            link_wa = f"https://wa.me/{telefono}?text={urllib.parse.quote(msj_wa)}"
                            st.markdown(f"[📲 Enviar WhatsApp]({link_wa})")
                            
                            if not modo_pendientes:
                                if st.button("📌 Pasar a SEGUIMIENTO", key=f"seg_{id_p}"):
                                    actualizar_nota(id_p, nota, TAG_ESPERA)
                                    st.rerun()
                            else:
                                if st.button("🧹 Ya pagó (Borrar)", key=f"clean_{id_p}"):
                                    eliminar_etiqueta(id_p, nota)
                                    st.rerun()
