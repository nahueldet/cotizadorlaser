import streamlit as st
import pandas as pd
import ezdxf
import fitz  # PyMuPDF
import math
import io
import json
import os

st.set_page_config(page_title="Cotizador CNC Automático", layout="wide")

# --- 1. LÓGICA DE GUARDADO DE PARÁMETROS OPERATIVOS ---
ARCHIVO_CONFIG = "parametros.json"
ARCHIVO_BD = "precios_chapas.csv"

config_por_defecto = {
    "costo_hora_maquina": 5000.0,
    "costo_nitrogeno": 250.0,
    "costo_oxigeno": 180.0
}

# Diccionario de densidades (kg/m2 por cada 1mm de espesor)
DENSIDADES = {
    "Acero al Carbono": 7.85,
    "Acero Inoxidable": 7.93,
    "Aluminio": 2.70
}

def cargar_parametros():
    if os.path.exists(ARCHIVO_CONFIG):
        with open(ARCHIVO_CONFIG, "r") as archivo:
            datos = json.load(archivo)
            for key, value in config_por_defecto.items():
                if key not in datos:
                    datos[key] = value
            return datos
    return config_por_defecto

def guardar_parametros(nuevos_parametros):
    with open(ARCHIVO_CONFIG, "w") as archivo:
        json.dump(nuevos_parametros, archivo)

parametros_actuales = cargar_parametros()

# --- 2. LÓGICA DE BASE DE DATOS DE CHAPAS ---
def cargar_bd_chapas():
    if os.path.exists(ARCHIVO_BD):
        df = pd.read_csv(ARCHIVO_BD)
        if "Precio por Kg ($)" not in df.columns:
            df["Precio por Kg ($)"] = df.apply(
                lambda row: row["Precio por m2 ($)"] / (row["Espesor (mm)"] * DENSIDADES.get(row["Material"], 7.85)), 
                axis=1
            ).round(2)
        return df
    else:
        data = {
            "Material": ["Acero al Carbono", "Acero al Carbono", "Acero Inoxidable", "Aluminio"],
            "Espesor (mm)": [1.0, 2.0, 1.0, 1.0],
            "Precio por Kg ($)": [1500.0, 1500.0, 6500.0, 7000.0] 
        }
        df = pd.DataFrame(data)
        
        def calcular_precio_m2(row):
            peso_m2 = row["Espesor (mm)"] * DENSIDADES[row["Material"]]
            return row["Precio por Kg ($)"] * peso_m2
            
        df["Precio por m2 ($)"] = df.apply(calcular_precio_m2, axis=1).round(2)
        df.to_csv(ARCHIVO_BD, index=False)
        return df

def guardar_bd_chapas(df):
    def calcular_precio_m2(row):
        peso_m2 = row["Espesor (mm)"] * DENSIDADES[row["Material"]]
        return row["Precio por Kg ($)"] * peso_m2
        
    df["Precio por m2 ($)"] = df.apply(calcular_precio_m2, axis=1).round(2)
    df.to_csv(ARCHIVO_BD, index=False)
    return df

df_chapas = cargar_bd_chapas()

