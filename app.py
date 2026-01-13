import streamlit as st
import requests
import re
import urllib.parse
from datetime import datetime, timezone

# ==========================================
# ⚙️ CONFIGURACIÓN SEGURA (Lectura de Secrets)
# ==========================================
try:
    TN_TOKEN = st.secrets["TN_TOKEN"]
    TN_ID = st.secrets["TN_ID"]
    ARIA_KEY = st.secrets["ARIA_KEY"]
except FileNotFoundError:
    st.error("⚠️ ERROR CRÍTICO: No se configuraron las claves secretas (Secrets) en el panel de Streamlit.")
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
# 🔌 FUNCIONES DE CONEXIÓN
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

# ==========================================
# 🧠 UTILIDADES INTELIGENTES (La Mejora)
# ==========================================
def buscar_cliente(nombre, dni, nota):
    # --- 1. LIMPIEZA DE DATOS ---
    dni_limpio = str(dni).replace(".", "").replace(" ", "").strip()
    nombre_limpio = nombre.strip().lower()
    
    # --- ESTRATEGIA A: BÚSQUEDA POR DNI (La más exacta) ---
    if dni_limpio and len(dni_limpio) > 5:
        res = consultar_api_aria(f"clientes?q={dni_limpio}")
        for c in res:
            dni_aria = str(c.get('cliente_dnicuit','')).replace(".","").strip()
            if dni_aria == dni_limpio:
                return c, "✅ Encontrado por DNI (Tiendanube)"

    # --- ESTRATEGIA B: BÚSQUEDA POR ID EN NOTA (Si el cliente lo escribió) ---
    match = re.search(r'\b\d{3,6}\b', str(nota))
    if match:
        posible_id = match.group()
        res = consultar_api_aria(f"cliente/{posible_id}")
        if res and isinstance(res, list) and len(res) > 0:
            apellido_aria = res[0].get('cliente_apellido', '').lower()
            # Chequeo de seguridad simple: que el apellido coincida un poco
            if apellido_aria in nombre_limpio:
                return res[0], f"✅ Encontrado por ID en Nota ({posible_id})"

    # --- ESTRATEGIA C: BÚSQUEDA POR APELLIDO (El último recurso) ---
    partes_nombre = nombre.split()
    if len(partes_nombre) >= 1:
        apellido = partes_nombre[-1].lower() 
        if len(apellido) > 3: 
            res = consultar_api_aria(f"clientes?q={apellido}")
            for c in res:
                nombre_aria = c.get('cliente_nombre', '').lower()
                apellido_aria_full = c.get('cliente_apellido', '').lower()
                
                # Cruzamos datos para evitar falsos positivos
                if apellido_aria_full in nombre_limpio:
                    return c, "⚠️ Coincidencia por Apellido (Verificar DNI)"

    return None, None

def extraer_productos(pedido):
    lista = []
    for item in pedido.get('products', []):
        lista.append(f"{item.get('name')} ({item.get('quantity')})")
    return ", ".join(lista)

# ==========================================
# 🖥️ INTERFAZ WEB (STREAMLIT)
# ==========================================

st.set_page_config(page_title="Robot Cobranzas SSS", page_icon="🤖", layout="wide")

st.title("🤖 SSServicios - Robot de Cobranzas")

# --- SIDEBAR (Menú Lateral) ---
st.sidebar.header("Panel de Control")
opcion = st.sidebar.radio("Ver:", ["Nuevos (Abiertos)", "Pendientes (Seguimiento)"])

if st.sidebar.button("🔄 Actualizar Lista"):
    st.rerun()

# --- LÓGICA PRINCIPAL ---
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
        elif not modo_pendientes and not es_espera
