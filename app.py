import streamlit as st
from docx import Document
import google.generativeai as genai
import pandas as pd
import json
import re
from fpdf import FPDF
import pypdf
import io

# ==========================================
# 1. SUPER BIBLIOTECA RJAIA
# ==========================================
RJAIA_LIBRARY = {
    "Regime Geral (AIA)": {
        "RJAIA": "Decreto-Lei n.º 151-B/2013, de 31 de outubro (alterado pelo DL 11/2023 - Simplex)",
        "LUA (Licenciamento Único)": "Decreto-Lei n.º 75/2015, de 11 de maio",
        "Regime da Consulta Pública": "Artigos 28.º a 31.º do DL 151-B/2013",
        "Pós-Avaliação (RECAPE)": "Portaria n.º 395/2015, de 4 de novembro"
    },
    "Taxas e Administrativo": {
        "Taxas AIA": "Portaria n.º 332-B/2015, de 2 de outubro (Redação atual)",
        "Prazo de Vigência da DIA": "Artigo 23.º do DL 151-B/2013"
    },
    "Normas Técnicas e Guias APA": {
        "Alterações Climáticas": "Lei de Bases do Clima (Lei n.º 98/2021) e Guia APA",
        "Fatores Críticos": "Guia de Fatores Críticos de Decisão da APA"
    },
    "Legislação Setorial": {
        "Pedreiras/Minas": "DL 270/2001 e DL 30/2021",
        "Energia/Eólicas": "DL 15/2022 e Despacho 6636/2023",
        "Hídrico": "Lei da Água (Lei 58/2005) e TURH"
    }
}

# ==========================================
# 2. MOTOR DE PDF (Extrator e Gerador)
# ==========================================

# --- A. Leitura do PDF de Input ---
def read_pdf(file):
    """Extrai texto de um ficheiro PDF."""
    try:
        reader = pypdf.PdfReader(file)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text
    except Exception as e:
        return f"Erro ao ler PDF: {e}"

# --- B. Leitura do Word de Input ---
def read_docx(file):
    """Extrai texto de um ficheiro DOCX."""
    doc = Document(file)
    full_text = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(full_text)

# --- C. Geração do Relatório PDF (Output) ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Relatorio de Auditoria PTF - RJAIA (IA)', 0, 1, 'C')
        self.ln(5)
        self.set_draw_color(0, 80, 180) 
        self.set_line_width(0.5)
        self.line(10, 25, 200, 25)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

def create_pdf_report(df):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Resumo
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, 'Resumo Executivo', 0, 1)
    
    pdf.set_font('Arial', '', 10)
    total = len(df)
    graves = len(df[df['gravidade'].str.contains('Alta|Grave', case=False, na=False)])
    pdf.cell(0, 6, f"Total de Observacoes: {total}", 0, 1)
    pdf.cell(0, 6, f"Desconformidades Graves: {graves}", 0, 1)
    pdf.ln(5)

    # Detalhes
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, 'Detalhe das Observacoes', 0, 1)
    
    def safe_txt(text):
        try:
            return text.encode('latin-1', 'replace').decode('latin-1')
        except:
            return str(text)

    for index, row in df.iterrows():
        pdf.set_font('Arial', 'B', 10)
        if "Alta" in str(row.get('gravidade', '')):
            pdf.set_text_color(200, 0, 0)
            icon = "[!]"
        else:
            pdf.set_text_color(0, 0, 0)
            icon = "[-]"
            
        title = f"{icon} {safe_txt(row.get('categoria', 'Geral'))} ({safe_txt(row.get('gravidade', '-'))})"
        pdf.cell(0, 8, title, 0, 1)
        
        pdf.set_font('Arial', '', 9)
        pdf.set_text_color(50, 50, 50)
        
        pdf.multi_cell(0, 5, safe_txt(f"Texto Original: {row.get('texto_detetado', 'N/A')}"))
        pdf.multi_cell(0, 5, safe_txt(f"Problema: {row.get('problema', 'N/A')}"))
        
        pdf.set_font('Arial', 'I', 9)
        pdf.set_text_color(0, 100, 0) 
        pdf.multi_cell(0, 5, safe_txt(f"Sugestao: {row.get('sugestao', 'N/A')}"))
        
        pdf.ln(3)
        pdf.set_draw_color(220, 220, 220)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

    return pdf.output(dest='S').encode('latin-1')

# ==========================================
# 3. LÓGICA AI (GEMINI)
# ==========================================

def get_library_context():
    return json.dumps(RJAIA_LIBRARY, ensure_ascii=False, indent=2)