# --- 3. FUNCIONES DE EXTRACCIÓN AUTOMÁTICA ---
def procesar_dxf(file_bytes):
    try:
        try:
            texto_dxf = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            texto_dxf = file_bytes.decode("latin-1")
            
        stringio = io.StringIO(texto_dxf)
        doc = ezdxf.read(stringio)
        msp = doc.modelspace()
        
        longitud_total = 0.0
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        
        elementos_encontrados = False
        conteo_tipos = {} 

        def extraer_entidades_de_espacio(espacio):
            nonlocal longitud_total, min_x, min_y, max_x, max_y, elementos_encontrados, conteo_tipos
            
            for entity in espacio:
                tipo = entity.dxftype()
                conteo_tipos[tipo] = conteo_tipos.get(tipo, 0) + 1
                
                if tipo == 'LINE':
                    start, end = entity.dxf.start, entity.dxf.end
                    longitud_total += math.dist((start.x, start.y), (end.x, end.y))
                    min_x = min(min_x, start.x, end.x); max_x = max(max_x, start.x, end.x)
                    min_y = min(min_y, start.y, end.y); max_y = max(max_y, start.y, end.y)
                    elementos_encontrados = True

                elif tipo == 'CIRCLE':
                    longitud_total += 2 * math.pi * entity.dxf.radius
                    cx, cy, r = entity.dxf.center.x, entity.dxf.center.y, entity.dxf.radius
                    min_x = min(min_x, cx - r); max_x = max(max_x, cx + r)
                    min_y = min(min_y, cy - r); max_y = max(max_y, cy + r)
                    elementos_encontrados = True

                elif tipo == 'ARC':
                    angle = math.radians(entity.dxf.end_angle - entity.dxf.start_angle)
                    if angle < 0: angle += 2 * math.pi
                    longitud_total += entity.dxf.radius * angle
                    cx, cy, r = entity.dxf.center.x, entity.dxf.center.y, entity.dxf.radius
                    min_x = min(min_x, cx - r); max_x = max(max_x, cx + r)
                    min_y = min(min_y, cy - r); max_y = max(max_y, cy + r)
                    elementos_encontrados = True

                elif tipo == 'LWPOLYLINE':
                    points = list(entity.get_points('xy'))
                    if len(points) > 1:
                        for i in range(len(points)-1):
                            longitud_total += math.dist(points[i], points[i+1])
                            min_x = min(min_x, points[i][0]); max_x = max(max_x, points[i][0])
                            min_y = min(min_y, points[i][1]); max_y = max(max_y, points[i][1])
                        
                        min_x = min(min_x, points[-1][0]); max_x = max(max_x, points[-1][0])
                        min_y = min(min_y, points[-1][1]); max_y = max(max_y, points[-1][1])

                        if entity.closed:
                            longitud_total += math.dist(points[-1], points[0])
                        elementos_encontrados = True

                elif tipo == 'POLYLINE':
                    points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                    if len(points) > 1:
                        for i in range(len(points)-1):
                            longitud_total += math.dist(points[i], points[i+1])
                            min_x = min(min_x, points[i][0]); max_x = max(max_x, points[i][0])
                            min_y = min(min_y, points[i][1]); max_y = max(max_y, points[i][1])
                        
                        min_x = min(min_x, points[-1][0]); max_x = max(max_x, points[-1][0])
                        min_y = min(min_y, points[-1][1]); max_y = max(max_y, points[-1][1])

                        if entity.is_closed:
                            longitud_total += math.dist(points[-1], points[0])
                        elementos_encontrados = True

                elif tipo in ['SPLINE', 'ELLIPSE']:
                    try:
                        points = list(entity.flattening(distance=0.1))
                        if len(points) > 1:
                            for i in range(len(points)-1):
                                p1, p2 = points[i], points[i+1]
                                longitud_total += math.dist((p1[0], p1[1]), (p2[0], p2[1]))
                                min_x = min(min_x, p1[0], p2[0]); max_x = max(max_x, p1[0], p2[0])
                                min_y = min(min_y, p1[1], p2[1]); max_y = max(max_y, p1[1], p2[1])
                            elementos_encontrados = True
                    except Exception:
                        pass

                elif tipo == 'INSERT':
                    try:
                        block_name = entity.dxf.name
                        if block_name in doc.blocks:
                            extraer_entidades_de_espacio(doc.blocks[block_name])
                    except Exception:
                        pass

        extraer_entidades_de_espacio(msp)

        if not elementos_encontrados:
            for block in doc.blocks:
                if not block.name.startswith("*"):
                    extraer_entidades_de_espacio(block)

        if not elementos_encontrados:
            st.error("❌ El archivo no contiene geometría de corte válida.")
            if conteo_tipos:
                st.warning(f"🔍 El script escaneó el archivo y detectó estos elementos (pero ninguno es apto para corte): {conteo_tipos}")
            else:
                st.warning("🔍 El script escaneó el archivo y está completamente vacío o usa una estructura irreconocible.")
            return None, None, None

        ancho = max_x - min_x
        largo = max_y - min_y
        
        return longitud_total, ancho, largo
        
    except Exception as e:
        st.error(f"🛑 Error técnico interno al procesar el DXF: {e}")
        return None, None, None

def procesar_pdf(file_bytes, factor_escala):
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        longitud_total_puntos = 0.0
        bbox_global = fitz.Rect() 
        elementos_encontrados = False

        for page in doc:
            paths = page.get_drawings()
            for path in paths:
                if not elementos_encontrados:
                    bbox_global = path["rect"]
                    elementos_encontrados = True
                else:
                    bbox_global = bbox_global | path["rect"]
                
                for item in path["items"]:
                    if item[0] == "l": 
                        p1, p2 = item[1], item[2]
                        longitud_total_puntos += math.dist((p1.x, p1.y), (p2.x, p2.y))
                    elif item[0] == "c": 
                        p1, p4 = item[1], item[4]
                        longitud_total_puntos += math.dist((p1.x, p1.y), (p4.x, p4.y))
        
        if not elementos_encontrados:
            return None, None, None
            
        conversion = 0.352778 * factor_escala
        longitud_mm = longitud_total_puntos * conversion
        ancho_mm = bbox_global.width * conversion
        largo_mm = bbox_global.height * conversion
        
        return longitud_mm, ancho_mm, largo_mm
    except Exception as e:
        st.error(f"Error al leer el PDF: {e}")
        return None, None, None

