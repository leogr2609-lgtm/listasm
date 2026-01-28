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

    # --- 🎛️ PANEL DE CONTROL (AJUSTA TU DISEÑO AQUÍ) ---
    
    # 1. PROPORCIONES (Para imitar a Hevy)
    # Hevy usa aprox: 15% espacio | 30% formulario | 55% imagen
    ANCHO_ESPACIO_IZQ = 0.6   # Margen izquierdo (para que no se pegue al borde)
    ANCHO_FORMULARIO = 1.4    # Ancho del login
    ANCHO_IMAGEN = 3.0        # Ancho de la imagen (El lado derecho grande)
    
    # 2. COLORES & ESTILO
    COLOR_FONDO_IZQ = "#FFFFFF"   # Blanco puro (Hevy style)
    COLOR_TEXTO = "#111827"       # Negro suave (Charcoal)
    COLOR_BOTON = "#9CA3AF"       # Gris Hevy (O usa tu verde #0C5A5D)
    COLOR_BOTON_TEXTO = "#FFFFFF" 
    
    # 3. IMAGEN LATERAL
    # Nota: Usa una imagen VERTICAL para que llene bien el espacio
    IMG_URL = "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?q=80&w=2070&auto=format&fit=crop"

    # -----------------------------------------------------------

    # --- CSS AVANZADO (PARA CORREGIR EL TEXTO BLANCO Y DAR ESTILO) ---
    st.markdown(f"""
    <style>
    /* 1. FORZAR MODO CLARO (Soluciona el texto invisible) */
    [data-testid="stAppViewContainer"] {{
        background-color: {COLOR_FONDO_IZQ} !important;
    }}
    
    /* 2. TIPOGRAFÍA MINIMALISTA (Estilo Apple/Hevy) */
    * {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
        letter-spacing: -0.2px;
    }}
    h1, h2, h3, p, span, div, label {{
        color: {COLOR_TEXTO} !important;
        text-shadow: none !important;
    }}
    
    /* 3. INPUTS (Cajas de texto estilo Hevy) */
    div[data-baseweb="input"] {{
        background-color: #FFFFFF !important;
        border: 1px solid #E5E7EB !important; /* Borde gris muy suave */
        border-radius: 8px !important;
        padding: 5px !important;
        box-shadow: none !important; /* Sin sombras raras */
    }}
    /* Corrección crítica para texto invisible en modo oscuro */
    input {{
        color: #000000 !important; 
        -webkit-text-fill-color: #000000 !important;
        caret-color: #000000 !important;
    }}
    
    /* 4. BOTÓN (Estilo Hevy: Ancho y Neutro) */
    div[data-testid="stButton"] button {{
        width: 100%;
        background-color: {COLOR_BOTON} !important;
        color: {COLOR_BOTON_TEXTO} !important;
        border: none;
        padding: 14px !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        font-size: 16px !important;
        margin-top: 10px;
        transition: background-color 0.2s;
    }}
    div[data-testid="stButton"] button:hover {{
        background-color: #4B5563 !important; /* Gris más oscuro al pasar mouse */
    }}

    /* 5. ARREGLAR MÁRGENES DE LA IMAGEN (Full Bleed) */
    /* Quitamos padding de la columna derecha para que la imagen toque los bordes */
    div[data-testid="column"]:last-child {{
        padding-top: 0px !important;
        padding-right: 0px !important;
        padding-left: 20px !important; /* Separación con el formulario */
    }}
    
    /* Ocultar header/footer de Streamlit */
    header, footer {{visibility: hidden;}}
    </style>
    """, unsafe_allow_html=True)

    # --- LAYOUT DE 3 COLUMNAS (Espacio | Formulario | Imagen) ---
    col_espacio, col_form, col_img = st.columns(
        [ANCHO_ESPACIO_IZQ, ANCHO_FORMULARIO, ANCHO_IMAGEN], 
        gap="small"
    )

    # --- COLUMNA CENTRAL (EL FORMULARIO) ---
    with col_form:
        # Espaciadores para centrar verticalmente "a ojo"
        st.write("") 
        st.write("") 
        st.write("") 
        st.write("")
        
        # Títulos Minimalistas
        st.markdown("<h1 style='font-size: 32px; font-weight: 700; margin-bottom: 5px; text-align: left;'>Log In</h1>", unsafe_allow_html=True)
        # Opcional: Botones de Google/Apple falsos para estética (como en la foto)
        # st.info("G   Login with Google") 
        
        st.write("") # Espacio
        
        # --- INPUT 1: USUARIO ---
        st.markdown("<p style='font-size: 13px; font-weight: 500; margin-bottom: 5px; color: #374151 !important;'>Email or username</p>", unsafe_allow_html=True)
        usuario = st.text_input(
            "Usuario",
            key="user_input",
            label_visibility="collapsed",
            placeholder="" # Hevy no usa placeholder, deja el campo limpio
        )
        
        st.write("") # Espacio pequeño

        # --- INPUT 2: PASSWORD ---
        st.markdown("<p style='font-size: 13px; font-weight: 500; margin-bottom: 5px; color: #374151 !important;'>Password</p>", unsafe_allow_html=True)
        password = st.text_input(
            "Contraseña", 
            type="password", 
            key="password_input",
            label_visibility="collapsed",
            placeholder=""
        )
        
        st.write("")
        
        # --- BOTÓN DE ACCIÓN ---
        # Nota: Puse el botón gris como Hevy. Si lo quieres verde, cambia la variable arriba.
        if st.button("Login", use_container_width=True):
            if password == st.secrets["PASSWORD_ACCESO"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("Credenciales incorrectas")

        # Links de texto abajo
        st.markdown("""
            <div style='text-align: center; margin-top: 20px;'>
                <a href='#' style='color: #2563EB; text-decoration: none; font-size: 13px; font-weight: 500;'>Forgot Password</a>
                <br><br>
                <span style='color: #6B7280; font-size: 13px;'>New to Nutribere? </span>
                <a href='#' style='color: #2563EB; text-decoration: none; font-size: 13px; font-weight: 500;'>Sign Up</a>
            </div>
        """, unsafe_allow_html=True)

    # --- COLUMNA DERECHA (LA IMAGEN GRANDE) ---
    with col_img:
        # Muestra la imagen llenando el espacio
        st.image(IMG_URL, use_container_width=True)

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




















