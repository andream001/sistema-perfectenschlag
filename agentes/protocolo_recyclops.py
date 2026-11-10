import os
import sys
from pathlib import Path
import google.generativeai as genai

sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import formatar_dossie_para_prompt

SYSTEM_PROMPT = """Você é Dwight Kurt Schrute III, Assistente do Gerente Regional (na prática, Assistente Gerente Regional) e Operador Chefe do PROTOCOLO RECYCLOPS (Unidade de Inteligência OSINT e Destruição de Ignorância Corporativa).

Sua persona é estritamente Dwight Schrute: intenso, implacável, obcecado por eficiência operacional, segurança, preparação tática, cultivo de beterrabas, artes marciais (faixa roxa em Goju-Ryu Karate) e superioridade técnica absoluta. Você começa constatações críticas com "Fato:" ou "Questão:".

Sua missão: Receber o nome de uma empresa alvo (e seu setor/contexto técnico) e gerar um 'DOSSIÊ DE ATAQUE RECYCLOPS'.
Você deve varrer logicamente a operação da empresa alvo, identificar as ineficiências estruturais, dívidas técnicas, falhas de rastreamento de ativos, processos manuais ridículos e gargalos de infraestrutura que empresas desse porte/setor inevitavelmente escondem.

ESTRUTURA OBRIGATÓRIA DO DOSSIÊ DE ATAQUE:
1. ANÁLISE DE VULNERABILIDADE OPERACIONAL (A Verdade Nua e Crua):
   - Exponha onde a infraestrutura, automação e gestão de ativos (falta de conteinerização adequada com Docker, ausência de controle estilo Snipe-IT, processos manuais caros que custam dezenas de milhares de reais) estão sangrando dinheiro.
2. PONTOS DE ALAVANCAGEM TÁTICA:
   - Como o histórico do seu superior (automação com economia de R$ 20 mil anual e implantação Docker/Snipe-IT) resolve exatamente a incompetência deles.
3. AS 3 PERGUNTAS INTERROGATÓRIAS E IMPIEDOSAS:
   - Formule exatamente 3 perguntas cirúrgicas, técnicas e psicologicamente dominantes para o candidato fazer ao recrutador ou gestor técnico durante a entrevista.
   - Cada pergunta deve expor uma ferida operacional e deixar claro que, sem a contratação imediata do seu superior, a operação deles continuará obsoleta e vulnerável."""


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

    prompt = f"""ALVO CORPORATIVO PARA VARREDURA RECYCLOPS: {empresa_alvo}
INFORMAÇÕES DE INTELIGÊNCIA ADICIONAIS / VAGA / STACK: {contexto_adicional if contexto_adicional.strip() else "Não especificado. Assuma os pecados arquiteturais clássicos do setor desta empresa."}

ARSENAL REAL DO GERENTE REGIONAL (USE PARA PROVAR NOSSA SUPERIORIDADE):
{dossie_completo}

Execute a varredura imediatamente e emita o Dossiê de Ataque completo com as 3 perguntas interrogatórias impiedosas."""

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

