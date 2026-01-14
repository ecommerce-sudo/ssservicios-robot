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
# 🔌 FUNCIONES DE CONEXIÓN Y UTILIDADES
# ==========================================
def solo_numeros(texto):
    if texto is None: return ""
    return re.sub(r'\D', '', str(texto))

def obtener_id_seguro(dato_dict):
    """
    Intenta extraer el ID probando todas las variantes posibles de nombres de clave.
    """
    if not isinstance(dato_dict, dict): return None
    # Lista de posibles nombres que usa la API para el ID
    posibles_keys = ['cliente_id', 'id', 'Id', 'ID', 'codigo', 'clienteId']
    
    for key in posibles_keys:
        val = dato_dict.get(key)
        if val: return str(val)
    return None

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
# 🕵️ LÓGICA DE BÚSQUEDA (MEJORADA)
# ==========================================
def buscar_cliente(nombre_tn, dni_tn, nota_tn):
    debug_log = []
    
    dni_tn_numeros = solo_numeros(dni_tn)
    debug_log.append(f"🔎 INPUT: TN_DNI='{dni_tn_numeros}' | NOMBRE='{nombre_tn}'")

    # --- FUNCIÓN AUXILIAR INTERNA ---
    def obtener_ficha_completa(candidato_parcial, origen):
        # Usamos la nueva función segura para sacar el ID
        posible_id = obtener_id_seguro(candidato_parcial)
        
        if posible_id:
            debug_log.append(f"🧩 ID detectado en '{origen}': {posible_id}")
            # Consultamos el endpoint de detalle para obtener saldo y cupo real
            res_full = consultar_api_aria(f"cliente/{posible_id}")
            if res_full and isinstance(res_full, list) and len(res_full) > 0:
                # Inyectamos el ID encontrado asegurado en la ficha final por si acaso
                res_full[0]['_id_seguro'] = posible_id 
                return res_full[0]
        else:
            debug_log.append(f"⚠️ '{origen}' devolvió datos pero NO encontré campo ID. Keys: {list(candidato_parcial.keys())}")
        
        return None

    # 1. ID EN NOTA (Prioridad Máxima)
    match = re.search(r'\b\d{3,6}\b', str(nota_tn))
    if match:
        posible_id = match.group()
        res = consultar_api_aria(f"cliente/{posible_id}")
        if res and isinstance(res, list) and len(res) > 0:
            res[0]['_id_seguro'] = posible_id
            return res[0], f"✅ ID {posible_id} forzado desde Nota", debug_log

    # 2. BÚSQUEDA DIRECTA DNI
    if len(dni_tn_numeros) > 5:
        res_dni = consultar_api_aria(f"clientes?q={dni_tn_numeros}")
        debug_log.append(f"📡 API Query DNI: {len(res_dni)} resultados")
        
        if res_dni and len(res_dni) > 0:
            candidato_full = obtener_ficha_completa(res_dni[0], "Busqueda DNI")
            
            if candidato_full:
                dni_aria = solo_numeros(candidato_full.get('cliente_dnicuit',''))
                if (dni_tn_numeros in dni_aria) or (dni_aria in dni_tn_numeros):
                    return candidato_full, "✅ Encontrado por DNI (Match Exacto)", debug_log
                else:
                    return candidato_full, f"⚠️ DNI API ({dni_aria}) difiere de TN", debug_log

    # 3. BÚSQUEDA POR APELLIDO
    partes_nombre = nombre_tn.split()
    if len(partes_nombre) >= 1:
        apellido_tn = partes_nombre[-1].lower() 
        if len(apellido_tn) > 2:
            res_ape = consultar_api_aria(f"clientes?q={apellido_tn}")
            debug_log.append(f"📡 API Query Apellido '{apellido_tn}': {len(res_ape)} resultados")
            
            for c in res_ape:
                c_full = obtener_ficha_completa(c, "Busqueda Apellido")
                if c_full:
                    dni_aria = solo_numeros(c_full.get('cliente_dnicuit',''))
                    if dni_tn_numeros and dni_aria and (dni_tn_numeros in dni_aria):
                        return c_full, "✅ Encontrado por Apellido > Match DNI", debug_log

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
                st.write(f"**Nota:** {nota}")
            
            with col2:
                mostrar_analisis = False
                if st.button(f"🔍 Analizar Cliente", key=f"btn_{id_p}"):
                    st.session_state['analisis_activo'][id_p] = True
                    mostrar_analisis = True
                elif st.session_state['analisis_activo'].get(id_p):
                    mostrar_analisis = True

                if mostrar_analisis:
                    cliente_aria, metodo_hallazgo, debug_data = buscar_cliente(nombre, dni_tn, nota)
                    
                    # --- DEBUGGER VISUAL (SIEMPRE VISIBLE POR AHORA) ---
                    with st.status("🛠️ Diagnóstico de Búsqueda", expanded=False):
                        st.write("Log del proceso:")
                        for log in debug_data: st.text(log)
                        if cliente_aria:
                            st.write("⬇️ DATOS CRUDOS RETORNADOS POR API:")
                            st.json(cliente_aria) # <--- AQUÍ VERÁS LOS NOMBRES REALES DE LOS CAMPOS

                    if not cliente_aria:
                        st.error("❌ Cliente no encontrado automáticamente.")
                        # Opción manual...
                        col_m1, col_m2 = st.columns([2,1])
                        id_manual = col_m1.text_input("Ingresar ID Manual:", key=f"in_{id_p}")
                        if col_m2.button("Buscar", key=f"b_man_{id_p}"):
                            res = consultar_api_aria(f"cliente/{id_manual}")
                            if res and len(res) > 0:
                                # Usamos la misma logica segura
                                id_safe = obtener_id_seguro(res[0])
                                if id_safe:
                                    res[0]['_id_seguro'] = id_safe # Inyectamos ID seguro
                                    # Forzamos re-render para que tome la logica de abajo
                                    st.session_state['manual_cliente'] = res[0]
                                else:
                                    st.error("La API trajo datos pero sin ID legible.")
                                    st.json(res[0])

                    # Lógica de visualización unificada (Auto o Manual)
                    cliente_final = st.session_state.get('manual_cliente') if not cliente_aria else cliente_aria
                    if 'manual_cliente' in st.session_state: del st.session_state['manual_cliente'] # Limpieza

                    if cliente_final:
                        # USAMOS EL ID SEGURO QUE CALCULAMOS
                        id_aria = cliente_final.get('_id_seguro', 'ERROR_ID')
                        cupo = float(cliente_final.get('clienteScoringFinanciable', 0))
                        saldo = float(cliente_final.get('cliente_saldo', 0))

                        if id_aria == 'ERROR_ID':
                            st.error("🚨 ERROR CRÍTICO: La API trajo el cliente pero no encuentro el campo 'cliente_id' ni 'id'. Revisa el 'Diagnóstico' arriba.")
                        else:
                            st.success(f"🆔 Cliente Encontrado ID: **{id_aria}**")
                            st.info(f"💰 Cupo: **${cupo:,.0f}** | Saldo: ${saldo:,.0f}")
                            
                            if saldo > 0:
                                st.error("⛔ RECHAZADO: Tiene deuda vigente.")
                            elif total <= cupo:
                                st.success("🚀 APROBADO: Cupo suficiente.")
                                if st.button(f"💸 COBRAR AHORA", key=f"pay_{id_p}"):
                                    ok, msg = cargar_deuda_aria(id_aria, total, id_p, prod_str)
                                    if ok:
                                        st.toast("✅ ¡Cobrado!", icon="🎉")
                                        del st.session_state['analisis_activo'][id_p]
                                        if modo_pendientes: eliminar_etiqueta(id_p, nota)
                                        st.rerun()
                                    else:
                                        st.error(f"Error API: {msg}")
                            else:
                                st.warning(f"⚠️ FALTA SALDO: ${total - cupo:,.0f}")
                                if st.button("📌 Pasar a SEGUIMIENTO", key=f"seg_{id_p}"):
                                    actualizar_nota(id_p, nota, TAG_ESPERA)
                                    del st.session_state['analisis_activo'][id_p]
                                    st.rerun()

                    st.markdown("---")
                    if st.button("Cerrar", key=f"cl_{id_p}"):
                        del st.session_state['analisis_activo'][id_p]
                        st.rerun()
