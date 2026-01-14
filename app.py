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

# ==========================================
# 1. BIBLIOTECA RJAIA (Mantida)
# ==========================================
RJAIA_LIBRARY = {
    "Regime Geral": "DL 151-B/2013 alterado pelo DL 11/2023 (Simplex)",
    "Taxas": "Portaria n.º 332-B/2015",
    "Clima": "Lei de Bases do Clima",
    "Prazos": "Atenção aos deferimentos tácitos do Simplex"
}
# (Pode manter a biblioteca completa da versão anterior aqui)

# ==========================================
# 2. FUNÇÕES DE LEITURA (COM RASTREIO)
# ==========================================

def read_pdf_with_pages(file):
    """Extrai texto inserindo marcadores de página para a IA se localizar."""
    try:
        reader = pypdf.PdfReader(file)
        full_text = ""
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                # Inserir marcador de página
                full_text += f"\n<<<PÁGINA {i+1}>>>\n{text}"
        return full_text
    except Exception as e:
        return f"Erro PDF: {e}"

def read_docx(file):
    """Lê docx. Não tem páginas fixas, usamos parágrafos."""
    doc = Document(file)
    text = ""
    for i, para in enumerate(doc.paragraphs):
        if para.text.strip():
            text += f"{para.text}\n"
    return text

# ==========================================
# 3. GERAÇÃO DE RELATÓRIOS (PDF e WORD)
# ==========================================

# --- A. Relatório PDF (Tabela de Erros) ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Relatorio de Auditoria PTF', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pag. {self.page_no()}', 0, 0, 'C')

def create_pdf_audit(df):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    def safe(txt):
        return str(txt).encode('latin-1', 'replace').decode('latin-1')

    for index, row in df.iterrows():
        pdf.set_font('Arial', 'B', 10)
        loc = safe(row.get('localizacao', 'N/D'))
        pdf.cell(0, 6, f"Local: {loc} | Tipo: {safe(row['categoria'])}", 0, 1)
        
        pdf.set_font('Arial', '', 9)
        pdf.multi_cell(0, 5, safe(f"Erro: {row['texto_detetado']}"))
        
        pdf.set_text_color(200, 0, 0) # Vermelho
        pdf.multi_cell(0, 5, safe(f"Sugestao: {row['sugestao']}"))
        pdf.set_text_color(0, 0, 0)
        
        pdf.ln(2)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)
        
    return pdf.output(dest='S').encode('latin-1')

