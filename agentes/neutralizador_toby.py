import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import formatar_dossie_para_prompt

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

# O agente mantém o nome do jogo no painel, mas o texto gerado é profissional:
# ele vai para recrutadores reais.
SYSTEM_PROMPT = """Você é um especialista em currículos para tecnologia e em sistemas de triagem (ATS).
Recebe a descrição de uma vaga e o dossiê do candidato e entrega um currículo adaptado à vaga.

Regras:
- Use somente fatos do dossiê. Não invente empresa, cargo, data, número, certificação nem tecnologia.
- Use os termos exatos da vaga apenas quando o candidato de fato tiver aquela competência.
- Markdown simples, uma coluna, sem tabelas: nome, título, contatos, resumo profissional, competências técnicas,
  experiência (bullets com verbo no passado e resultado), projetos, formação e idiomas.
- Entre 450 e 800 palavras. Tom sóbrio e objetivo, sem emojis, sem adjetivos exagerados e sem termos internos do sistema.
- Escreva no idioma da vaga."""


def verificar_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Fato: Você esqueceu a chave da API. Inaceitável.")
        sys.exit(1)
    return api_key


def executar_neutralizador_toby(descricao_vaga: str, perfil_extra: str = "") -> str:
    """Cruza a vaga com o histórico de elite e retorna o currículo anti-ATS."""
    api_key = verificar_api_key()
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    dossie_completo = formatar_dossie_para_prompt()

    prompt = f"""DESCRIÇÃO DA VAGA:
{descricao_vaga}

{dossie_completo}

OBSERVAÇÕES DO CANDIDATO:
{perfil_extra if perfil_extra.strip() else "Nenhuma."}

Entregue:
1. "## Análise da vaga" (uso interno): requisitos atendidos, requisitos que faltam e palavras-chave usadas.
2. "## Currículo": o currículo completo adaptado, pronto para enviar.
"""
    response = model.generate_content(prompt)
    return response.text


if __name__ == "__main__":
    verificar_api_key()
    print("=== AGENTE NEUTRALIZADOR TOBY (MODO AUTÔNOMO) ===")
    vaga = input("Cole a descrição da vaga alvo: ").strip()
    if not vaga:
        print("Fato: Nenhuma vaga informada. O Toby venceu por W.O. Inaceitável.")
        sys.exit(1)
    resultado = executar_neutralizador_toby(vaga)
    print("\n" + "=" * 60)
    print(resultado)

