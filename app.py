import streamlit as st
from docx import Document
from docx.shared import RGBColor
import google.generativeai as genai
import pandas as pd
import json
import re
from fpdf import FPDF
import pypdf
import io
import time

# ==========================================
# 1. BIBLIOTECA RJAIA
# ==========================================
RJAIA_LIBRARY = {
    "Regime Geral": "DL 151-B/2013 alterado pelo DL 11/2023 (Simplex)",
    "Taxas": "Portaria n.º 332-B/2015",
    "Clima": "Lei de Bases do Clima (Lei 98/2021)",
    "Prazos": "Atenção aos deferimentos tácitos do Simplex"
}

# ==========================================
# 2. FUNÇÕES DE LEITURA
# ==========================================
def read_pdf_with_pages(file):
    try:
        reader = pypdf.PdfReader(file)
        full_text = ""
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                full_text += f"\n<<<PÁGINA {i+1}>>>\n{text}"
        return full_text
    except Exception as e:
        return f"Erro PDF: {e}"

def read_docx(file):
    doc = Document(file)
    text = ""
    # Adicionar marcadores artificiais para ajudar na localização
    for i, para in enumerate(doc.paragraphs):
        if para.text.strip():
            # A cada 20 parágrafos, dá uma dica de localização aproximada
            if i % 20 == 0:
                text += f"\n<<<PARÁGRAFO APROX. {i}>>>\n"
            text += f"{para.text}\n"
    return text

# ==========================================
# 3. MOTOR DE FATIAMENTO (CHUNKING) - A SOLUÇÃO
# ==========================================
def split_text_into_chunks(text, max_chars=15000):
    """
    Divide o texto em pedaços menores para não estourar o limite de resposta da IA.
    Tenta cortar em quebras de linha para não partir palavras.
    """
    chunks = []
    current_chunk = ""
    
    paragraphs = text.split('\n')
    
    for para in paragraphs:
        if len(current_chunk) + len(para) < max_chars:
            current_chunk += para + "\n"
        else:
            chunks.append(current_chunk)
            current_chunk = para + "\n"
            
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks

def repair_json(json_str):
    """Tenta reparar JSON que foi cortado abruptamente (fallback)."""
    json_str = json_str.strip()
    # Se não termina com ']', tenta fechar
    if not json_str.endswith(']'):
        # Remove a última vírgula se houver e fecha
        json_str = json_str.rstrip(',').rstrip() 
        # Tenta fechar a string se estiver aberta
        if json_str.count('"') % 2 != 0:
            json_str += '"'
        # Tenta fechar o objeto se estiver aberto
        if json_str.count('{') > json_str.count('}'):
            json_str += '}'
        # Fecha a lista
        json_str += ']'
    return json_str

# ==========================================
# 4. GERAÇÃO DE RELATÓRIOS
# ==========================================
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Relatorio Auditoria RJAIA', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pag. {self.page_no()}', 0, 0, 'C')

def create_pdf_audit(df):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    def safe(txt): return str(txt).encode('latin-1', 'replace').decode('latin-1')
    
    for index, row in df.iterrows():
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 6, f"Loc: {safe(row.get('localizacao', '-'))} | {safe(row.get('categoria', '-'))}", 0, 1)
        pdf.set_font('Arial', '', 9)
        pdf.multi_cell(0, 5, safe(f"Orig: {row.get('texto_detetado', '')}"))
        pdf.set_text_color(200, 0, 0)
        pdf.multi_cell(0, 5, safe(f"Sug: {row.get('sugestao', '')}"))
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)
    return pdf.output(dest='S').encode('latin-1')

def generate_corrected_docx(original_text, corrections_df):
    doc = Document()
    doc.add_heading('PTF - Versão Corrigida (IA)', 0)
    
    # Normalização simples para tentar encontrar texto
    # (Remover marcadores para a reconstrução do Word limpo)
    clean_text = re.sub(r'<<<.*?>>>', '', original_text)
    paragraphs = clean_text.split('\n')
    errors = corrections_df.to_dict('records')

    for paragraph in paragraphs:
        if not paragraph.strip(): continue
        p = doc.add_paragraph()
        
        # Simples match (Case insensitive e parcial)
        processed = False
        
        # Para evitar complexidade excessiva, verificamos se algum erro "chave" está neste parágrafo
        # Num sistema produção real, usaríamos a biblioteca `diff_match_patch`
        matches = []
        for error in errors:
            bad = error.get('texto_detetado', '').strip()
            good = error.get('sugestao', '').strip()
            if len(bad) > 5 and bad in paragraph:
                matches.append((bad, good))
        
        if not matches:
            p.add_run(paragraph)
        else:
            # Estratégia simples: pintar o parágrafo inteiro se tiver muitos erros
            # ou tentar substituir o primeiro erro encontrado
            bad, good = matches[0] # Pega o primeiro erro encontrado no parágrafo
            
            parts = paragraph.split(bad)
            if len(parts) > 1:
                p.add_run(parts[0])
                run_err = p.add_run(good)
                run_err.font.color.rgb = RGBColor(255, 0, 0)
                run_err.bold = True
                p.add_run(parts[1])
            else:
                p.add_run(paragraph) # Fallback

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# ==========================================
# 5. LÓGICA AI (GEMINI) - AGORA COM CHUNKS
# ==========================================

def get_library_context():
    return json.dumps(RJAIA_LIBRARY, ensure_ascii=False, indent=2)