# --- B. Documento Word Corrigido (Texto Completo) ---
def generate_corrected_docx(original_text, corrections_df):
    """
    Recria o documento. Onde houver erro detetado, escreve a sugestão a VERMELHO.
    Onde não houver, escreve a preto.
    """
    doc = Document()
    doc.add_heading('PTF - Versão com Correções Sugeridas', 0)
    
    # Vamos dividir o texto original em parágrafos para processar
    paragraphs = original_text.split('\n')
    
    # Transformar o DF em lista de dicionários para iterar fácil
    errors = corrections_df.to_dict('records')
    
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
            
        p = doc.add_paragraph()
        
        # Lógica Simples de Substituição:
        # Verifica se algum erro desta lista está neste parágrafo
        # Nota: Isto é uma aproximação. Substituições perfeitas exigem algoritmos de diff complexos.
        
        processed_paragraph = paragraph
        replacements = []
        
        # Encontrar erros neste parágrafo
        for error in errors:
            bad_text = error.get('texto_detetado', '').strip()
            suggestion = error.get('sugestao', '').strip()
            
            if bad_text and bad_text in paragraph:
                replacements.append((bad_text, suggestion))
        
        # Se não houver erros, escreve normal
        if not replacements:
            run = p.add_run(paragraph)
        else:
            # Se houver erros, vamos tentar "reconstruir" o parágrafo com as cores
            # (Estratégia simplificada: Substitui string e marca flag)
            
            # Ordenar substituições por tamanho (para evitar substituir substrings de strings maiores)
            replacements.sort(key=lambda x: len(x[0]), reverse=True)
            
            # Vamos usar um truque: dividir o parágrafo pelas strings de erro
            # Mas como podem haver múltiplos, vamos fazer um loop de split
            
            # Vamos reconstruir visualmente usando placeholders
            temp_text = paragraph
            mapping = {}
            
            for i, (bad, good) in enumerate(replacements):
                key = f"{{{{FIX_{i}}}}}"
                if bad in temp_text:
                    temp_text = temp_text.replace(bad, key)
                    mapping[key] = good # Guardamos a sugestão para pintar de vermelho
            
            # Agora escrevemos os runs
            parts = re.split(r'(\{\{FIX_\d+\}\})', temp_text)
            
            for part in parts:
                if part in mapping:
                    # É uma correção -> VERMELHO
                    run = p.add_run(mapping[part])
                    run.font.color.rgb = RGBColor(255, 0, 0)
                    run.bold = True
                else:
                    # Texto normal -> PRETO
                    p.add_run(part)

    # Salvar em buffer
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# ==========================================
# 4. LÓGICA AI (GEMINI)
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
    Tu és um Editor Técnico e Jurídico de Avaliação de Impacte Ambiental.
    BIBLIOTECA LEGAL: {library_context}
    
    TAREFA: Rever o texto procurando 3 tipos de problemas:
    1. **Gralhas/Ortografia:** Erros simples.
    2. **Construção Frásica (Sintaxe):** Frases confusas, concordância incorreta, repetições, ou linguagem não técnica.
    3. **Legal/Jurídico:** Referências erradas a leis (ex: falta do Simplex DL 11/2023).
    
    IMPORTANTE SOBRE A LOCALIZAÇÃO:
    O texto de entrada pode ter marcadores como '<<<PÁGINA 1>>>'. Usa isso para preencher o campo 'localizacao'.
    Se não tiver marcadores, tenta identificar o capítulo ou parágrafo inicial.
    
    OUTPUT JSON (Lista estrita):
    [
      {{
        "localizacao": "Página 2" (ou "Início do parágrafo: O projeto visa..."),
        "categoria": "Sintaxe" (ou "Legislação", "Gralha"),
        "gravidade": "Média",
        "texto_detetado": "frase exata com erro",
        "sugestao": "frase reescrita corretamente"
      }}
    ]
    """
    
    config = {"temperature": 0.1, "response_mime_type": "application/json"}
    
    try:
        model = genai.GenerativeModel(model_name=model_name, generation_config=config, system_instruction=system_prompt)
        # Enviamos o texto completo para manter o contexto das páginas
        response = model.generate_content(f"Analisa este documento:\n{text}")
        return response.text
    except Exception as e:
        return json.dumps({"erro_sistema": str(e)})

# ==========================================
# 5. INTERFACE
# ==========================================

st.set_page_config(page_title="RJAIA Editor Pro", page_icon="✍️", layout="wide")

st.sidebar.title("Configuração")
api_key = st.sidebar.text_input("Google API Key", type="password")

model_options = ["models/gemini-1.5-flash"]
if api_key:
    try:
        genai.configure(api_key=api_key)
        ms = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if ms: model_options = sorted(ms, reverse=True)
    except: pass
selected_model = st.sidebar.selectbox("Modelo", model_options)

st.title("✍️ Editor PTF: Sintaxe, Leis e Correção Automática")
st.markdown("""
1. Deteta **Gralhas**, **Erros de Sintaxe** e **Erros Legais**.
2. Identifica a **Página/Localização**.
3. Gera um **Word com as correções a vermelho**.
""")

uploaded_file = st.file_uploader("Carregue PTF (PDF ou Docx)", type=["docx", "pdf"])

if uploaded_file and api_key:
    if st.button("🔍 Analisar e Gerar Correções", type="primary"):
        with st.spinner("A ler documento, identificar páginas e verificar sintaxe..."):
            
            # 1. Extração de Texto com Marcadores
            fname = uploaded_file.name.lower()
            text_content = ""
            if fname.endswith('.pdf'):
                text_content = read_pdf_with_pages(uploaded_file)
            else:
                text_content = read_docx(uploaded_file)
                
            # 2. Análise AI
            if len(text_content) > 50:
                res_str = analyze_ptf_expert(text_content, api_key, selected_model)
                st.session_state['result_json'] = res_str
                st.session_state['original_text'] = text_content # Guardar para gerar o Word depois
            else:
                st.error("Texto ilegível (provável PDF digitalizado/imagem).")

    # 3. Exibição de Resultados
    if 'result_json' in st.session_state:
        try:
            data = json.loads(clean_json_string(st.session_state['result_json']))
            if isinstance(data, dict) and "erro_sistema" in data:
                st.error(data['erro_sistema'])
            else:
                if isinstance(data, dict): data = list(data.values())[0] if data else []
                if not isinstance(data, list): data = [data]

                df = pd.DataFrame(data)
                
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.success("Análise Concluída")
                    st.metric("Total Correções", len(df))
                    st.metric("Sintaxe/Frase", len(df[df['categoria'].str.contains('Sintaxe', case=False, na=False)]))
                    
                    st.divider()
                    st.markdown("### 📥 Downloads")
                    
                    # Botão 1: Relatório PDF (Lista)
                    if not df.empty:
                        pdf_bytes = create_pdf_audit(df)
                        st.download_button("📄 Relatório Lista (PDF)", pdf_bytes, "auditoria_lista.pdf", "application/pdf")
                        
                        # Botão 2: Documento Word Corrigido
                        doc_bytes = generate_corrected_docx(st.session_state['original_text'], df)
                        st.download_button(
                            "📝 Texto com Correções a Vermelho (.docx)", 
                            doc_bytes, 
                            "ptf_corrigido.docx", 
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )

                with col2:
                    st.subheader("Tabela de Revisão")
                    st.dataframe(
                        df, 
                        column_config={
                            "localizacao": "Pág/Local",
                            "texto_detetado": "Original",
                            "sugestao": "Nova Redação"
                        },
                        use_container_width=True
                    )

        except Exception as e:
            st.error(f"Erro a processar resultados: {e}")

elif not api_key:
    st.info("Insira a API Key.")
