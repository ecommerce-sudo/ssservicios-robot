import streamlit as st
import requests

# 1. Configuración (Usa tus secrets)
try:
    ARIA_KEY = st.secrets["ARIA_KEY"]
except:
    st.error("No se detectaron los secrets.")
    st.stop()

st.title("🕵️ Script Espía de Estructura")

# 2. Botón para lanzar la prueba
if st.button("🔎 BUSCAR DNI 28979733 Y VER ESTRUCTURA"):
    url = "https://api.anatod.ar/api/clientes?q=28979733"
    headers = {"x-api-key": ARIA_KEY, "Content-Type": "application/json"}
    
    st.write(f"Consultando: {url} ...")
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            datos = res.json()
            st.success("✅ ¡Datos recibidos!")
            
            if len(datos) > 0:
                cliente = datos[0]
                
                # AQUÍ ESTÁ LA CLAVE: Mostramos las llaves del diccionario
                st.subheader("🔑 ¿Cómo se llaman los campos?")
                st.code(list(cliente.keys()))
                
                st.subheader("📄 Datos completos:")
                st.json(cliente)
            else:
                st.warning("La API respondió [], no encontró al cliente.")
        else:
            st.error(f"Error {res.status_code}: {res.text}")
    except Exception as e:
        st.error(f"Fallo de conexión: {e}")
