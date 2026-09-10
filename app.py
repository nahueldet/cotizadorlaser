import streamlit as st
import pandas as pd
# import fitz  # PyMuPDF, librería que usarías para intentar leer vectores del PDF

st.set_page_config(page_title="Cotizador CNC", layout="wide")

st.title("⚙️ Calculadora de Costos de Corte CNC")

# --- BARRA LATERAL: PARÁMETROS DEL TALLER ---
st.sidebar.header("Parámetros de Costos")
costo_hora_maquina = st.sidebar.number_input("Costo Hora Máquina ($)", value=5000.0)
costo_nitrogeno = st.sidebar.number_input("Costo Nitrógeno (por m³) ($)", value=250.0)
costo_oxigeno = st.sidebar.number_input("Costo Oxígeno (por m³) ($)", value=180.0)

# --- INTERFAZ PRINCIPAL ---
st.header("1. Carga de Plano y Datos del Trabajo")
archivo_pdf = st.file_uploader("Cargar Plano (PDF)", type=["pdf"])

col1, col2, col3 = st.columns(3)
with col1:
    material = st.selectbox("Material de la Chapa", ["Acero al Carbono", "Acero Inoxidable", "Aluminio"])
with col2:
    espesor = st.number_input("Espesor de la chapa (mm)", min_value=0.1, value=1.0, step=0.1)
with col3:
    # Este campo está como respaldo por la complejidad de parsear líneas de un PDF
    longitud_manual = st.number_input("Longitud total de corte (mm) - Manual", min_value=1.0, value=1000.0)

st.write("---")

if st.button("Calcular Costo de Trabajo", type="primary"):
    if archivo_pdf is not None or longitud_manual > 0:
        
        # Aquí iría la lógica de lectura del PDF usando PyMuPDF (fitz) o pdfminer.
        # Por ahora usamos el valor manual para que la calculadora funcione.
        longitud_corte_mm = longitud_manual 
        
        st.success(f"Archivo {archivo_pdf.name if archivo_pdf else 'Manual'} procesado.")

        # --- LÓGICA DE ASIGNACIÓN DE GAS Y VELOCIDADES ---
        # (Estas fórmulas de velocidad/consumo son simplificadas; deberás ajustarlas a tu maquinaria)
        if material == "Acero al Carbono":
            gas_utilizado = "Oxígeno"
            costo_gas_unitario = costo_oxigeno
            # A mayor espesor, menor velocidad y mayor consumo
            velocidad_corte_mm_min = 4000 / espesor 
            consumo_gas_m3_min = 0.5 * espesor 
        else:
            gas_utilizado = "Nitrógeno"
            costo_gas_unitario = costo_nitrogeno
            velocidad_corte_mm_min = 3500 / (espesor * 1.2)
            consumo_gas_m3_min = 0.8 * espesor

        # Evitar división por cero
        velocidad_corte_mm_min = max(velocidad_corte_mm_min, 1) 

        # --- CÁLCULOS ---
        tiempo_minutos = longitud_corte_mm / velocidad_corte_mm_min
        consumo_total_gas = tiempo_minutos * consumo_gas_m3_min

        costo_tiempo = (tiempo_minutos / 60) * costo_hora_maquina
        costo_gas_total = consumo_total_gas * costo_gas_unitario
        costo_total = costo_tiempo + costo_gas_total

        # --- MOSTRAR RESULTADOS ---
        st.header("2. Resultados de la Cotización")
        
        res1, res2, res3 = st.columns(3)
        res1.metric("Gas Requerido", gas_utilizado)
        res2.metric("Tiempo de Procesamiento", f"{tiempo_minutos:.2f} min")
        res3.metric("Consumo de Gas", f"{consumo_total_gas:.2f} m³")

        st.subheader(f"Costo Estimado Total: ${costo_total:.2f}")
        
        with st.expander("Ver desglose de costos"):
            st.write(f"- Costo por tiempo de máquina: ${costo_tiempo:.2f}")
            st.write(f"- Costo por consumo de gas: ${costo_gas_total:.2f}")
            
        st.info("💡 **Nota técnica sobre planos:** Extraer vectores precisos directamente de un PDF depende mucho de cómo se exportó el dibujo (a veces se exporta como imagen y no como líneas vectoriales). Si en el futuro notas errores en la longitud calculada, considera implementar subida de archivos `.dxf` utilizando la librería `ezdxf`, que lee el perímetro de forma exacta.")
    else:
        st.warning("Por favor, sube un archivo o ingresa la longitud de corte manualmente.")
