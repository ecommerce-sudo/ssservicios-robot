import streamlit as st
import requests

# ==========================================
# 🔬 DIAGNÓSTICO DEFINITIVO (V2)
# ==========================================
st.title("🔬 Radiografía de la API")

# 1. Carga de claves
try:
    ARIA_KEY = st.secrets["ARIA_KEY"]
except:
    st.error("⚠️ No se encontraron las claves (secrets).")
    st.stop()

# 2. Botón de prueba
if st.button("📡 CONSULTAR Y MOSTRAR TODO"):
    # Usamos el DNI de la foto que sabemos que existe
    url = "https://api.anatod.ar/api/clientes?q=28979733"
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    
    st.info(f"Consultando: {url}")
    
    try:
        res = requests.get(url, headers=headers)
        
        if res.status_code == 200:
            datos = res.json()
            
            st.success("✅ ¡Conexión Exitosa!")
            st.markdown("### 👇 ESTA ES LA ESTRUCTURA REAL:")
            
            # Esto mostrará el objeto completo sin importar si es lista o diccionario
            st.json(datos) 
            
        else:
            st.error(f"Error {res.status_code}: {res.text}")
            
    except Exception as e:
        st.error(f"🔥 Error grave: {e}")
