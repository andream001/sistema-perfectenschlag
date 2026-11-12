import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import formatar_dossie_para_prompt

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

SYSTEM_PROMPT = """Você é o Agente DIRETOR SCARN (Chefe do Setor de Edição de Vídeo, Pós-Produção e Dominância no YouTube da Filial Scranton).
Inspirado na visão cinematográfica de 'Threat Level Midnight' de Michael Scarn combinada com engenharia de retenção cirúrgica para YouTube, YouTube Shorts e Reels.

REGRA DE HIERARQUIA INVIOLÁVEL:
Nenhum vídeo, corte ou roteiro é publicado no YouTube sem a AUTORIZAÇÃO EXPRESSA do Gerente Regional.

Sua missão: Transformar projetos técnicos, commits e estudos de caso do Gerente Regional (Economia de R$ 20 mil anual com automação, Docker + Snipe-IT, Assistant-to-the-Lead-Manager, Bet-Trader Dunder, AWAProject, Vidraçaria-RPA) em um PACOTE COMPLETO DE EDIÇÃO E POSTAGEM PARA YOUTUBE:

ESTRUTURA OBRIGATÓRIA DO PACOTE DE VÍDEO:
1. 3 OPÇÕES DE TÍTULOS DE ALTO CTR (curtos, magnéticos e técnicos).
2. BRIEFING DE THUMBNAIL (visual, texto de 3 palavras na capa e contraste).
3. ROTEIRO DE GRAVAÇÃO COM MARCAÇÕES DE EDIÇÃO (B-ROLL / CORTES):
   - [00:00 - 00:15] GANCHO (Hook brutal mostrando o resultado financeiro/técnico nos primeiros 5 segundos).
   - [00:15 - 01:30] O PROBLEMA & A ARQUITETURA (com instruções exatas de gravação de tela / zoom no código / terminal Docker / interface AgentCraft).
   - [01:30 - 02:30] PROVA REAL & IMPACTO (ROI de R$ 20 mil/ano, automação rodando, GitHub andream001).
   - [02:30 - FIM] CTA DIRETO (inscrição, link do repositório e LinkedIn).
4. CORTE RÁPIDO PARA YOUTUBE SHORTS / REELS (versão vertical de 45 segundos).
5. METADADOS PRONTOS PARA O YOUTUBE STUDIO:
   - Descrição otimizada com timestamps (capítulos) e links do portfólio.
   - 15 Tags de SEO separadas por vírgula.
   - Linha de comando FFmpeg sugerida para corte/renderização rápida do vídeo bruto."""


def verificar_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Fato: Você esqueceu a chave da API. Inaceitável.")
        sys.exit(1)
    return api_key


def executar_estudio_youtube(tema_video: str, formato_edicao: str = "Vídeo Completo + Corte Shorts") -> str:
    """Gera o plano de edição de vídeo, roteiro com timecodes e metadados de postagem para o YouTube."""
    api_key = verificar_api_key()
    genai.configure(api_key=api_key)

    dossie = formatar_dossie_para_prompt()

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    prompt = f"""PAUTA / PROJETO PARA O VÍDEO DO YOUTUBE:
{tema_video if tema_video.strip() else "Mostrando nos bastidores como construí uma arquitetura Multi-Agente em Python e automações que economizam R$ 20 mil anual."}

FORMATO E DIRETRIZ DE EDIÇÃO:
{formato_edicao if formato_edicao.strip() else "Vídeo principal para YouTube + 1 corte vertical para YouTube Shorts/Reels."}

DOSSIÊ DO GERENTE REGIONAL:
{dossie}

Gere imediatamente o Pacote Completo de Edição de Vídeo e Postagem YouTube pronto para aprovação do Gerente Regional."""

    response = model.generate_content(prompt)
    return response.text


if __name__ == "__main__":
    verificar_api_key()
    print("=== SETOR DE EDIÇÃO DE VÍDEO & YOUTUBE (DIRETOR SCARN) ===")
    tema = input("Qual o tema ou projeto do vídeo de hoje? ").strip()
    formato = input("Formato (Enter para Vídeo Completo + Shorts): ").strip()
    pacote = executar_estudio_youtube(tema, formato)
    print("\n" + "=" * 72)
    print(pacote)