# --- BARRA LATERAL: PARÁMETROS OPERATIVOS ---
st.sidebar.header("⚙️ Parámetros de Máquina y Gas")
nuevo_costo_hora = st.sidebar.number_input("Costo Hora Máquina ($)", value=float(parametros_actuales["costo_hora_maquina"]), step=100.0)
nuevo_costo_nitrogeno = st.sidebar.number_input("Costo Nitrógeno (por m³) ($)", value=float(parametros_actuales["costo_nitrogeno"]), step=10.0)
nuevo_costo_oxigeno = st.sidebar.number_input("Costo Oxígeno (por m³) ($)", value=float(parametros_actuales["costo_oxigeno"]), step=10.0)

if st.sidebar.button("Guardar Parámetros de Máquina", type="primary"):
    nuevos_datos = {
        "costo_hora_maquina": nuevo_costo_hora,
        "costo_nitrogeno": nuevo_costo_nitrogeno,
        "costo_oxigeno": nuevo_costo_oxigeno
    }
    guardar_parametros(nuevos_datos)
    st.sidebar.success("✅ Parámetros guardados.")
    st.rerun()

st.title("⚙️ Sistema Integral de Cotización CNC")

# --- NAVEGACIÓN POR PESTAÑAS ---
tab1, tab2, tab3, tab4 = st.tabs(["💰 Cotizador Automático", "⏱️ Cotizador Manual", "🗄️ Base de Datos", "⚖️ Calculadora de Pesos"])

# ==========================================
# PESTAÑA 1: CALCULADORA DE COSTOS AUTOMÁTICA
# ==========================================
with tab1:
    st.header("1. Carga de Plano")
    archivo_corte = st.file_uploader("Cargar Plano (.DXF o .PDF)", type=["pdf", "dxf"])
    
    factor_escala_pdf = 1.0
    if archivo_corte is not None and archivo_corte.name.lower().endswith(".pdf"):
        st.info("⚠️ Has cargado un PDF. Asegúrate de ingresar la escala correcta.")
        factor_escala_pdf = st.number_input("Factor de Escala del PDF (ej: 10 para 1:10)", min_value=0.1, value=1.0)

    st.header("2. Especificaciones del Material")
    col1, col2 = st.columns(2)
    with col1:
        materiales_disponibles = df_chapas["Material"].unique()
        material_seleccionado = st.selectbox("Material de la Chapa", materiales_disponibles, key="mat_cotizador_auto")
    with col2:
        espesores_disponibles = df_chapas[df_chapas["Material"] == material_seleccionado]["Espesor (mm)"].unique()
        if len(espesores_disponibles) > 0:
            espesor_seleccionado = st.selectbox("Espesor (mm)", sorted(espesores_disponibles), key="esp_cotizador_auto")
        else:
            st.warning("No hay espesores cargados para este material.")
            espesor_seleccionado = 0

    st.write("---")

    if st.button("Calcular Costo Automático", type="primary", use_container_width=True):
        if archivo_corte is not None and espesor_seleccionado > 0:
            file_bytes = archivo_corte.getvalue()
            
            if archivo_corte.name.lower().endswith(".dxf"):
                longitud_corte_mm, ancho_pieza, largo_pieza = procesar_dxf(file_bytes)
            else:
                longitud_corte_mm, ancho_pieza, largo_pieza = procesar_pdf(file_bytes, factor_escala_pdf)
                
            if longitud_corte_mm is not None and longitud_corte_mm > 0:
                st.success("Archivo procesado correctamente. Medidas extraídas automáticamente.")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Longitud de Corte", f"{longitud_corte_mm:.0f} mm")
                c2.metric("Ancho Detectado", f"{ancho_pieza:.1f} mm")
                c3.metric("Largo Detectado", f"{largo_pieza:.1f} mm")

                fila_material = df_chapas[(df_chapas["Material"] == material_seleccionado) & (df_chapas["Espesor (mm)"] == espesor_seleccionado)]
                precio_m2_chapa = fila_material["Precio por m2 ($)"].values[0]

                area_m2 = (ancho_pieza * largo_pieza) / 1000000
                costo_material_total = area_m2 * precio_m2_chapa

                if "Acero al Carbono" in material_seleccionado:
                    gas_utilizado = "Oxígeno"
                    costo_gas_unitario = nuevo_costo_oxigeno
                    velocidad_corte_mm_min = 6000 / (espesor_seleccionado ** 0.8) 
                    consumo_gas_m3_min = 0.02 + (0.005 * espesor_seleccionado)
                else:
                    gas_utilizado = "Nitrógeno"
                    costo_gas_unitario = nuevo_costo_nitrogeno
                    velocidad_corte_mm_min = 5000 / espesor_seleccionado
                    consumo_gas_m3_min = 0.25 + (0.05 * espesor_seleccionado)

                velocidad_corte_mm_min = max(velocidad_corte_mm_min, 50) 
                tiempo_minutos = longitud_corte_mm / velocidad_corte_mm_min
                consumo_total_gas = tiempo_minutos * consumo_gas_m3_min

                costo_tiempo = (tiempo_minutos / 60) * nuevo_costo_hora
                costo_gas_total = consumo_total_gas * costo_gas_unitario
                
                costo_total = costo_tiempo + costo_gas_total + costo_material_total

                st.header("3. Resultados de la Cotización")
                st.subheader(f"Costo Estimado Total: ${costo_total:.2f}")
                
                with st.expander("Ver desglose detallado de costos", expanded=True):
                    st.write(f"🏭 **Operación CNC:**")
                    st.write(f"- Tiempo estimado de proceso: {tiempo_minutos:.2f} min")
                    st.write(f"- Costo máquina (${nuevo_costo_hora}/h): **${costo_tiempo:.2f}**")
                    st.write(f"- Costo {gas_utilizado} ({consumo_total_gas:.2f} m³ a ${costo_gas_unitario}/m³): **${costo_gas_total:.2f}**")
                    st.write(f"📦 **Materia Prima:**")
                    st.write(f"- Área total consumida: {area_m2:.4f} m²")
                    st.write(f"- Costo {material_seleccionado} {espesor_seleccionado}mm (a ${precio_m2_chapa}/m²): **${costo_material_total:.2f}**")
            else:
                pass 
        else:
            st.warning("Por favor, sube un archivo e indica el espesor válido.")

