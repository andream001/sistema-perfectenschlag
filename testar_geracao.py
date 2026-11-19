"""
Teste rápido da geração de candidatura com a sua chave do Gemini e o seu perfil real.
Não envia nada: só gera, checa a qualidade e salva o currículo em .docx para você abrir.

Uso:
    python testar_geracao.py
    python testar_geracao.py "Cargo — Empresa" "link-ou-email" arquivo_com_a_descricao.txt
"""
import sys
from pathlib import Path

from base_conhecimento import carregar_perfil_gerente, pendencias_perfil
from agentes.curriculo_profissional import gerar_docx_bytes, nome_arquivo_cv
from agentes.esteira_golden_ticket import carregar_candidaturas, criar_pacote_candidatura, salvar_candidaturas

VAGA_EXEMPLO = (
    "Engenheiro de Automação Python — Empresa Exemplo",
    "vagas@exemplo.com.br",
    "Buscamos pessoa engenheira de automação com Python, Docker, APIs REST e Git. "
    "Diferencial: experiência com RPA e gestão de ativos de TI. Envie o currículo em PDF com o assunto "
    "\"Automação Python\". Informe a pretensão salarial. 100% remoto, PJ.",
)


def main() -> None:
    if len(sys.argv) >= 4:
        cargo, canal = sys.argv[1], sys.argv[2]
        descricao = Path(sys.argv[3]).read_text(encoding="utf-8")
    else:
        cargo, canal, descricao = VAGA_EXEMPLO

    pend = pendencias_perfil()
    print("Pendências do perfil:", "nenhuma" if not pend else "")
    for p in pend:
        print("  -", p)

    c = criar_pacote_candidatura(cargo, canal, descricao, "Teste local — não enviar")
    f, q = c["formato_candidatura"], c["qualidade"]
    print("\nIA usada:", "sim" if c["gerado_por_ia"] else "NÃO (plano B, montado do perfil)")
    print("Canal:", f["plataforma"], "| envio automático:", f["envio_automatico_permitido"], "| idioma:", f["idioma_curriculo"])
    print("Pronto para envio:", q["pronto_para_envio"])
    for b in q["bloqueios"]:
        print("  BLOQUEIA:", b)
    for a in q["avisos"]:
        print("  aviso:", a)

    perfil = carregar_perfil_gerente()
    destino = Path(f"TESTE-{nome_arquivo_cv(perfil)}")
    destino.write_bytes(gerar_docx_bytes(c["curriculo_moldado"], "Teste"))
    print(f"\nCurrículo salvo em {destino.resolve()}")
    print("\n--- MENSAGEM ---\n" + (c.get("mensagem_apresentacao") or "(vazia)"))
    print("\n--- DIAGNÓSTICO (interno) ---\n" + c.get("diagnostico", ""))

    # Remove a candidatura de teste da esteira
    salvar_candidaturas([x for x in carregar_candidaturas() if x.get("id") != c["id"]])


if __name__ == "__main__":
    main()
