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

# Valores por defecto ampliados con los costos de chapa
config_por_defecto = {
    "costo_hora_maquina": 5000.0,
    "costo_nitrogeno": 250.0,
    "costo_oxigeno": 180.0,
    "costo_kg_carbono": 1500.0,
    "costo_kg_inox": 6500.0,
    "costo_kg_aluminio": 7000.0
}

def cargar_parametros():
    if os.path.exists(ARCHIVO_CONFIG):
        with open(ARCHIVO_CONFIG, "r") as archivo:
            datos = json.load(archivo)
            # Validamos que existan las nuevas llaves en caso de tener un archivo viejo guardado
            for key, value in config_por_defecto.items():
                if key not in datos:
                    datos[key] = value
            return datos
    return config_por_defecto

def guardar_parametros(nuevos_parametros):
    with open(ARCHIVO_CONFIG, "w") as archivo:
        json.dump(nuevos_parametros, archivo)

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
st.sidebar.header("💾 Parámetros Operativos")
nuevo_costo_hora = st.sidebar.number_input("Costo Hora Máquina ($)", value=float(parametros_actuales["costo_hora_maquina"]), step=100.0)
nuevo_costo_nitrogeno = st.sidebar.number_input("Costo Nitrógeno (por m³) ($)", value=float(parametros_actuales["costo_nitrogeno"]), step=10.0)
nuevo_costo_oxigeno = st.sidebar.number_input("Costo Oxígeno (por m³) ($)", value=float(parametros_actuales["costo_oxigeno"]), step=10.0)

st.sidebar.header("📦 Costos de Materiales (por Kg)")
nuevo_costo_carbono = st.sidebar.number_input("Acero al Carbono ($/kg)", value=float(parametros_actuales["costo_kg_carbono"]), step=50.0)
nuevo_costo_inox = st.sidebar.number_input("Acero Inoxidable ($/kg)", value=float(parametros_actuales["costo_kg_inox"]), step=50.0)
nuevo_costo_aluminio = st.sidebar.number_input("Aluminio ($/kg)", value=float(parametros_actuales["costo_kg_aluminio"]), step=50.0)

if st.sidebar.button("Actualizar y Guardar Precios", type="primary"):
    nuevos_datos = {
        "costo_hora_maquina": nuevo_costo_hora,
        "costo_nitrogeno": nuevo_costo_nitrogeno,
        "costo_oxigeno": nuevo_costo_oxigeno,
        "costo_kg_carbono": nuevo_costo_carbono,
        "costo_kg_inox": nuevo_costo_inox,
        "costo_kg_aluminio": nuevo_costo_aluminio
    }
    guardar_parametros(nuevos_datos)
    st.sidebar.success("✅ Precios actualizados exitosamente.")
    st.rerun()

# --- INTERFAZ PRINCIPAL ---
st.title("⚙️ Calculadora de Costos CNC Automática")

st.header("1. Carga de Plano y Datos del Trabajo")
archivo_corte = st.file_uploader("Cargar Plano (.DXF o .PDF)", type=["pdf", "dxf"])

factor_escala_pdf = 1.0
if archivo_corte is not None and archivo_corte.name.lower().endswith(".pdf"):
    st.info("⚠️ Has cargado un PDF. Asegúrate de ingresar la escala correcta.")
    factor_escala_pdf = st.number_input("Factor de Escala del PDF (ej: 10 para 1:10)", min_value=0.1, value=1.0)

st.subheader("Especificaciones del Material")
col1, col2 = st.columns(2)
with col1:
    material = st.selectbox("Material de la Chapa", ["Acero al Carbono", "Acero Inoxidable", "Aluminio"])
with col2:
    espesor = st.number_input("Espesor de la chapa (mm)", min_value=0.1, value=1.0, step=0.1)

col3, col4 = st.columns(2)
with col3:
    ancho_pieza = st.number_input("Ancho del recuadro de la pieza (mm)", min_value=1.0, value=100.0)
with col4:
    largo_pieza = st.number_input("Largo del recuadro de la pieza (mm)", min_value=1.0, value=100.0)

st.write("---")

if st.button("Calcular Costo de Trabajo", type="primary", use_container_width=True):
    if archivo_corte is not None:
        file_bytes = archivo_corte.getvalue()
        
        if archivo_corte.name.lower().endswith(".dxf"):
            longitud_corte_mm = calcular_longitud_dxf(file_bytes)
        else:
            longitud_corte_mm = calcular_longitud_pdf(file_bytes, factor_escala_pdf)
            
        if longitud_corte_mm is not None and longitud_corte_mm > 0:
            st.success("Archivo procesado correctamente.")
            
            # --- DENSIDADES Y PRECIOS ---
            densidades_g_cm3 = {
                "Acero al Carbono": 7.85,
                "Acero Inoxidable": 7.93,
                "Aluminio": 2.70
            }
            costos_kg = {
                "Acero al Carbono": nuevo_costo_carbono,
                "Acero Inoxidable": nuevo_costo_inox,
                "Aluminio": nuevo_costo_aluminio
            }

            # --- CÁLCULO DE PESO Y COSTO DE MATERIAL ---
            # Volumen en mm3 = ancho * largo * espesor
            # mm3 a cm3 = / 1000.  cm3 a kg = * densidad / 1000
            peso_kg = (ancho_pieza * largo_pieza * espesor * densidades_g_cm3[material]) / 1000000
            costo_material_total = peso_kg * costos_kg[material]

            # --- LÓGICA DE CÁLCULO MÁQUINA Y GAS ---
            if material == "Acero al Carbono":
                gas_utilizado = "Oxígeno"
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
            
            # TOTAL FINAL
            costo_total = costo_tiempo + costo_gas_total + costo_material_total

            # --- MOSTRAR RESULTADOS ---
            st.header("2. Resultados de la Cotización")
            
            res1, res2, res3, res4 = st.columns(4)
            res1.metric("Longitud Total", f"{longitud_corte_mm:.0f} mm")
            res2.metric("Tiempo de Proceso", f"{tiempo_minutos:.2f} min")
            res3.metric("Peso del Material", f"{peso_kg:.2f} kg")
            res4.metric("Consumo de Gas", f"{consumo_total_gas:.2f} m³")

            st.subheader(f"Costo Estimado Total: ${costo_total:.2f}")
            
            with st.expander("Ver desglose detallado de costos", expanded=True):
                st.write(f"🏭 **Operación CNC:**")
                st.write(f"- Costo por tiempo de máquina (${nuevo_costo_hora}/h): **${costo_tiempo:.2f}**")
                st.write(f"- Costo por consumo de {gas_utilizado} (${costo_gas_unitario}/m³): **${costo_gas_total:.2f}**")
                st.write(f"📦 **Materia Prima:**")
                st.write(f"- Costo de Chapa {material} ({peso_kg:.2f} kg a ${costos_kg[material]}/kg): **${costo_material_total:.2f}**")
        else:
            st.error("No se detectó un recorrido de corte válido.")
    else:
        st.warning("Por favor, sube un archivo .DXF o .PDF.")
