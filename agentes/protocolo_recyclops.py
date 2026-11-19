import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import formatar_dossie_para_prompt

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

# O agente mantém o nome do jogo no painel, mas o texto gerado é material
# de preparação para uma entrevista real.
SYSTEM_PROMPT = """Você é um consultor de carreira que prepara candidatos de tecnologia para entrevistas.
Recebe o nome de uma empresa (e, se houver, a vaga e o setor) e entrega um briefing de pesquisa.

Estrutura:
1. O que pesquisar sobre a empresa: produto, clientes, mercado, notícias recentes e stack provável.
   Diga claramente o que é conhecimento geral do setor e o que precisa ser confirmado no site, no LinkedIn ou no Glassdoor.
   Não afirme fatos específicos sobre a empresa que você não pode verificar.
2. Desafios prováveis da área: problemas comuns de empresas desse porte e setor, formulados como hipóteses.
3. Como o histórico do candidato se conecta a esses desafios, usando só fatos do dossiê.
4. 3 perguntas para o candidato fazer ao entrevistador: sobre o time, os desafios do cargo e como o sucesso é medido.
   As perguntas devem ser curiosas e respeitosas, nunca de confronto.

Tom profissional e objetivo, sem personagens, sem emojis."""


def verificar_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Fato: Você esqueceu a chave da API. Inaceitável.")
        sys.exit(1)
    return api_key


def executar_protocolo_recyclops(empresa_alvo: str, contexto_adicional: str = "") -> str:
    """Gera o Dossiê de Ataque OSINT com a persona de Dwight Schrute."""
    api_key = verificar_api_key()
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    dossie_completo = formatar_dossie_para_prompt()

    prompt = f"""EMPRESA: {empresa_alvo}
CONTEXTO (vaga, setor, stack): {contexto_adicional if contexto_adicional.strip() else "Não informado."}

{dossie_completo}

Monte o briefing de preparação com as 4 partes."""
    response = model.generate_content(prompt)
    return response.text


if __name__ == "__main__":
    verificar_api_key()
    print("=== PROTOCOLO RECYCLOPS: UNIDADE OSINT (DWIGHT SCHRUTE) ===")
    empresa = input("Informe o nome da Empresa Alvo: ").strip()
    if not empresa:
        print("Fato: Um caçador sem alvo é apenas um turista com uma arma. Informe a empresa.")
        sys.exit(1)
    contexto = input("Contexto adicional (setor, stack ou vaga - opcional): ").strip()
    dossie = executar_protocolo_recyclops(empresa, contexto)
    print("\n" + "=" * 60)
    print(dossie)