# ==========================================
# PESTAÑA 2: COTIZADOR MANUAL
# ==========================================
with tab2:
    st.header("⏱️ Cotizador Manual (Datos del CAM)")
    st.write("Utiliza esta calculadora si ya procesaste el plano en el software de la máquina láser y tienes los datos exactos del trabajo.")
    
    col_man1, col_man2 = st.columns(2)
    with col_man1:
        tiempo_manual_min = st.number_input("Tiempo estimado de corte (minutos)", min_value=0.1, value=5.0, step=0.5)
        gas_manual_tipo = st.selectbox("Gas utilizado", ["Oxígeno", "Nitrógeno"])
        consumo_gas_manual_m3 = st.number_input("Consumo de gas estimado (m³)", min_value=0.0, value=1.0, step=0.1)
    
    with col_man2:
        material_man_seleccionado = st.selectbox("Material de la Chapa", materiales_disponibles, key="mat_cotizador_man")
        espesores_man_disponibles = df_chapas[df_chapas["Material"] == material_man_seleccionado]["Espesor (mm)"].unique()
        if len(espesores_man_disponibles) > 0:
            espesor_man_seleccionado = st.selectbox("Espesor (mm)", sorted(espesores_man_disponibles), key="esp_cotizador_man")
        else:
            st.warning("No hay espesores cargados para este material.")
            espesor_man_seleccionado = 0
            
        peso_manual_kg = st.number_input("Peso total de la pieza o recorte (kg)", min_value=0.0, value=10.0, step=1.0)
    
    st.write("---")
    
    if st.button("Calcular Costo Manual", type="primary", use_container_width=True):
        if espesor_man_seleccionado > 0:
            # Cálculos manuales basados en los inputs
            costo_tiempo_man = (tiempo_manual_min / 60) * nuevo_costo_hora
            
            precio_gas_unitario_man = nuevo_costo_oxigeno if gas_manual_tipo == "Oxígeno" else nuevo_costo_nitrogeno
            costo_gas_man = consumo_gas_manual_m3 * precio_gas_unitario_man
            
            # Buscar el precio por kg del material en la base de datos
            fila_material_man = df_chapas[(df_chapas["Material"] == material_man_seleccionado) & (df_chapas["Espesor (mm)"] == espesor_man_seleccionado)]
            precio_kg_chapa_man = fila_material_man["Precio por Kg ($)"].values[0]
            
            costo_material_man = peso_manual_kg * precio_kg_chapa_man
            
            costo_total_man = costo_tiempo_man + costo_gas_man + costo_material_man
            
            st.header("Resultados de la Cotización Manual")
            st.subheader(f"Costo Total: ${costo_total_man:.2f}")
            
            with st.expander("Ver desglose detallado de costos", expanded=True):
                st.write(f"🏭 **Operación CNC:**")
                st.write(f"- Costo máquina ({tiempo_manual_min} min a ${nuevo_costo_hora}/h): **${costo_tiempo_man:.2f}**")
                st.write(f"- Costo {gas_manual_tipo} ({consumo_gas_manual_m3} m³ a ${precio_gas_unitario_man}/m³): **${costo_gas_man:.2f}**")
                st.write(f"📦 **Materia Prima:**")
                st.write(f"- Costo {material_man_seleccionado} {espesor_man_seleccionado}mm ({peso_manual_kg} kg a ${precio_kg_chapa_man}/kg): **${costo_material_man:.2f}**")
        else:
            st.error("Por favor, selecciona un espesor válido.")

