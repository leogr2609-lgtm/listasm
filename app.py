import streamlit as st
from fpdf import FPDF
import json
from datetime import datetime
import re
import pandas as pd
from google import genai
from google.genai import types
import PyPDF2
import io

# --- 1. CONFIGURACIÓN DE API Y MARCA ---
API_KEY = st.secrets["GOOGLE_API_KEY"]

# Configuración VITAL: v1beta para Gemini 3 Flash Preview
client = genai.Client(
    api_key=API_KEY, 
    http_options={'api_version': 'v1beta'}
)

COLOR_TEAL = (12, 90, 93)      # #0C5A5D
COLOR_YELLOW = (251, 192, 45)  # #FBC02D
COLOR_TEXT_DARK = (40, 40, 40) # #282828
COLOR_WHITE = (255, 255, 255)

st.set_page_config(
    page_title="Nutribere Studio",
    page_icon="🍏",
    layout="wide", # <--- ESTO ES LA CLAVE (Antes decía "centered" o no estaba)
    initial_sidebar_state="collapsed"
)

# --- 2. PROMPT MAESTRO (TU PROMPT EXACTO) ---
SYSTEM_INSTRUCTION = """
<NUCLEO_DE_PROCESAMIENTO>
Rol: Motor de Cálculo Logístico para Retail Alimentario (Nutrilista API).
Región Objetivo: Tijuana, Baja California, México.
Misión: Transformar planes alimenticios en una "Lista de Compra Base (Ciclo 1x)" consolidada, matemática y estéticamente legible.
</NUCLEO_DE_PROCESAMIENTO>

<PROTOCOLO_ALGORITMICO_SECUENCIAL>
Debes ejecutar estos 5 pasos en orden estricto antes de generar el JSON:

PASO 1: EXTRACCIÓN Y LIMPIEZA DE DATOS
- Input: Texto del PDF (Plan Nutricional).
- Acción: Extrae todos los ingredientes de todos los menús disponibles.
- Filtro de Exclusión: Ignora agua, sal, pimienta y especias menores a 2g.
- Filtro de Integridad (Anti-Procesados):
  * Si el plan dice "Frijoles molidos", "Frijoles de la olla" o "Frijoles enteros": TU SALIDA OBLIGATORIA ES "Frijol en grano (crudo)".
  * PROHIBIDO: Sugerir "Frijoles refritos", "Enlatados" o productos con sellos de exceso de grasa/sodio a menos que sea explícito.

PASO 2: LÓGICA DE CONSOLIDACIÓN (ESTRATEGIA CICLO 1x)
- Objetivo: Generar el inventario exacto para preparar CADA menú del documento UNA SOLA VEZ.
- Operación Matemática: SUMA CONDICIONAL.
  * Si el ingrediente es EXACTAMENTE el mismo, súmalo.
  * REGLA DE SEGREGACIÓN DE CORTES (CRÍTICO - PROTEÍNAS):
    - NO agrupes carnes solo por el animal. Distingue por TIPO DE CORTE.
    - "Carne molida" ES DIFERENTE A "Bistec", "Milanesa" o "Trozos".
    - Si el plan pide "120g Bistec" y "225g Molida", TU SALIDA DEBE SER DOS LÍNEAS SEPARADAS. NO LAS SUMES.

PASO 3: INGENIERÍA INVERSA DE COCCIÓN (RAW YIELD CALCULATION)
- Detecta ingredientes que cambian de volumen al cocinarse: Arroz, Pasta, Avena, Quinoa, Leguminosas.
- Asunción: Las cantidades en el plan nutricional suelen ser en estado COCIDO/PREPARADO.
- Acción: Calcula el equivalente en CRUDO para la compra.
  * Factor de conversión aprox: Divide el volumen cocido entre 2.5 o 3.
  * Ejemplo: Si la suma total es "4 tazas de arroz cocido" -> La lista de compra debe ser "1 Bolsa de arroz (aprox. 500g-1kg)".

PASO 4: LOCALIZACIÓN Y TRADUCCIÓN COMERCIAL (TIJUANA)
- Diccionario Obligatorio:
  * "Jitomate" -> TRADUCIR A "Tomate" (Rojo).
  * "Tomate" (verde) -> TRADUCIR A "Tomatillo".
  * "Domo" -> TRADUCIR A "Cajita", "Paquete" o "Charola".
  * "Pieza de pan" -> "Rebanada" o "Barra".

- Reglas de Presentación por Categoría:
  A) PROTEÍNAS (Carne, Pollo, Pescado, Cerdo):
     * Cero Redondeo Comercial: NO sugerir charolas.
     * Salida: Muestra la SUMA EXACTA EN GRAMOS/KILOS.

  B) LÁCTEOS, EMBUTIDOS Y DESPENSA:
     * Redondeo al Alza (Ceiling): Ajusta a la unidad de venta cerrada más cercana.
     * Ejemplo: Si necesita 1.2 rebanadas de Jamón -> "1 Paquete de jamón".

PASO 5: FORMATEO ESTÉTICO DE TEXTO (CRÍTICO)
- Tu salida son "Strings de Texto", deben ser limpios y legibles.
- REGLA 1 (Sentence Case): Solo la PRIMERA letra del nombre del producto debe ir en mayúscula. El resto en minúsculas (salvo nombres propios).
- REGLA 2 (Limpieza): Elimina palabras redundantes como "Total:" dentro del paréntesis. Usa solo el número y la unidad.
- FORMATO OBLIGATORIO: "Nombre del producto (Cantidad)"
  * Correcto: "Pechuga de pollo (650g)"
  * Correcto: "Carne molida de res (225g)"
  * Incorrecto: "Pechuga De Pollo (650g)" (Demasiadas mayúsculas)
  * Incorrecto: "pechuga de pollo (650g)" (Todo minúsculas)
</PROTOCOLO_ALGORITMICO_SECUENCIAL>

<FORMATO_DE_SALIDA>
- Estructura: Objeto JSON válido.
- Restricción: NO incluyas markdown (```json), texto introductorio ni explicaciones.
- Unidades Prohibidas en Output: Tazas, cucharadas, pizcas. Usa siempre: Kg, g, Litro, Pieza, Manojo, Paquete, Bolsa, Bote.

{
  "Verduras": ["String (Producto + Cantidad Tijuanense)"],
  "Frutas": ["String (Producto + Cantidad Tijuanense)"],
  "Proteínas": ["String (Producto + Gramaje Neto Exacto)"],
  "Grasas y Lácteos": ["String (Producto + Presentación Comercial)"],
  "Cereales y Tubérculos": ["String (Producto + Presentación Base Cruda)"],
  "Extras y Despensa": ["String (Producto + Presentación Comercial)"]
}
</FORMATO_DE_SALIDA>
"""

