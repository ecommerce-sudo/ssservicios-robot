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
TAG_ESPERA = "#ESPERANDO_DIFERENCIA"
CUOTAS_A_GENERAR = 3

# ==========================================
# 🧠 MEMORIA DE SESIÓN
# ==========================================
if 'analisis_activo' not in st.session_state:
    st.session_state['analisis_activo'] = {}

# ==========================================
# 🔌 FUNCIONES DE CONEXIÓN
# ==========================================
def solo_numeros(texto):
    if texto is None: return ""
    return re.sub(r'\D', '', str(texto))

def consultar_api_aria(endpoint):
    """
    Conecta con la API y extrae la lista real de datos,
    manejando la estructura de paginación {'data': [...]}.
    """
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    try:
        # Añadimos verify=False si hay problemas de certificados, pero intentamos normal primero
        res = requests.get(f"{ARIA_URL_BASE}/{endpoint}", headers=headers)
        
        if res.status_code == 200:
            respuesta_json = res.json()
            
            # 1. CASO PAGINACIÓN (La estructura que descubrimos)
            if isinstance(respuesta_json, dict) and "data" in respuesta_json:
                return respuesta_json["data"]
            
            # 2. CASO LISTA DIRECTA (Por si acaso otros endpoints son distintos)
            if isinstance(respuesta_json, list):
                return respuesta_json
            
            # 3. CASO OBJETO ÚNICO (Convertimos a lista para estandarizar)
            if isinstance(respuesta_json, dict):
                return [respuesta_json]
                
        return []
    except Exception as e:
        print(f"Error API: {e}")
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

# ==========================================
# 🕵️ LÓGICA DE BÚSQUEDA
# ==========================================
def buscar_cliente(nombre_tn, dni_tn, nota_tn):
    debug_log = []
    dni_tn_numeros = solo_numeros(dni_tn)

    # 1. ID EN NOTA (Búsqueda Directa)
    match = re.search(r'\b\d{3,6}\b', str(nota_tn))
    if match:
        posible_id = match.group()
        # Al buscar por ID directo, usamos el endpoint singular
        res = consultar_api_aria(f"cliente/{posible_id}")
        if res and len(res) > 0:
            return res[0], f"✅ ID {posible_id} (Nota)", debug_log

    # 2. BÚSQUEDA DIRECTA DNI
    if len(dni_tn_numeros) > 5:
        # endpoint plural 'clientes?q=...' devuelve estructura paginada que ahora manejamos bien
        res_dni = consultar_api_aria(f"clientes?q={dni_tn_numeros}")
        
        if res_dni and len(res_dni) > 0:
            candidato = res_dni[0]
            dni_aria = solo_numeros(candidato.get('cliente_dnicuit',''))
            
            # Verificación flexible
            if (dni_tn_numeros in dni_aria) or (dni_aria in dni_tn_numeros):
                return candidato, "✅ Encontrado por DNI", debug_log

    # 3. BÚSQUEDA POR APELLIDO
    partes_nombre = nombre_tn.split()
    if len(partes_nombre) >= 1:
        apellido_tn = partes_nombre[-1].lower() 
        if len(apellido_tn) > 2:
            res_ape = consultar_api_aria(f"clientes?q={apellido_tn}")
            
            for c in res_ape:
                dni_aria = solo_numeros(c.get('cliente_dnicuit',''))
                if dni_tn_numeros and dni_aria and (dni_tn_numeros in dni_aria):
                    return c, "✅ Apellido > Match DNI", debug_log

    return None, None, debug_log

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
if st.sidebar.button("🔄 Actualizar Lista"): st.rerun()

modo_pendientes = opcion == "Pendientes (Seguimiento)"
estado_api = "any" if modo_pendientes else "open"

with st.spinner('Conectando con Tiendanube...'):
    pedidos = obtener_pedidos(estado_api)

pedidos_filtrados = []
if pedidos:
    for p in pedidos:
        nota = p.get('owner_note') or ""
        es_espera = TAG_ESPERA in nota
        if modo_pendientes and es_espera: pedidos_filtrados.append(p)
        elif not modo_pendientes and not es_espera: pedidos_filtrados.append(p)

if not pedidos_filtrados:
    st.info("💤 No hay pedidos en esta bandeja.")
else:
    st.success(f"Bandeja: {len(pedidos_filtrados)} pedidos")

    for p in pedidos_filtrados:
        id_p = p['id']
        nombre = p['customer']['name']
        dni_tn = p['customer'].get('identification')
        total = float(p['total'])
        nota = p.get('owner_note', '')
        prod_str = extraer_productos(p)

        with st.expander(f"🛒 #{id_p} | {nombre} | ${total:,.0f}", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Productos:** {prod_str}")
                st.write(f"**DNI (TN):** {dni_tn}")
                
            with col2:
                mostrar_analisis = False
                if st.button(f"🔍 Analizar Cliente", key=f"btn_{id_p}"):
                    st.session_state['analisis_activo'][id_p] = True
                    mostrar_analisis = True
                elif st.session_state['analisis_activo'].get(id_p):
                    mostrar_analisis = True

                if mostrar_analisis:
                    cliente_aria, metodo, debug_log = buscar_cliente(nombre, dni_tn, nota)
                    
                    if not cliente_aria:
                        st.error("❌ No encontrado.")
                    else:
                        # === EXTRACCIÓN DE DATOS SEGURA ===
                        # Ahora sabemos los nombres exactos gracias a tu captura
                        id_aria = cliente_aria.get('cliente_id')
                        
                        # Convertimos los strings "111920.00" a float
                        try:
                            cupo = float(cliente_aria.get('clienteScoringFinanciable', 0))
                        except: cupo = 0.0
                            
                        try:
                            saldo = float(cliente_aria.get('cliente_saldo', 0))
                        except: saldo = 0.0

                        st.success(f"{metodo}")
                        st.success(f"🆔 ID Cliente: **{id_aria}**")
                        st.info(f"💰 Cupo: **${cupo:,.0f}** | Saldo: ${saldo:,.0f}")

                        # LÓGICA DE APROBACIÓN
                        if saldo > 100: # Tolerancia de $100 por si quedan decimales
                            st.error(f"⛔ RECHAZADO: Tiene deuda (${saldo:,.0f}).")
                        elif total <= cupo:
                            st.success("🚀 APROBADO: Cupo suficiente.")
                            if st.button(f"💸 COBRAR AHORA", key=f"pagar_{id_p}"):
                                ok, msg = cargar_deuda_aria(id_aria, total, id_p, prod_str)
                                if ok:
                                    st.toast("✅ ¡Cobrado!", icon="🎉")
                                    del st.session_state['analisis_activo'][id_p]
                                    if modo_pendientes: eliminar_etiqueta(id_p, nota)
                                    st.rerun()
                                else:
                                    st.error(f"Error API: {msg}")
                        else:
                            st.warning(f"⚠️ FALTA SALDO: ${total-cupo:,.0f}")
                            if st.button("📌 Pasar a SEGUIMIENTO", key=f"seg_{id_p}"):
                                actualizar_nota(id_p, nota, TAG_ESPERA)
                                del st.session_state['analisis_activo'][id_p]
                                st.rerun()

                    if st.button("Cerrar", key=f"c_{id_p}"):
                        del st.session_state['analisis_activo'][id_p]
                        st.rerun()