# ==========================================
# PESTAÑA 3: BASE DE DATOS DE MATERIALES
# ==========================================
with tab3:
    st.header("🗄️ Gestión de Precios por Espesor")
    st.write("Ingresa el Precio por Kg. El sistema calculará automáticamente el Precio por Metro Cuadrado (m²) al guardar.")

    column_config = {
        "Material": st.column_config.SelectboxColumn(
            "Tipo de Material",
            options=["Acero al Carbono", "Acero Inoxidable", "Aluminio"],
            required=True
        ),
        "Espesor (mm)": st.column_config.NumberColumn(
            "Espesor (mm)",
            min_value=0.1,
            format="%.1f",
            required=True
        ),
        "Precio por Kg ($)": st.column_config.NumberColumn(
            "Precio por Kg ($)",
            min_value=0,
            format="$%d",
            required=True
        ),
        "Precio por m2 ($)": st.column_config.NumberColumn(
            "Precio por m² ($) (Calculado)",
            disabled=True 
        )
    }
    
    column_order = ["Material", "Espesor (mm)", "Precio por Kg ($)", "Precio por m2 ($)"]

    df_editado = st.data_editor(
        df_chapas, 
        column_order=column_order,
        num_rows="dynamic",
        use_container_width=True,
        column_config=column_config
    )

    if st.button("Guardar Cambios y Calcular m²", type="primary"):
        df_actualizado = guardar_bd_chapas(df_editado)
        st.success("✅ Base de datos actualizada y precios por m² recalculados.")
        st.rerun()

# ==========================================
# PESTAÑA 4: CALCULADORA DE PESOS
# ==========================================
with tab4:
    st.header("⚖️ Calculadora de Pesos de Chapa")
    st.write("Consulta rápidamente el peso teórico del material sin salir de la aplicación.")
    
    col_peso1, col_peso2 = st.columns(2)
    with col_peso1:
        material_peso = st.selectbox("Tipo de Material", list(DENSIDADES.keys()), key="mat_calculadora_peso")
    with col_peso2:
        espesor_peso = st.number_input("Espesor de la chapa (mm)", min_value=0.1, value=1.0, step=0.1, key="esp_calculadora_peso")
        
    st.write("---")
    
    st.subheader("Opcional: Calcular peso de una pieza o recorte específico")
    col_peso3, col_peso4 = st.columns(2)
    with col_peso3:
        ancho_peso = st.number_input("Ancho (mm)", min_value=1.0, value=1000.0, step=100.0, key="ancho_calculadora_peso")
    with col_peso4:
        largo_peso = st.number_input("Largo (mm)", min_value=1.0, value=1000.0, step=100.0, key="largo_calculadora_peso")
        
    peso_por_m2 = espesor_peso * DENSIDADES[material_peso]
    area_m2_peso = (ancho_peso * largo_peso) / 1000000
    peso_total = area_m2_peso * peso_por_m2
    
    st.write("")
    
    res_peso1, res_peso2 = st.columns(2)
    res_peso1.metric("⚖️ Peso por Metro Cuadrado", f"{peso_por_m2:.2f} kg/m²")
    res_peso2.metric("📦 Peso Total de la Pieza", f"{peso_total:.2f} kg")
