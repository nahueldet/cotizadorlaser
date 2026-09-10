import streamlit as st
import pandas as pd
import ezdxf
import fitz  # PyMuPDF
import math
import io
import json
import os

st.set_page_config(page_title="Cotizador CNC Automático", layout="wide")

# --- LÓGICA DE GUARDADO DE PARÁMETROS ---
ARCHIVO_CONFIG = "parametros.json"

# Valores por defecto en caso de que sea la primera vez que se abre la app
config_por_defecto = {
    "costo_hora_maquina": 5000.0,
    "costo_nitrogeno": 250.0,
    "costo_oxigeno": 180.0
}

def cargar_parametros():
    if os.path.exists(ARCHIVO_CONFIG):
        with open(ARCHIVO_CONFIG, "r") as archivo:
            return json.load(archivo)
    return config_por_defecto

def guardar_parametros(nuevos_parametros):
    with open(ARCHIVO_CONFIG, "w") as archivo:
        json.dump(nuevos_parametros, archivo)

# Cargamos los parámetros actuales al iniciar
parametros_actuales = cargar_parametros()

# --- FUNCIONES DE EXTRACCIÓN DE LONGITUD ---
def calcular_longitud_dxf(file_bytes):
    try:
        stringio = io.StringIO(file_bytes.decode("utf-8"))
        doc = ezdxf.read(stringio)
        msp = doc.modelspace()
        longitud_total = 0.0
        
        for entity in msp:
            if entity.dxftype() == 'LINE':
                start, end = entity.dxf.start, entity.dxf.end
                longitud_total += math.dist((start.x, start.y), (end.x, end.y))
            elif entity.dxftype() == 'CIRCLE':
                longitud_total += 2 * math.pi * entity.dxf.radius
            elif entity.dxftype() == 'ARC':
                angle = math.radians(entity.dxf.end_angle - entity.dxf.start_angle)
                if angle < 0: angle += 2 * math.pi
                longitud_total += entity.dxf.radius * angle
            elif entity.dxftype() == 'LWPOLYLINE':
                points = list(entity.get_points('xy'))
                for i in range(len(points)-1):
                    longitud_total += math.dist(points[i], points[i+1])
                if entity.closed:
                    longitud_total += math.dist(points[-1], points[0])
                    
        return longitud_total 
    except Exception as e:
        st.error(f"Error al leer el DXF: {e}")
        return None

def calcular_longitud_pdf(file_bytes, factor_escala):
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        longitud_total_puntos = 0.0
        
        for page in doc:
            paths = page.get_drawings()
            for path in paths:
                for item in path["items"]:
                    if item[0] == "l": 
                        p1, p2 = item[1], item[2]
                        longitud_total_puntos += math.dist((p1.x, p1.y), (p2.x, p2.y))
                    elif item[0] == "c": 
                        p1, p4 = item[1], item[4]
                        longitud_total_puntos += math.dist((p1.x, p1.y), (p4.x, p4.y))
                        
        longitud_mm = longitud_total_puntos * 0.352778 * factor_escala
        return longitud_mm
    except Exception as e:
        st.error(f"Error al leer el PDF: {e}")
        return None

# --- BARRA LATERAL: CONFIGURACIÓN DE PRECIOS ---
st.sidebar.header("💾 Parámetros del Taller")
st.sidebar.write("Modifica los valores y presiona el botón para fijarlos.")

nuevo_costo_hora = st.sidebar.number_input("Costo Hora Máquina ($)", value=float(parametros_actuales["costo_hora_maquina"]), step=100.0)
nuevo_costo_nitrogeno = st.sidebar.number_input("Costo Nitrógeno (por m³) ($)", value=float(parametros_actuales["costo_nitrogeno"]), step=10.0)
nuevo_costo_oxigeno = st.sidebar.number_input("Costo Oxígeno (por m³) ($)", value=float(parametros_actuales["costo_oxigeno"]), step=10.0)

if st.sidebar.button("Actualizar y Guardar Precios", type="primary"):
    nuevos_datos = {
        "costo_hora_maquina": nuevo_costo_hora,
        "costo_nitrogeno": nuevo_costo_nitrogeno,
        "costo_oxigeno": nuevo_costo_oxigeno
    }
    guardar_parametros(nuevos_datos)
    st.sidebar.success("✅ Precios actualizados exitosamente.")
    # Forzamos una actualización visual para que se apliquen los cambios
    st.rerun()

st.sidebar.write("---")

# --- INTERFAZ PRINCIPAL ---
st.title("⚙️ Calculadora de Costos CNC Automática")

st.header("1. Carga de Plano y Datos del Trabajo")
archivo_corte = st.file_uploader("Cargar Plano (.DXF o .PDF)", type=["pdf", "dxf"])

factor_escala_pdf = 1.0
if archivo_corte is not None and archivo_corte.name.lower().endswith(".pdf"):
    st.info("⚠️ Has cargado un PDF. Los PDF no tienen escala real nativa (1:1) como los DXF.")
    factor_escala_pdf = st.number_input("Ingresa el Factor de Escala del PDF (ej: si el plano está 1:10, ingresa 10)", min_value=0.1, value=1.0)

col1, col2 = st.columns(2)
with col1:
    material = st.selectbox("Material de la Chapa", ["Acero al Carbono", "Acero Inoxidable", "Aluminio"])
with col2:
    espesor = st.number_input("Espesor de la chapa (mm)", min_value=0.1, value=1.0, step=0.1)

st.write("---")

if st.button("Calcular Costo de Trabajo", type="primary", use_container_width=True):
    if archivo_corte is not None:
        file_bytes = archivo_corte.getvalue()
        
        if archivo_corte.name.lower().endswith(".dxf"):
            longitud_corte_mm = calcular_longitud_dxf(file_bytes)
        else:
            longitud_corte_mm = calcular_longitud_pdf(file_bytes, factor_escala_pdf)
            
        if longitud_corte_mm is not None and longitud_corte_mm > 0:
            st.success(f"Archivo procesado correctamente.")
            st.metric("Longitud total de corte detectada", f"{longitud_corte_mm:.2f} mm")

            # --- LÓGICA DE CÁLCULO ---
            if material == "Acero al Carbono":
                gas_utilizado = "Oxígeno"
                # Usamos los precios recién cargados de la configuración
                costo_gas_unitario = nuevo_costo_oxigeno
                velocidad_corte_mm_min = 4000 / espesor 
                consumo_gas_m3_min = 0.5 * espesor 
            else:
                gas_utilizado = "Nitrógeno"
                costo_gas_unitario = nuevo_costo_nitrogeno
                velocidad_corte_mm_min = 3500 / (espesor * 1.2)
                consumo_gas_m3_min = 0.8 * espesor

            velocidad_corte_mm_min = max(velocidad_corte_mm_min, 1) 
            tiempo_minutos = longitud_corte_mm / velocidad_corte_mm_min
            consumo_total_gas = tiempo_minutos * consumo_gas_m3_min

            costo_tiempo = (tiempo_minutos / 60) * nuevo_costo_hora
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
                st.write(f"- Costo por tiempo de máquina (${nuevo_costo_hora}/h): **${costo_tiempo:.2f}**")
                st.write(f"- Costo por consumo de {gas_utilizado} (${costo_gas_unitario}/m³): **${costo_gas_total:.2f}**")
        else:
            st.error("No se detectó un recorrido de corte válido.")
    else:
        st.warning("Por favor, sube un archivo .DXF o .PDF.")
