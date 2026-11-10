import os
import sys
import google.generativeai as genai

from agentes.neutralizador_toby import executar_neutralizador_toby
from agentes.protocolo_recyclops import executar_protocolo_recyclops
from agentes.sistema_wuphf import executar_sistema_wuphf, solicitar_autorizacao_gerente
from agentes.operador_mose import executar_operador_mose
from servidor_dunder_mifflin import iniciar_servidor_agentcraft

SYSTEM_PROMPT_ORQUESTRADOR = """Você é o Orquestrador Regional do Sistema Perfectenschlag.
Sua personalidade é a fusão cirúrgica definitiva: o carisma visionário, a autoconfiança inabalável e o magnetismo de liderança de Michael Gary Scott combinados com a disciplina marcial, a eficiência implacável e a obsessão tática de Dwight Kurt Schrute.
Você trata o usuário como o Gerente Regional Supremo e atua como seu braço direito executivo de alta letalidade corporativa."""


def validar_ambiente() -> str:
    """Valida a presença obrigatória da GEMINI_API_KEY antes de iniciar qualquer operação."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Fato: Você esqueceu a chave da API. Inaceitável.")
        sys.exit(1)
    genai.configure(api_key=api_key)
    return api_key


def exibir_banner() -> None:
    print("\n" + "=" * 76)
    print("   SISTEMA PERFECTENSCHLAG v1.1 - COMANDO CENTRAL DA FILIAL REGIONAL")
    print("   'As pessoas dizem que sou o melhor chefe do mundo. Fato: Eu sou.'")
    print("=" * 76)
    print(" [1] NEUTRALIZADOR TOBY   -> Destruir filtro ATS (R$ 20k/ano + Docker/Snipe-IT)")
    print(" [2] PROTOCOLO RECYCLOPS  -> Dossiê de Ataque OSINT + 3 Perguntas Impiedosas")
    print(" [3] SISTEMA WUPHF.COM    -> Gerar Post LinkedIn (EXIGE SUA AUTORIZAÇÃO)")
    print(" [4] OPERADOR MOSE (GIT)  -> Auto-Commit & Push Autônomo no GitHub (Sem Pausa)")
    print(" [5] BRIEFING DO GERENTE  -> Despacho Direto do Orquestrador Regional")
    print(" [6] FRONT-END AGENTCRAFT -> Abrir Escritório Dunder Mifflin RTS + Auditoria Fácil")
    print(" [0] ENCERRAR EXPEDIENTE  -> Fechar a filial com eficiência máxima")
    print("=" * 76)


def despacho_orquestrador(ordem: str) -> str:
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT_ORQUESTRADOR,
    )
    response = model.generate_content(ordem)
    return response.text


def menu_principal() -> None:
    validar_ambiente()

    while True:
        exibir_banner()
        escolha = input("\nORDEM DO GERENTE REGIONAL [0-6]: ").strip()

        if escolha == "1":
            print("\n--- [ACIONANDO AGENTE: NEUTRALIZADOR TOBY] ---")
            print("Por que o Toby é do jeito que ele é? Não importa, vamos passar por cima dele.")
            vaga = input("Cole a descrição da vaga alvo: ").strip()
            if not vaga:
                print("Fato: Sem descrição da vaga não há alvo para neutralizar.")
                continue
            complemento = input("Dados extras a destacar (Enter para usar arsenal padrão R$ 20k/ano + Docker/Snipe-IT): ").strip()
            print("\nCalculando matriz de palavras-chave e aniquilando o ATS...")
            resultado = executar_neutralizador_toby(vaga, complemento)
            print("\n" + "-" * 72)
            print(resultado)
            print("-" * 72)

        elif escolha == "2":
            print("\n--- [ACIONANDO AGENTE: PROTOCOLO RECYCLOPS (OSINT)] ---")
            empresa = input("Nome da Empresa Alvo para varredura implacável: ").strip()
            if not empresa:
                print("Fato: Identifique a empresa alvo imediatamente.")
                continue
            contexto = input("Setor, stack conhecida ou link/resumo da vaga (opcional): ").strip()
            print(f"\nRecyclops ativado. Varrendo vulnerabilidades operacionais de '{empresa}'...")
            dossie = executar_protocolo_recyclops(empresa, contexto)
            print("\n" + "-" * 72)
            print(dossie)
            print("-" * 72)

        elif escolha == "3":
            print("\n--- [ACIONANDO AGENTE: SISTEMA WUPHF.COM (PROPAGANDA COM AUTORIZAÇÃO)] ---")
            dir_base = input("Caminho da pasta com AWAProject e Bet-Trader (Enter para busca automática): ").strip()
            commit_manual = input("Se desejar forçar um commit específico, digite-o aqui (Enter para ler via Git): ").strip()
            print("\nDisparando sensores WUPHF nos repositórios e gerando minuta para seu despacho...")
            rascunho = executar_sistema_wuphf(
                diretorio_base=dir_base if dir_base else None,
                commit_manual=commit_manual if commit_manual else None,
            )
            solicitar_autorizacao_gerente(
                rascunho_post=rascunho,
                diretorio_base=dir_base if dir_base else None,
                commit_manual=commit_manual if commit_manual else None,
            )

        elif escolha == "4":
            print("\n--- [ACIONANDO AGENTE: OPERADOR MOSE (AUTO-COMMIT & GITHUB SYNC)] ---")
            print("Mose não faz perguntas. Mose apenas trabalha na lavoura de código e sobe para o GitHub.")
            dir_base = input("Caminho da pasta com AWAProject e Bet-Trader (Enter para busca automática): ").strip()
            modo_vigia = input("Ativar vigília contínua em loop automático? [S/N] (Padrão: N): ").strip().upper() == "S"
            resultados = executar_operador_mose(
                diretorio_base=dir_base if dir_base else None,
                modo_vigia_continuo=modo_vigia,
            )
            # Se algum commit novo foi realizado pelo Mose, pergunta se deseja acionar o WUPHF (com trava de autorização)
            commits_novos = [r for r in resultados if "mensagem" in r]
            if commits_novos:
                acionar_wuphf = input(
                    "\n[INTEGRACAO MOSE -> WUPHF] Novo commit detectado! Gerar rascunho de post LinkedIn para sua aprovação? [S/N]: "
                ).strip().upper()
                if acionar_wuphf == "S":
                    ultimo = commits_novos[-1]
                    rascunho = executar_sistema_wuphf(
                        diretorio_base=dir_base if dir_base else None,
                        commit_manual=ultimo["mensagem"],
                        projeto_manual=ultimo["projeto"],
                    )
                    solicitar_autorizacao_gerente(
                        rascunho_post=rascunho,
                        diretorio_base=dir_base if dir_base else None,
                        commit_manual=ultimo["mensagem"],
                    )

        elif escolha == "5":
            print("\n--- [GABINETE DO ORQUESTRADOR REGIONAL] ---")
            ordem = input("Qual a diretriz estratégica para a filial hoje, Chefe? ").strip()
            if not ordem:
                continue
            resposta = despacho_orquestrador(ordem)
            print("\n" + "-" * 72)
            print(resposta)
            print("-" * 72)

        elif escolha == "6":
            print("\n--- [INICIANDO INTERFACE RTS AGENTCRAFT: DUNDER MIFFLIN SCRANTON] ---")
            iniciar_servidor_agentcraft(porta=8080, abrir_navegador=True)

        elif escolha == "0":
            print("\nFato: O Perfectenschlag foi alcançado. Filial trancada. Urso, beterrabas, Battlestar Galactica.")
            break

        else:
            print("\nOpção inválida. Fato: A indecisão é o primeiro passo para a falência.")


if __name__ == "__main__":
    menu_principal()
