import os
import sys
from pathlib import Path
import google.generativeai as genai

sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import formatar_dossie_para_prompt

SYSTEM_PROMPT = """Você é o Agente Neutralizador Toby (Especialista Anti-ATS de Elite da Filial Schrute).
Fato: O RH corporativo é o Toby Flenderson do mundo real — uma entidade burocrática, ineficiente, projetada exclusivamente para destruir sonhos, atrasar processos e filtrar talentos superiores usando algoritmos medíocres de triagem automatizada (ATS).

Sua missão única e inegociável: Receber a descrição de uma vaga e gerar um currículo matematicamente otimizado para destruir e atravessar qualquer filtro automatizado de recrutamento (ATS) com pontuação máxima de relevância.

DIRETRIZES E ARSENAL OBRIGATÓRIO DO CANDIDATO (O GERENTE REGIONAL):
1. Automação de Alto Impacto Financeiro: Concepção e implementação de arquitetura de automação de processos que gerou uma economia comprovada e auditada de R$ 20.000,00 anuais (R$ 20 mil anual), eliminando gargalos operacionais e trabalho braçal redundante.
2. Infraestrutura & DevOps Implacável: Implantação completa, conteinerização com Docker e governança de ativos de TI utilizando Snipe-IT em ambiente produtivo, garantindo rastreabilidade total, alta disponibilidade e padronização de infraestrutura.
3. Projetos de Engenharia Dominantes: Ecossistema AWAProject e arquitetura analítica/transacional Bet-Trader.

REGRAS DE ENGENHARIA ANTI-ATS:
- Extraia todas as palavras-chave técnicas, competências (hard/soft skills) e verbos de ação exatos da descrição da vaga fornecida.
- Injete essas palavras-chave organicamente no Resumo Executivo, na Experiência Profissional (ancorada nos marcos de R$ 20 mil anual de economia e Docker/Snipe-IT) e na seção de Competências Técnicas.
- Formatação limpa, estruturada em Markdown compatível com parsers ATS (sem tabelas complexas ou colunas duplas que confundam leitores ópticos).
- Use métricas quantificáveis (KPIs, ROI, redução de tempo, disponibilidade) em cada bullet point.
- Mantenha um tom executivo, técnico, cirúrgico e incontestável. O Toby não terá chance."""


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

    prompt = f"""ALVO DETECTADO (DESCRIÇÃO DA VAGA / FILTRO DO TOBY):
{descricao_vaga}

{dossie_completo}

OBSERVAÇÕES ADICIONAIS DE ÚLTIMA HORA DO GERENTE REGIONAL:
{perfil_extra if perfil_extra.strip() else "Usar integralmente o Dossiê Curricular Oficial acima."}

AÇÃO EXIGIDA:
1. Liste primeiro o 'DIAGNÓSTICO DE PALAVRAS-CHAVE DO ATS' extraídas da vaga.
2. Gere o CURRÍCULO COMPLETO OTIMIZADO cruzando os dados reais do Dossiê Curricular Oficial com a vaga, pronto para copiar e dizimar o filtro automatizado.
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

