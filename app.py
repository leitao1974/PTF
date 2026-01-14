import streamlit as st
from pypdf import PdfWriter, PdfReader
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
import io
import os
import time
import tempfile
import re
from datetime import datetime

# ==========================================
# --- 1. CONFIGURAÇÃO VISUAL ---
# ==========================================

st.set_page_config(page_title="Auditor EIA Pro (Versão Consolidada)", page_icon="⚖️", layout="wide")

st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #0e4da4; color: white; }
    .stSuccess, .stInfo, .stWarning { border-left: 5px solid #0e4da4; }
</style>
""", unsafe_allow_html=True)

if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
def reset_app(): st.session_state.uploader_key += 1

# ==========================================
# --- 2. SUPER BASE DE DADOS LEGISLATIVA (BLINDADA) ---
# ==========================================

# A chave do dicionário inclui "na redação atual" para instruir a IA a considerar revisões.
COMMON_LAWS = {
    "RJAIA - Regime Jurídico AIA (DL 151-B/2013 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2013-116043164",
    "SIMPLEX AMBIENTAL (DL 11/2023 - Versão Consolidada)": "https://diariodarepublica.pt/dr/detalhe/decreto-lei/11-2023-207604364",
    "LUA - Licenciamento Único (DL 75/2015 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2015-106567543",
    "REDE NATURA 2000 (DL 140/99 com alterações do DL 49/2005)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/1999-34460975",
    "RGR - Regulamento Geral do Ruído (DL 9/2007 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2007-34526556",
    "LEI DA ÁGUA (Lei 58/2005 e DL 226-A/2007 consolidados)": "https://diariodarepublica.pt/dr/legislacao-consolidada/lei/2005-34563267",
    "RGGR - Regime Geral de Resíduos (DL 102-D/2020 atualizado)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2020-150917243",
    "RESPONSABILIDADE AMBIENTAL (DL 147/2008 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2008-34484567"
}

SPECIFIC_LAWS = {
    "1. Agricultura, Pecuária e Floresta": {
        "NREAP - Pecuária (DL 81/2013 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2013-34766868",
        "GESTÃO EFLUENTES PECUÁRIOS (Port. 631/2009 consolidada)": "https://diariodarepublica.pt/dr/detalhe/portaria/631-2009-518868",
        "SISTEMA DEFESA FLORESTA (DL 124/2006 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2006-34493356",
        "ARBORIZAÇÃO (DL 96/2013 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2013-116043321"
    },
    "2. Indústria Extrativa (Minas e Pedreiras)": {
        "BASES RECURSOS GEOLÓGICOS (Lei 54/2015 atualizada)": "https://diariodarepublica.pt/dr/legislacao-consolidada/lei/2015-107567789",
        "RESÍDUOS DE EXTRAÇÃO (DL 10/2010 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2010-34658745",
        "REVELAÇÃO E APROVEITAMENTO (DL 270/2001 atualizado)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2001-34449875"
    },
    "3. Energia (Renováveis, Linhas, H2)": {
        "SISTEMA ELÉTRICO (DL 15/2022 atualizado)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2022-177343687",
        "GASES RENOVÁVEIS/H2 (DL 62/2020 atualizado)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2020-141445587",
        "LINHAS ALTA TENSÃO (DL 25/2016)": "https://diariodarepublica.pt/dr/detalhe/decreto-lei/25-2016-106543210"
    },
    "4. Indústria e Química": {
        "SISTEMA INDÚSTRIA (SIR - DL 169/2012 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2012-34658112",
        "EMISSÕES INDUSTRIAIS (DL 127/2013 atualizado)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2013-34789569",
        "SEVESO III (DL 150/2015 atualizado)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2015-106558967"
    },
    "5. Infraestruturas e Transportes": {
        "ESTATUTO ESTRADAS (Lei 34/2015 atualizada)": "https://diariodarepublica.pt/dr/legislacao-consolidada/lei/2015-34585678",
        "SERVIDÕES AERONÁUTICAS (DL 48/2022)": "https://diariodarepublica.pt/dr/detalhe/decreto-lei/48-2022-185799345"
    },
    "6. Água, Saneamento e Hidráulica": {
        "UTILIZAÇÃO RECURSOS HÍDRICOS (DL 226-A/2007 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2007-34526567",
        "QUALIDADE ÁGUA CONSUMO (DL 306/2007 com alt. DL 69/2023)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2007-34512233",
        "SEGURANÇA BARRAGENS (DL 21/2018)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2018-114833256"
    },
    "7. Resíduos": {
        "RGGR (DL 102-D/2020 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2020-150917243",
        "ATERROS (DL 102-D/2020 Anexo II)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2020-150917243"
    },
    "8. Turismo e Urbanismo": {
        "RJUE (DL 555/99 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/1999-34563452",
        "RJET (DL 39/2008 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2008-34460567",
        "REN (DL 166/2008 na redação atual)": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2008-34512221"
    },
    "Outra Tipologia": {}
}

# ==========================================
# --- 3. LÓGICA DE PROCESSO (HÍBRIDA) ---
# ==========================================

def get_available_models(api_key):
    """Lista modelos disponíveis na API Google."""
    try:
        genai.configure(api_key=api_key)
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        return models
    except:
        return []

def extract_text_from_pdfs_local(files):
    """Lê PDFs de legislação extra localmente (não precisa de cloud)."""
    text = ""
    for f in files:
        try:
            reader = PdfReader(f)
            text += f"\n>>> INÍCIO DIPLOMA EXTRA: {f.name} <<<\n"
            for page in reader.pages:
                text += page.extract_text() + "\n"
            text += f">>> FIM DIPLOMA EXTRA: {f.name} <<<\n"
        except Exception as e:
            text += f"\n[ERRO LEITURA {f.name}: {str(e)}]\n"
    return text

def merge_pdfs_to_temp(uploaded_files):
    """Junta todos os ficheiros do processo num único PDF temporário."""
    merger = PdfWriter()
    for uploaded_file in uploaded_files:
        merger.append(uploaded_file)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        merger.write(tmp)
        tmp_path = tmp.name
    return tmp_path

def analyze_large_document(merged_pdf_path, laws_str, extra_laws_text, prompt_instructions, key, model_name):
    """
    Envia o Processo gigante via File API + Instruções e Leis via Texto.
    """
    genai.configure(api_key=key)
    status_msg = st.empty()
    status_msg.info("📤 A enviar processo EIA para a Google Cloud (File API)...")
    
    processo_file = None
    try:
        # 1. Upload do Ficheiro Grande
        processo_file = genai.upload_file(path=merged_pdf_path, display_name="Processo EIA Auditoria")
        
        # 2. Esperar processamento
        status_msg.info("⚙️ A Google está a processar o PDF...")
        while processo_file.state.name == "PROCESSING":
            time.sleep(2)
            processo_file = genai.get_file(processo_file.name)
        
        if processo_file.state.name == "FAILED":
            raise ValueError("A Google falhou a leitura do PDF do processo.")
        
        status_msg.success("✅ Processamento concluído. A iniciar análise jurídica...")

        # 3. Gerar Análise
        model = genai.GenerativeModel(model_name)
        
        full_prompt = [
            prompt_instructions,
            "\n=== QUADRO LEGISLATIVO GERAL (VERIFICAR CUMPRIMENTO) ===\n",
            laws_str,
            "\n=== LEGISLAÇÃO EXTRA CARREGADA PELO UTILIZADOR (TEXTO INTEGRAL) ===\n",
            extra_laws_text if extra_laws_text else "Nenhum diploma extra carregado.",
            "\n=== INSTRUÇÃO FINAL ===\n",
            "Analisa agora o ficheiro PDF em anexo (Processo EIA) face a esta legislação.",
            processo_file
        ]

        response = model.generate_content(full_prompt)
        status_msg.empty()
        return response.text

    except ResourceExhausted:
        return "🚨 ERRO DE COTA: Atingiste o limite da API da Google. Verifica o teu plano."
    except Exception as e:
        return f"❌ Erro Técnico: {str(e)}"
    finally:
        # Limpeza obrigatória para não pagar armazenamento
        if processo_file:
            try: genai.delete_file(processo_file.name)
            except: pass

# ==========================================
# --- 4. GERADOR DE WORD (PROFISSIONAL) ---
# ==========================================

def clean_markdown(text):
    return text.replace('**', '').strip()

def create_professional_doc(content, project_type, active_laws_dict, extra_files_names):
    doc = Document()
    
    # Estilos
    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Calibri'
    style_normal.font.size = Pt(11)
    
    # Título Principal
    title = doc.add_heading('AUDITORIA DE CONFORMIDADE EIA', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f'Setor: {project_type}').alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f'Data: {datetime.now().strftime("%d/%m/%Y")}').alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph('---')

    # Conteúdo da Análise
    for line in content.split('\n'):
        line = line.strip()
        if not line: continue
        
        if line.startswith('## '):
            clean = clean_markdown(line.replace('## ', ''))
            h = doc.add_heading(clean.upper(), level=1)
            h.style.font.color.rgb = RGBColor(14, 77, 164) # Azul Institucional
        elif line.startswith('### '):
            clean = clean_markdown(line.replace('### ', ''))
            doc.add_heading(clean, level=2)
        elif line.startswith('- ') or line.startswith('* '):
            p = doc.add_paragraph(line[2:], style='List Bullet')
        else:
            doc.add_paragraph(line)

    # Anexo Legislativo
    doc.add_page_break()
    doc.add_heading('ANEXO: QUADRO LEGISLATIVO REFERENCIADO', level=1)
    
    doc.add_paragraph("1. Legislação Base e Setorial:", style='Heading 2')
    for name, url in active_laws_dict.items():
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(name).bold = True
        if url.startswith("http"):
            p.add_run(f" (Consultar DRE)").italic = True
    
    if extra_files_names:
        doc.add_paragraph("2. Legislação Extra Específica (PDFs Analisados):", style='Heading 2')
        for f_name in extra_files_names:
            doc.add_paragraph(f_name, style='List Bullet')

    bio = io.BytesIO()
    doc.save(bio)
    return bio

# ==========================================
# --- 5. INTERFACE DO UTILIZADOR ---
# ==========================================

with st.sidebar:
    st.header("1. Configuração")
    # --- AUTO-CONFIG ---
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        api_key = st.text_input("Chave API Google", type="password")
    # ------------------
    
    model_name = ""
    if api_key:
        models = get_available_models(api_key)
        if models:
            ix = 0
            # Prioridade ao modelo Flash (rápido e barato para docs grandes)
            for i, m in enumerate(models):
                if 'flash' in m: ix = i; break
            model_name = st.selectbox("Modelo IA", models, index=ix)
    
    st.markdown("---")
    st.header("2. Tipologia do Projeto")
    project_type = st.selectbox("Setor RJAIA:", list(SPECIFIC_LAWS.keys()) + ["Outra Tipologia"])
    
    # Construção Dinâmica da Lista de Leis
    active_laws = COMMON_LAWS.copy()
    if project_type in SPECIFIC_LAWS:
        active_laws.update(SPECIFIC_LAWS[project_type])
    
    with st.expander(f"📚 Base Legislativa ({len(active_laws)} Diplomas)"):
        for k, v in active_laws.items():
            st.markdown(f"[{k}]({v})")
            
    st.markdown("---")
    st.header("3. Legislação Extra")
    st.caption("Carregue PDMs, Regulamentos Municipais ou Leis Recentes (últimos 6 meses).")
    extra_laws_files = st.file_uploader("Upload PDFs Extra", type=['pdf'], accept_multiple_files=True)

st.title("⚖️ Auditor EIA Pro")
st.markdown("Auditoria de conformidade EIA com base no RJAIA atualizado e Simplex Ambiental.")

st.info("ℹ️ Carregue todos os volumes do processo (Tomo I, RNT, Anexos). O sistema suporta ficheiros grandes (até 2GB via File API).")

uploaded_files = st.file_uploader(
    "📂 Carregar Processo EIA Completo", 
    type=['pdf'], 
    accept_multiple_files=True,
    key=f"uploader_{st.session_state.uploader_key}"
)

# --- INSTRUÇÕES ESTRUTURADAS (7 CAPÍTULOS + OPINIÃO TÉCNICA) ---
instructions = f"""
Atua como Perito Sénior em Engenharia do Ambiente e Jurista.
Auditoria de conformidade rigorosa ao EIA do setor: {project_type}.

CONTEXTO LEGISLATIVO:
1. Verifica a conformidade com a 'Legislação Base' listada (considerando sempre a REDAÇÃO ATUAL/CONSOLIDADA).
2. Verifica a conformidade com a 'Legislação Extra' fornecida (se houver).

ESTRUTURA OBRIGATÓRIA DO RELATÓRIO (Usa Markdown ##):

## 1. ENQUADRAMENTO LEGAL E CONFORMIDADE
   - O projeto enquadra-se corretamente no RJAIA (Anexo I ou II)?
   - Verifica se o DL 11/2023 (Simplex Ambiental) foi respeitado.
   - Verifica ponto a ponto o cumprimento da legislação listada.
   - Identifica falhas administrativas (ex: falta de peças desenhadas, cronogramas, dados desatualizados).

## 2. PRINCIPAIS IMPACTES (Técnico)
   - Análise detalhada por descritor ambiental (Ar, Água, Ruído, Biodiversidade, etc.).
   - Foca nos impactes negativos significativos não mitigados.

## 3. MEDIDAS DE MITIGAÇÃO PROPOSTAS
   - Lista as medidas apresentadas no EIA (Fase Construção e Exploração).

## 4. ANÁLISE CRÍTICA E BENCHMARKING
   - Comparação: As medidas propostas são suficientes face às Melhores Técnicas Disponíveis (MTD) para o setor {project_type}?
   - Existem lacunas legais ou omissões graves face às boas práticas?

## 5. FUNDAMENTAÇÃO
   - Lista de evidências.
   - OBRIGATÓRIO: Indica EXPLICITAMENTE a página do PDF onde encontraste a informação (ex: "Ref: Pág. 45 do Tomo I").

## 6. CITAÇÕES RELEVANTES
   - Transcreve trechos curtos do EIA que evidenciem os problemas ou compromissos assumidos.

## 7. CONCLUSÕES E OPINIÃO TÉCNICA
   - Não emitir "Parecer Favorável/Desfavorável" administrativo.
   - Formular uma OPINIÃO TÉCNICA sobre a robustez do estudo.
   - O estudo permite uma decisão informada? Faltam elementos essenciais (Aditamentos)?
   - Resumo das principais desconformidades detetadas.

Tom: Formal, Técnico, Crítico e Construtivo.
"""

if st.button("🚀 INICIAR AUDITORIA", type="primary"):
    if not api_key or not model_name: st.error("⚠️ Configura a API Key na barra lateral.")
    elif not uploaded_files: st.warning("⚠️ Carrega os ficheiros do Processo EIA.")
    else:
        with st.spinner("A processar legislação e a analisar o processo..."):
            
            # 1. Preparar Base Legal (Apenas Nomes para a IA, ela conhece o conteúdo)
            laws_str = "\n".join([f"- {k}" for k in active_laws.keys()])
            
            # 2. Extrair Texto das Leis Extras (Localmente)
            extra_text = ""
            extra_names = []
            if extra_laws_files:
                extra_text = extract_text_from_pdfs_local(extra_laws_files)
                extra_names = [f.name for f in extra_laws_files]
            
            # 3. Preparar Processo (Merge + Upload Cloud)
            temp_path = merge_pdfs_to_temp(uploaded_files)
            
            result_text = analyze_large_document(
                temp_path, 
                laws_str, 
                extra_text, 
                instructions, 
                api_key, 
                model_name
            )
            
            # Limpeza do ficheiro temporário local
            try: os.remove(temp_path)
            except: pass
            
            if "🚨" in result_text or "❌" in result_text:
                st.error(result_text)
            else:
                st.success("Auditoria Concluída!")
                
                with st.expander("📄 Ver Relatório", expanded=True):
                    st.markdown(result_text)
                
                docx = create_professional_doc(result_text, project_type, active_laws, extra_names)
                
                st.download_button(
                    label="⬇️ Download Relatório Word Oficial",
                    data=docx.getvalue(),
                    file_name="Auditoria_EIA_Parecer.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    on_click=reset_app
                )
