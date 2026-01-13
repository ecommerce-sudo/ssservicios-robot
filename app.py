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

# --- 🧠 HERRAMIENTAS DE LIMPIEZA ---
def solo_numeros(texto):
    """Elimina todo lo que no sea un dígito 0-9"""
    if not texto: return ""
    return re.sub(r'\D', '', str(texto))

def hay_coincidencia_palabras(texto_aria, texto_tn):
    if not texto_aria or not texto_tn: return False
    palabras_aria = set(texto_aria.lower().replace(".","").replace(",","").split())
    palabras_tn = set(texto_tn.lower().replace(".","").replace(",","").split())
    palabras_aria = {p for p in palabras_aria if len(p) > 2}
    palabras_tn = {p for p in palabras_tn if len(p) > 2}
    return len(palabras_aria.intersection(palabras_tn)) > 0

def buscar_cliente(nombre_tn, dni_tn, nota_tn):
    debug_log = []
    
    # 1. PREPARACIÓN DE DATOS (LIMPIEZA NUCLEAR)
    dni_tn_numeros = solo_numeros(dni_tn)
    nombre_tn_limpio = nombre_tn.strip().lower()
    
    debug_log.append(f"🔎 TN Input: Nombre='{nombre_tn}', DNI='{dni_tn}' -> Clean='{dni_tn_numeros}'")

    # =========================================================================
    # A. ID EN NOTA (Prioridad Máxima)
    # =========================================================================
    match = re.search(r'\b\d{3,6}\b', str(nota_tn))
    if match:
        posible_id = match.group()
        res = consultar_api_aria(f"cliente/{posible_id}")
        if res and isinstance(res, list) and len(res) > 0:
            cliente = res[0]
            dni_aria_numeros = solo_numeros(cliente.get('cliente_dnicuit',''))
            nombre_completo_aria = f"{cliente.get('cliente_nombre','')} {cliente.get('cliente_apellido','')}"
            
            # Comparación Nuclear
            if dni_tn_numeros and dni_aria_numeros and (dni_tn_numeros in dni_aria_numeros or dni_aria_numeros in dni_tn_numeros):
                 return cliente, f"✅ ID {posible_id} confirmado por DNI/CUIT", debug_log
            elif hay_coincidencia_palabras(nombre_completo_aria, nombre_tn_limpio):
                 return cliente, f"✅ ID {posible_id} confirmado por Nombre", debug_log
            else:
                 return cliente, f"⚠️ ID {posible_id} hallado, pero datos dudosos.", debug_log

    # =========================================================================
    # B. BÚSQUEDA MASIVA (La Red de Arrastre)
    # =========================================================================
    candidatos = []
    
    # B1. Buscar por DNI (Limpio)
    if len(dni_tn_numeros) > 5:
        # Probamos buscar el DNI limpio
        res_dni = consultar_api_aria(f"clientes?q={dni_tn_numeros}")
        candidatos.extend(res_dni)
        debug_log.append(f"Resultados API x DNI '{dni_tn_numeros}': {len(res_dni)}")
        
    # B2. Buscar por Apellido
    partes_nombre = nombre_tn.split()
    if len(partes_nombre) >= 1:
        apellido_tn = partes_nombre[-1].lower() 
        if len(apellido_tn) > 2:
            res_ape = consultar_api_aria(f"clientes?q={apellido_tn}")
            candidatos.extend(res_ape)
            debug_log.append(f"Resultados API x Apellido '{apellido_tn}': {len(res_ape)}")

    # ---------------------------------------------------------
    # C. COMPARACIÓN NUCLEAR (Uno por Uno)
    # ---------------------------------------------------------
    candidatos_unicos = {v['cliente_id']: v for v in candidatos if v.get('cliente_id')}.values()
    
    for c in candidatos_unicos:
        # DATOS ARIA LIMPIOS
        raw_dni_aria = c.get('cliente_dnicuit','')
        dni_aria_numeros = solo_numeros(raw_dni_aria)
        nombre_aria_full = f"{c.get('cliente_nombre','')} {c.get('cliente_apellido','')}"
        
        id_c = c.get('cliente_id')
        
        # LOG DETALLADO DE CADA CANDIDATO (Para que veas qué pasa)
        log_match = f"❌ ID {id_c}: Aria('{dni_aria_numeros}') vs TN('{dni_tn_numeros}')"
        
        match_encontrado = False

        # C1. Match de DNI/CUIT Nuclear
        # Verificamos si uno está contenido en el otro (para cubrir CUITs)
        if dni_tn_numeros and dni_aria_numeros:
            if dni_tn_numeros == dni_aria_numeros:
                match_encontrado = True
                log_match = f"✅ MATCH EXACTO ID {id_c}"
            elif len(dni_tn_numeros) > 5 and (dni_tn_numeros in dni_aria_numeros):
                match_encontrado = True
                log_match = f"✅ MATCH CUIT ID {id_c}"
        
        if match_encontrado:
            debug_log.append(log_match)
            return c, "✅ Encontrado por DNI/CUIT", debug_log
        
        debug_log.append(log_match)

    # C2. Intento secundario: Nombre (Solo si no hubo match de DNI)
    for c in candidatos_unicos:
        nombre_aria_full = f"{c.get('cliente_nombre','')} {c.get('cliente_apellido','')}"
        if hay_coincidencia_palabras(nombre_aria_full, nombre_tn_limpio):
            return c, "⚠️ Coincidencia por Nombre (DNI no coincide, revisar)", debug_log

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

        with st.expander(f"🛒 #{id_p} | {nombre} | ${total:,.0f}", expanded=True):
            
            if not es_manual and not modo_pendientes:
                st.warning(f"⚠️ Pago: '{metodo}'. El robot suele ignorar esto por seguridad.")

            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Productos:** {prod_str}")
                st.write(f"**DNI (TN):** {p['customer'].get('identification')}")
                st.write(f"**Nota:** {nota}")
            
            with col2:
                mostrar_analisis = False
                
                if st.button(f"🔍 Analizar Cliente", key=f"btn_{id_p}"):
                    st.session_state['analisis_activo'][id_p] = True
                    mostrar_analisis = True
                elif st.session_state['analisis_activo'].get(id_p):
                    mostrar_analisis = True

                if mostrar_analisis:
                    cliente_aria, metodo_hallazgo, debug_data = buscar_cliente(nombre, p['customer'].get('identification'), nota)
                    
                    if not cliente_aria:
                        st.error("❌ Cliente no encontrado automáticamente.")
                        
                        # DEBUGGER VISUAL DETALLADO
                        with st.expander("🐞 DIAGNÓSTICO TÉCNICO (¿Qué ve el robot?)"):
                            st.write(f"**Cliente TN:** {nombre}")
                            st.write(f"**DNI TN:** {p['customer'].get('identification')}")
                            st.write("---")
                            st.write("**Análisis de Candidatos:**")
                            for log in debug_data:
                                # Coloreamos si hubo match o fallo
                                if "✅" in log:
                                    st.success(log)
                                elif "❌" in log:
                                    st.error(log)
                                else:
                                    st.text(log)
                            st.info("Nota: El robot compara 'solo números'. Si Aria tiene el campo DNI vacío, fallará aquí.")

                        st.markdown("---")
                        st.write("🕵️ **Opción Manual:**")
                        col_m1, col_m2 = st.columns([2,1])
                        with col_m1:
                            id_manual = st.text_input("Ingresar Nro Cliente ARIA:", key=f"input_man_{id_p}")
                        with col_m2:
                            if st.button("Buscar Manual", key=f"btn_man_{id_p}"):
                                res = consultar_api_aria(f"cliente/{id_manual}")
                                if res and isinstance(res, list) and len(res) > 0 and res[0].get('cliente_id'):
                                    cliente_manual = res[0]
                                    id_aria_m = cliente_manual.get('cliente_id')
                                    cupo_m = float(cliente_manual.get('clienteScoringFinanciable', 0))
                                    saldo_m = float(cliente_manual.get('cliente_saldo', 0))
                                    
                                    st.success(f"✅ Encontrado Manualmente: {id_aria_m}")
                                    st.info(f"💰 Cupo: **${cupo_m:,.0f}** | Saldo: ${saldo_m:,.0f}")
                                    
                                    if saldo_m > 0:
                                        st.error("⛔ RECHAZADO: Tiene deuda vigente.")
                                    elif total <= cupo_m:
                                        st.success("🚀 APROBADO: Tiene cupo suficiente.")
                                        if st.button(f"💸 COBRAR MANUALMENTE", key=f"cobrar_man_{id_p}"):
                                            ok, msg = cargar_deuda_aria(id_aria_m, total, id_p, prod_str)
                                            if ok:
                                                st.toast("✅ ¡Cobrado exitosamente!", icon="🎉")
                                                del st.session_state['analisis_activo'][id_p]
                                                if modo_pendientes:
                                                    eliminar_etiqueta(id_p, nota)
                                                st.rerun()
                                            else:
                                                st.error(f"Fallo Aria: {msg}")
                                else:
                                    st.error("❌ Ese ID no existe en Aria.")

                    if cliente_aria:
                        id_aria = cliente_aria.get('cliente_id')
                        cupo = float(cliente_aria.get('clienteScoringFinanciable', 0))
                        saldo = float(cliente_aria.get('cliente_saldo', 0))
                        
                        if "⚠️" in metodo_hallazgo:
                            st.warning(f"{metodo_hallazgo}")
                        else:
                            st.info(f"{metodo_hallazgo}")

                        st.success(f"🆔 Cliente: **{id_aria}**")
                        st.info(f"💰 Cupo: **${cupo:,.0f}** | Saldo: ${saldo:,.0f}")
                        
                        if saldo > 0:
                            st.error("⛔ RECHAZADO: Tiene deuda vigente.")
                        elif total <= cupo:
                            st.success("🚀 APROBADO: Tiene cupo suficiente.")
                            if st.button(f"💸 COBRAR AHORA", key=f"cobrar_{id_p}"):
                                ok, msg = cargar_deuda_aria(id_aria, total, id_p, prod_str)
                                if ok:
                                    st.toast("✅ ¡Cobrado exitosamente!", icon="🎉")
                                    del st.session_state['analisis_activo'][id_p]
                                    if modo_pendientes:
                                        eliminar_etiqueta(id_p, nota)
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
                            
                            if st.button("📌 Pasar a SEGUIMIENTO", key=f"seg_{id_p}"):
                                actualizar_nota(id_p, nota, TAG_ESPERA)
                                del st.session_state['analisis_activo'][id_p]
                                st.rerun()

                    st.markdown("---")
                    if st.button("Cerrar Panel", key=f"close_{id_p}"):
                        del st.session_state['analisis_activo'][id_p]
                        st.rerun()