# --- 3. CSS "NUTRIBERE GLASS" ---
st.markdown("""
    <style>
    /* 1. FONDO GLOBAL: TEAL NUTRIBERE */
    .stApp { background-color: #0C5A5D; }

    /* 2. TEXTOS: BLANCO PURO */
    h1, h2, h3, h4, p, span, div, label {
        color: #FFFFFF !important;
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    }
    h1 { text-shadow: 0 2px 4px rgba(0,0,0,0.3); }

    /* 3. EFECTO "GLASSMORPHISM" */
    div[data-testid="stVerticalBlock"] > div[style*="background-color"] {
        background-color: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 16px; padding: 2rem;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
    }
    
    /* 4. INPUTS */
    div[data-baseweb="input"], div[data-baseweb="textarea"], .stTextInput input, .stTextArea textarea {
        background-color: #FFFFFF !important; 
        color: #0C5A5D !important;
        border: none; border-radius: 8px;
    }
    label[data-testid="stWidgetLabel"] p {
        color: #FBC02D !important; 
        font-weight: 600; font-size: 14px; text-transform: uppercase; letter-spacing: 1px;
    }

    /* 5. BOTONES */
    .stButton>button {
        background-color: #FBC02D !important; color: #0C5A5D !important;
        font-weight: 800; font-size: 16px; border-radius: 10px; border: none;
        padding: 0.8rem 1rem; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #FFFFFF !important; color: #0C5A5D !important;
        transform: scale(1.02); box-shadow: 0 6px 20px rgba(0,0,0,0.3);
    }
    
    /* 6. TABLAS Y EXPANDERS */
    div[data-testid="stDataEditor"] {
        border-radius: 10px; overflow: hidden; border: 1px solid rgba(255, 255, 255, 0.3);
    }
    .streamlit-expanderHeader {
        background-color: rgba(255, 255, 255, 0.1) !important;
        color: #FBC02D !important; font-weight: bold; border-radius: 8px;
    }
    
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 4. CLASE PDF (CORREGIDA Y BLINDADA) ---
class NutriListPDF(FPDF):
    def __init__(self, nombre_paciente):
        super().__init__()
        self.nombre_paciente = nombre_paciente
        # Márgenes laterales
        self.set_margins(left=20, top=20, right=20)

    def header(self):
        # Fondo Verde
        self.set_fill_color(*COLOR_TEAL)
        self.rect(0, 0, 210, 52, 'F')
        
        # Nombre
        self.set_font('Helvetica', 'B', 28)
        self.set_text_color(*COLOR_WHITE)
        self.set_y(15)
        self.cell(0, 10, self.nombre_paciente, ln=True, align='C')
        
        # Línea Amarilla
        self.set_draw_color(*COLOR_YELLOW)
        self.set_line_width(1.5)
        self.line(70, 28, 140, 28)
        
        # Subtítulo
        self.set_font('Helvetica', '', 11)
        self.set_y(35)
        self.cell(0, 10, 'LISTA DE SUPERMERCADO INTELIGENTE', ln=True, align='C')
        
        # AJUSTE ANTICHOQUE: Obligamos a empezar abajo del header
        self.set_y(60)

    def footer(self):
        self.set_y(-20)
        self.set_font('Helvetica', 'I', 12)
        self.set_text_color(80, 80, 80) 
        self.cell(0, 10, '-nutribere(:', align='C')
        
        self.set_font('Helvetica', '', 9)
        self.set_text_color(150, 150, 150)
        self.set_x(-30)
        self.cell(0, 10, f'Pág {self.page_no()}/{{nb}}', align='R')

# --- 5. FUNCIONES LÓGICAS ---

# A. Función de IA
def procesar_con_ia(pdf_file):
    reader = PyPDF2.PdfReader(pdf_file)
    texto = "".join([page.extract_text() for page in reader.pages])
    
    try:
        response = client.models.generate_content(
            model="models/gemini-3-flash-preview",
            contents=texto,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0,
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Error de IA: {e}")
        return {}

# B. Generador de PDF (VERSIÓN FINAL CON TEXTO APROBADO)
def generar_pdf_desde_editor(datos_editados, nombre_paciente):
    pdf = NutriListPDF(nombre_paciente)
    pdf.alias_nb_pages()
    pdf.add_page()
    # Margen inferior para evitar cortes
    pdf.set_auto_page_break(auto=True, margin=28)
    
    # --- BUCLE DE INGREDIENTES ---
    for categoria, items_df in datos_editados.items():
        lista_items = items_df["Producto"].dropna().tolist()
        lista_items = [x for x in lista_items if x.strip()]

        if not lista_items: continue
        
        # TÍTULOS DE CATEGORÍA
        if pdf.get_y() > 225: pdf.add_page()
        else: pdf.ln(5)

        # Estilo Teal para encabezados
        pdf.set_fill_color(*COLOR_TEAL)
        pdf.set_text_color(*COLOR_WHITE)
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 10, f"  {categoria.upper()}", ln=True, fill=True)
        pdf.ln(3)
        
        pdf.set_font('Helvetica', '', 11)
        pdf.set_text_color(*COLOR_TEXT_DARK)
        
        # LISTA DE ÍTEMS
        for item in lista_items:
            if pdf.get_y() > 260:
                pdf.add_page()
                pdf.set_font('Helvetica', '', 11)
                pdf.set_text_color(*COLOR_TEXT_DARK)

            # Checkbox visual (cuadrito amarillo)
            pdf.set_x(15)
            pdf.set_draw_color(*COLOR_YELLOW)
            pdf.set_line_width(0.5)
            pdf.rect(15, pdf.get_y() + 1.2, 4.5, 4.5) 
            
            # Texto del ingrediente
            pdf.set_x(24) 
            pdf.multi_cell(0, 7, str(item))
            pdf.ln(1)

    # --- AQUÍ EMPIEZA LA SECCIÓN NUEVA (NOTA FINAL) ---
    pdf.ln(10) # Espacio antes de la nota
    
    # Calculamos si cabe en la hoja, si no, salta de página
    if pdf.get_y() > 220: 
        pdf.add_page()
    
    # 1. Línea separadora gris
    pdf.set_draw_color(200, 200, 200)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(6)
    
    # 2. Título en color Teal (Marca)
    pdf.set_text_color(*COLOR_TEAL)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, "CÓMO USAR TU LISTA DE SÚPER", ln=True)
    
    # 3. Texto del cuerpo (Gris oscuro para lectura fácil)
    pdf.set_text_color(80, 80, 80)
    pdf.set_font('Helvetica', '', 9)
    
    # El texto exacto que me diste
    mensaje_final = (
        "Esta lista trae los ingredientes exactos para cocinar cada uno de tus menús una sola vez.\n\n"
        "¿Vas a repetir menús? Si decides repetir un menú completo en la semana (ej. volver a comer el Menú 1 el jueves), "
        "simplemente agrega a tu carrito la cantidad extra necesaria para ese día.\n\n"
        "Ejemplo: Si el Menú 1 pide 100g de pollo y lo vas a preparar dos veces en la semana, ¡recuerda comprar 100g más!\n\n"
        "Importante: Las cantidades mostradas son estimaciones logísticas aproximadas para facilitar tu compra. "
        "Ajusta según tus preferencias."
    )
    
    # Imprimimos el bloque de texto
    pdf.multi_cell(0, 5, mensaje_final)
            
   # Corrección: Forzamos la salida como String ('S') y la codificamos a Latin-1 (estándar de FPDF)
    return pdf.output(dest='S').encode('latin-1')

# --- 6. INTERFAZ PRINCIPAL ---
import streamlit as st
def check_password():
    """Retorna True si el usuario ingresó la contraseña correcta."""
    
    if st.session_state.get("password_correct", False):
        return True

    # --- ESTILO TIPO "HEVY" (SaaS CLEAN) ---
    st.markdown("""
    <style>
    /* 1. FORZAR MODO CLARO (WHITE MODE) */
    /* Esto obliga a que el fondo sea blanco aunque tu navegador esté en oscuro */
    [data-testid="stAppViewContainer"] {
        background-color: #FFFFFF !important;
    }
    [data-testid="stHeader"] {
        background-color: rgba(0,0,0,0) !important;
    }
    
    /* 2. TEXTOS EN NEGRO */
    h1, h2, h3, p, label, span, div {
        color: #1A1A1A !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* 3. INPUTS (Estilo Hevy: Borde gris suave, fondo blanco, esquinas redondeadas) */
    div[data-baseweb="input"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E0E0E0 !important;
        border-radius: 8px !important;
        padding: 4px !important;
    }
    /* Arreglo del input de password y texto */
    input {
        color: #000000 !important;
        background-color: #FFFFFF !important;
    }
    
    /* 4. BOTÓN (Estilo Hevy: Ancho completo, Gris o Color Marca) */
    div[data-testid="stButton"] button {
        width: 100%;
        background-color: #0C5A5D !important; /* Tu color Teal */
        color: #FFFFFF !important; /* Texto Blanco */
        border: none;
        padding: 12px;
        font-weight: 600;
        border-radius: 8px;
        transition: background-color 0.3s;
        margin-top: 10px;
    }
    div[data-testid="stButton"] button:hover {
        background-color: #094648 !important; /* Un poco más oscuro al hover */
        box-shadow: 0 4px 12px rgba(12, 90, 93, 0.2);
    }

    /* Ocultar elementos innecesarios */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Ajuste para la columna de la derecha (Imagen/Brand) */
    .brand-column {
        background-color: #F4F6F8;
        border-radius: 20px;
        padding: 20px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    </style>
    """, unsafe_allow_html=True)

    # --- LAYOUT DE PANTALLA DIVIDIDA ---
    # Columna Izquierda (40%): Login
    # Columna Derecha (60%): Branding/Imagen (Como Hevy)
    col_login, col_brand = st.columns([1, 1.5], gap="large")

    # --- COLUMNA IZQUIERDA: FORMULARIO ---
    with col_login:
        st.write("") 
        st.write("") 
        st.write("") # Espaciado superior para centrar
        
        # Logo pequeño arriba
        st.markdown("<h3 style='margin-bottom: 0;'>🍏 nutribere</h3>", unsafe_allow_html=True)
        st.write("")
        
        # Título Grande "Log In"
        st.markdown("<h1 style='font-size: 42px; font-weight: 700; margin-bottom: 10px;'>Iniciar Sesión</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #666 !important; margin-bottom: 30px;'>Bienvenida de nuevo a tu espacio de trabajo.</p>", unsafe_allow_html=True)

        # Inputs con etiquetas limpias
        # Nota: Ponemos label_visibility="visible" porque en estilo limpio SÍ se usan etiquetas
        st.markdown("<p style='font-weight: 600; font-size: 14px; margin-bottom: 5px;'>Contraseña</p>", unsafe_allow_html=True)
        password = st.text_input(
            "Contraseña", 
            type="password", 
            key="password_input",
            label_visibility="collapsed", # Ocultamos la etiqueta nativa para usar la nuestra personalizada arriba
            placeholder="Introduce tu clave de acceso"
        )
        
        st.write("")
        
        # Botón
        if st.button("INGRESAR"):
            if password == st.secrets["PASSWORD_ACCESO"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("La contraseña es incorrecta.")

        # Link falso de "Olvidé mi contraseña" (Solo estético)
        st.markdown("<div style='text-align: center; margin-top: 20px;'><a href='#' style='color: #0C5A5D; text-decoration: none; font-size: 14px;'>¿Olvidaste tu contraseña?</a></div>", unsafe_allow_html=True)

    # --- COLUMNA DERECHA: BRANDING (El lado "Bonito") ---
    with col_brand:
        # Aquí simulamos la imagen de la derecha. 
        # Como no tengo una imagen tuya, crearé un bloque de color con texto elegante.
        st.markdown("""
        <div style="
            background-color: #0C5A5D; 
            border-radius: 20px; 
            height: 85vh; 
            display: flex; 
            flex-direction: column; 
            justify-content: center; 
            align-items: center; 
            color: white;
            text-align: center;
            padding: 40px;
            background-image: linear-gradient(135deg, #0C5A5D 0%, #084042 100%);
        ">
            <h1 style="color: white !important; font-size: 50px;">Logística Inteligente <br>para Nutrición.</h1>
            <p style="color: rgba(255,255,255,0.8) !important; font-size: 18px; margin-top: 20px; max-width: 400px;">
                Genera listas de compra exactas, evita desperdicios y mejora la adherencia de tus pacientes.
            </p>
            <div style="margin-top: 40px; font-size: 80px;">🍏</div>
        </div>
        """, unsafe_allow_html=True)

    return False
# --- NUEVA FUNCIÓN: EL LIMPIADOR AUTOMÁTICO ---
def limpiar_memoria():
    """Esta función se activa SOLA cuando cambias el archivo PDF."""
    if 'datos_ia' in st.session_state:
        del st.session_state['datos_ia']

def main():
    # --- 1. BLOQUEO DE SEGURIDAD ---
    if not check_password():
        st.stop()
    
    # --- 2. DISEÑO DE CABECERA ---
    st.markdown("<div style='text-align: center; margin-bottom: 30px;'>", unsafe_allow_html=True)
    st.markdown("<h1 style='font-size: 50px; margin-bottom: 0;'>nutribere</h1>", unsafe_allow_html=True)
    st.markdown("<div style='text-align: center; margin-bottom: 30px;'>", unsafe_allow_html=True)
    st.markdown("<div style='width: 40px; height: 3px; background-color: #FBC02D; margin: 10px auto;'></div>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 14px; opacity: 0.8; letter-spacing: 2px;'>IMPRESORA DE LOGÍSTICA</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # --- 3. ENTRADAS DE USUARIO ---
    with st.container():
        col1, col2 = st.columns([1, 1])
        with col1:
            nombre_paciente = st.text_input("1. Nombre del Paciente", placeholder="Ej: Leo Garcia")
        
        with col2:
            # AQUÍ ESTÁ EL TRUCO: on_change=limpiar_memoria
            # Esto garantiza que al cambiar el archivo, se borren los datos viejos.
            archivo_pdf = st.file_uploader(
                "2. Sube el Plan (PDF)", 
                type="pdf", 
                on_change=limpiar_memoria 
            )

    st.write("") 

    # --- 4. LÓGICA DE PROCESAMIENTO E IA ---
    datos_para_pdf = {}
    
    if archivo_pdf and nombre_paciente:
        
        # Solo llama a la IA si no hay datos guardados
        if 'datos_ia' not in st.session_state:
            with st.spinner("🧠 Analizando el nuevo menú..."):
                st.session_state.datos_ia = procesar_con_ia(archivo_pdf)
        
        # --- 5. REVISIÓN Y EDICIÓN ---
        if st.session_state.get("datos_ia"):
            with st.container():
                st.markdown(f"<h3 style='border-bottom: 1px solid rgba(255,255,255,0.2); padding-bottom: 10px; margin-bottom: 20px;'>📋 Revisión: {nombre_paciente}</h3>", unsafe_allow_html=True)
                
                orden = ["Verduras", "Frutas", "Proteínas", "Grasas y Lácteos", "Cereales y Tubérculos", "Extras y Despensa"]
                data_ia = st.session_state.datos_ia
                
                # Asegurar categorías
                for cat in orden:
                    if cat not in data_ia: data_ia[cat] = []

                for categoria in orden:
                    items = data_ia.get(categoria, [])
                    with st.expander(f"{categoria.upper()} ({len(items)})", expanded=False):
                        df = pd.DataFrame(items, columns=["Producto"])
                        edited_df = st.data_editor(
                            df, 
                            num_rows="dynamic", 
                            use_container_width=True, 
                            key=f"ed_{categoria}",
                            column_config={"Producto": st.column_config.TextColumn("Editar Ingrediente")}
                        )
                        datos_para_pdf[categoria] = edited_df

                st.write("")
                
                # --- 6. BOTÓN DE IMPRESIÓN ---
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    if st.button("✨ IMPRIMIR LISTA OFICIAL"):
                        with st.spinner("Generando PDF..."):
                            try:
                                pdf_bytes = generar_pdf_desde_editor(datos_para_pdf, nombre_paciente)
                                
                                fecha = datetime.now().strftime("%Y-%m-%d")
                                nombre_safe = re.sub(r'[\\/*?:"<>|]', "", nombre_paciente)
                                nombre_archivo = f"{nombre_safe}_Lista_{fecha}.pdf"
                                
                                st.balloons()
                                st.success("¡LISTO PARA DESCARGAR!")
                                st.download_button(
                                    label="⬇️ DESCARGAR PDF",
                                    data=pdf_bytes,
                                    file_name=nombre_archivo,
                                    mime="application/pdf"
                                )
                            except Exception as e:
                                st.error(f"Error generando PDF: {e}")
        else:
             st.warning("La IA no pudo extraer datos. Intenta subir el PDF de nuevo.")
             
    elif archivo_pdf and not nombre_paciente:
        st.warning("⚠️ Por favor escribe el nombre del paciente antes de continuar.")

if __name__ == "__main__":
    main()