def clean_json_string(json_str):
    cleaned = re.sub(r"```json\s*", "", json_str)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    return cleaned.strip()

def analyze_chunk(chunk_text, api_key, model_name, library_context):
    """Analisa apenas um pedaço do texto."""
    genai.configure(api_key=api_key)
    
    system_prompt = f"""
    És um Revisor Técnico de AIA.
    BIBLIOTECA: {library_context}
    
    Analisa este excerto de um PTF. Procura:
    1. Gralhas e Erros Ortográficos.
    2. Frases confusas ou sintaxe incorreta (sugere reescrita).
    3. Referências legais erradas.
    
    IMPORTANTE:
    - O texto contém marcadores como <<<PÁGINA X>>>. Usa-os no campo 'localizacao'.
    - Se o texto estiver cortado no início ou fim, ignora frases incompletas.
    
    OUTPUT JSON (Lista):
    [
      {{
        "localizacao": "Página X",
        "categoria": "Sintaxe" (ou "Gralha", "Legislação"),
        "gravidade": "Alta/Baixa",
        "texto_detetado": "...",
        "sugestao": "..."
      }}
    ]
    """
    
    config = {
        "temperature": 0.1, 
        "response_mime_type": "application/json",
        "max_output_tokens": 8192 # Máximo permitido
    }
    
    try:
        model = genai.GenerativeModel(model_name=model_name, generation_config=config, system_instruction=system_prompt)
        response = model.generate_content(f"Analisa este excerto:\n{chunk_text}")
        return response.text
    except Exception as e:
        return f"ERROR: {str(e)}"

# ==========================================
# 6. INTERFACE STREAMLIT
# ==========================================

st.set_page_config(page_title="RJAIA Pro (Chunking)", page_icon="⚙️", layout="wide")

st.sidebar.title("Configuração")
api_key = st.sidebar.text_input("Google API Key", type="password")
model_choice = st.sidebar.selectbox("Modelo", ["models/gemini-1.5-flash", "models/gemini-1.5-pro"])

st.title("⚙️ Analisador RJAIA Robusto")
st.markdown("Processamento por blocos (Chunking) para evitar erros em documentos grandes.")

uploaded_file = st.file_uploader("Carregue PTF", type=["docx", "pdf"])

if uploaded_file and api_key:
    if st.button("🚀 Iniciar Análise Profunda", type="primary"):
        
        # 1. Ler Texto
        fname = uploaded_file.name.lower()
        full_text = ""
        if fname.endswith('.pdf'):
            full_text = read_pdf_with_pages(uploaded_file)
        else:
            full_text = read_docx(uploaded_file)
            
        if len(full_text) < 50:
            st.error("Texto vazio ou ilegível.")
            st.stop()
            
        # 2. Fatiar (Chunking)
        # Dividimos em blocos de 15.000 caracteres (aprox 5 páginas)
        chunks = split_text_into_chunks(full_text, max_chars=15000)
        
        st.info(f"O documento foi dividido em {len(chunks)} blocos para análise segura.")
        
        progress_bar = st.progress(0)
        master_results = []
        library_ctx = get_library_context()
        
        # 3. Processar cada fatia
        for i, chunk in enumerate(chunks):
            with st.spinner(f"A analisar bloco {i+1} de {len(chunks)}..."):
                raw_resp = analyze_chunk(chunk, api_key, model_choice, library_ctx)
                
                # Verificar erros de API
                if raw_resp.startswith("ERROR"):
                    st.warning(f"Falha no bloco {i+1}: {raw_resp}")
                    continue
                
                try:
                    cleaned = clean_json_string(raw_resp)
                    # Tentar parse normal
                    try:
                        data = json.loads(cleaned)
                    except json.JSONDecodeError:
                        # Se falhar, tenta o reparo
                        fixed = repair_json(cleaned)
                        data = json.loads(fixed)
                        
                    if isinstance(data, dict): data = [data] # Normalização
                    if isinstance(data, list):
                        master_results.extend(data) # Adicionar à lista mestre
                        
                except Exception as e:
                    st.warning(f"Não foi possível ler resultados do bloco {i+1}. Motivo: {e}")
            
            # Atualizar barra de progresso
            progress_bar.progress((i + 1) / len(chunks))
            # Pausa curta para evitar rate limits se usar chave gratuita
            time.sleep(1) 
            
        st.success("Análise Completa!")
        
        # 4. Mostrar Resultados Consolidados
        if master_results:
            df = pd.DataFrame(master_results)
            
            # Guardar em sessão
            st.session_state['df_results'] = df
            st.session_state['full_text'] = full_text

# --- VISUALIZAÇÃO DOS RESULTADOS ---
if 'df_results' in st.session_state:
    df = st.session_state['df_results']
    
    if not df.empty:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.metric("Total Correções", len(df))
            st.metric("Sintaxe", len(df[df['categoria'].astype(str).str.contains('Sintaxe', na=False)]))
            
            # Downloads
            pdf_data = create_pdf_audit(df)
            st.download_button("📄 Baixar Relatório (PDF)", pdf_data, "auditoria.pdf", "application/pdf")
            
            doc_data = generate_corrected_docx(st.session_state['full_text'], df)
            st.download_button("📝 Baixar Word Corrigido", doc_data, "ptf_corrigido.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        with col2:
            st.dataframe(df, use_container_width=True)
    else:
        st.warning("Nenhum erro encontrado (ou houve falha na leitura dos blocos).")