def clean_json_string(json_str):
    cleaned = re.sub(r"```json\s*", "", json_str)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    return cleaned.strip()

def analyze_ptf_expert(text, api_key, model_name):
    genai.configure(api_key=api_key)
    library_context = get_library_context()
    
    system_prompt = f"""
    Tu és um Auditor Técnico da APA (Agência Portuguesa do Ambiente).
    BIBLIOTECA LEGAL: {library_context}
    
    INSTRUÇÃO: Analisa o PTF fornecido procurando:
    1. Legislação desatualizada ou incorreta (cruzar com a Biblioteca).
    2. Menção obrigatória ao DL 11/2023 (Simplex).
    3. Erros de português ou linguagem não técnica.
    
    OUTPUT JSON (Lista estrita):
    [
      {{
        "categoria": "Legislação",
        "gravidade": "Alta", 
        "texto_detetado": "...",
        "problema": "...",
        "sugestao": "..."
      }}
    ]
    """
    
    config = {"temperature": 0.1, "response_mime_type": "application/json"}
    
    try:
        model = genai.GenerativeModel(model_name=model_name, generation_config=config, system_instruction=system_prompt)
        response = model.generate_content(f"PTF:\n{text}")
        return response.text
    except Exception as e:
        return json.dumps({"erro_sistema": str(e)})

# ==========================================
# 4. INTERFACE
# ==========================================

st.set_page_config(page_title="RJAIA Expert (PDF/Docx)", page_icon="📑", layout="wide")

st.sidebar.title("⚙️ Configuração")
api_key = st.sidebar.text_input("Google API Key", type="password")

model_options = ["models/gemini-1.5-flash"]
if api_key:
    try:
        genai.configure(api_key=api_key)
        ms = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if ms: model_options = sorted(ms, reverse=True)
        st.sidebar.success(f"Conectado: {len(model_options)} modelos.")
    except:
        pass

selected_model = st.sidebar.selectbox("Modelo", model_options)

st.title("📑 Analisador PTF Universal (PDF & Word)")
st.markdown("Suporta documentos **Word** editáveis e **PDFs** (nativos).")

# Atualizado para aceitar 'pdf'
uploaded_file = st.file_uploader("Carregue o PTF", type=["docx", "pdf"])

if uploaded_file and api_key:
    if st.button("🚀 Analisar Documento", type="primary"):
        with st.spinner("A extrair texto e a auditar..."):
            
            # --- SELETOR DE FORMATO ---
            file_type = uploaded_file.name.split('.')[-1].lower()
            text_content = ""
            
            if file_type == 'pdf':
                text_content = read_pdf(uploaded_file)
            elif file_type == 'docx':
                text_content = read_docx(uploaded_file)
            
            # --- CHECK DE TEXTO VAZIO (SCAN) ---
            if len(text_content.strip()) < 50:
                st.error("⚠️ O texto extraído é muito curto ou vazio.")
                st.warning("""
                Possível causa: O PDF é uma imagem (digitalização/scan) e não texto selecionável.
                Esta APP requer PDFs com texto selecionável (nativos).
                """)
            else:
                # Processamento Normal
                st.info(f"Texto extraído com sucesso: {len(text_content)} caracteres.")
                res_str = analyze_ptf_expert(text_content, api_key, selected_model)
                st.session_state['result_json'] = res_str

    if 'result_json' in st.session_state:
        try:
            data = json.loads(clean_json_string(st.session_state['result_json']))
            if isinstance(data, dict) and "erro_sistema" in data:
                st.error(data['erro_sistema'])
            else:
                if isinstance(data, dict): data = list(data.values())[0] if data else []
                if not isinstance(data, list): data = [data]

                df = pd.DataFrame(data)
                
                col_kpi, col_table = st.columns([1, 3])
                
                with col_kpi:
                    st.info("Resumo")
                    st.metric("Total", len(df))
                    n_graves = len(df[df['gravidade'].str.contains('Alta', na=False)])
                    st.metric("Graves", n_graves, delta_color="inverse" if n_graves > 0 else "normal")
                    st.divider()
                    
                    if not df.empty:
                        pdf_bytes = create_pdf_report(df)
                        st.download_button(
                            "📄 Baixar Relatório PDF",
                            pdf_bytes,
                            "relatorio_auditoria.pdf",
                            "application/pdf"
                        )

                with col_table:
                    st.dataframe(df, use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Erro no processamento: {e}")

elif not api_key:
    st.info("Insira a API Key na barra lateral.")
