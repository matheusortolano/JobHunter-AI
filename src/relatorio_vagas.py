"""Relatório local de vagas já analisadas, sem chamadas de IA ou envio de e-mail."""

import argparse
import json
import os
import webbrowser
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from database import conectar_banco


RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_RELATORIO = RAIZ / "data" / "reports" / "relatorio_vagas.html"


def texto(valor):
    if valor is None or valor == "":
        return "Não informado"
    return str(valor)


def seguro(valor):
    return escape(texto(valor), quote=True)


def link_publico(valor):
    """Aceita somente URLs HTTP(S), sem caracteres de controle."""
    if not isinstance(valor, str) or not valor:
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in valor):
        return None
    try:
        partes = urlsplit(valor)
        if partes.scheme.lower() not in ("http", "https") or not partes.hostname:
            return None
        if partes.username is not None or partes.password is not None:
            return None
    except ValueError:
        return None
    return valor


def ler_lista_json(valor):
    if not valor:
        return []
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except (ValueError, TypeError):
            return []
    if not isinstance(valor, list):
        return []
    return [item for item in valor if isinstance(item, str) and item.strip()]


def buscar_vagas(limite=10, dias=30):
    """Consulta somente análises concluídas e recentes; não altera o banco."""
    if not 1 <= limite <= 50 or not 1 <= dias <= 365:
        raise ValueError("Use limite de 1 a 50 e período de 1 a 365 dias.")

    conexao = conectar_banco()
    cursor = None
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, titulo, empresa, localizacao, url, score,
                   score_ia, recomendacao_ia, pontos_fortes_ia,
                   gaps_ia, justificativa_ia, data_analise_ia,
                   status_candidatura
            FROM vagas
            WHERE analisada_ia = TRUE
              AND score_ia IS NOT NULL
              AND recomendacao_ia IN ('CANDIDATAR', 'AVALIAR')
              AND data_analise_ia >= %s
            ORDER BY score_ia DESC, data_analise_ia DESC
            LIMIT %s
            """,
            (datetime.now() - timedelta(days=dias), limite),
        )
        return cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        conexao.close()


def lista_html(itens):
    if not itens:
        return '<p class="muted">Nenhuma informação registrada.</p>'
    return "<ul>" + "".join(f"<li>{seguro(item)}</li>" for item in itens) + "</ul>"


def cartao_vaga(vaga):
    fortes = ler_lista_json(vaga.get("pontos_fortes_ia"))
    gaps = ler_lista_json(vaga.get("gaps_ia"))
    url = link_publico(vaga.get("url"))
    link = (
        f'<a class="botao" href="{escape(url, quote=True)}" '
        'target="_blank" rel="noopener noreferrer">Abrir vaga ↗</a>'
        if url else '<span class="muted">Link não disponível</span>'
    )
    data = vaga.get("data_analise_ia")
    data_formatada = data.strftime("%d/%m/%Y %H:%M") if isinstance(data, datetime) else texto(data)
    recomendacao = texto(vaga.get("recomendacao_ia"))
    classe = "candidatar" if recomendacao == "CANDIDATAR" else "avaliar"

    return f"""
    <article class="card">
      <div class="topo">
        <div>
          <span class="badge {classe}">{seguro(recomendacao)}</span>
          <h2>{seguro(vaga.get('titulo'))}</h2>
          <p class="empresa">{seguro(vaga.get('empresa'))}</p>
          <p class="muted">{seguro(vaga.get('localizacao'))}</p>
        </div>
        <div class="score"><strong>{seguro(vaga.get('score_ia'))}</strong><span>/100<br>Score IA</span></div>
      </div>
      <p class="meta">Algoritmo: {seguro(vaga.get('score'))}/100 · Analisada em {seguro(data_formatada)} · Candidatura: {seguro(vaga.get('status_candidatura'))}</p>
      <h3>Por que vale avaliar?</h3>
      <p>{seguro(vaga.get('justificativa_ia'))}</p>
      <div class="colunas">
        <div><h3>Pontos fortes</h3>{lista_html(fortes)}</div>
        <div><h3>Gaps e pontos a confirmar</h3>{lista_html(gaps)}</div>
      </div>
      {link}
    </article>"""


def montar_html(vagas, dias=30):
    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    conteudo = "".join(cartao_vaga(vaga) for vaga in vagas)
    if not vagas:
        conteudo = (
            '<div class="card"><h2>Nenhuma análise para exibir</h2>'
            '<p>Não há vagas com recomendação CANDIDATAR ou AVALIAR '
            'no período escolhido. A coleta e a fila podem continuar normalmente.</p></div>'
        )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JobHunter AI — Relatório de vagas</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6fb;color:#17263d;font:15px/1.65 system-ui,-apple-system,Segoe UI,sans-serif}}
header{{background:#102a4c;color:#fff;padding:38px 24px}}.wrap{{max-width:960px;margin:auto}}h1{{font-size:30px;margin:0 0 8px}}h2{{font-size:22px;line-height:1.3;margin:12px 0 6px}}h3{{font-size:14px;margin:24px 0 8px}}p{{margin:8px 0 14px}}.intro{{color:#cbd8e8;margin:0}}main{{padding:26px 18px 48px}}.card{{background:#fff;border:1px solid #e1e7ef;border-radius:14px;padding:26px;margin-bottom:20px;box-shadow:0 3px 15px #102a4c08}}.topo{{display:flex;justify-content:space-between;gap:20px}}.empresa{{font-weight:600}}.muted,.meta{{color:#64748b}}.meta{{font-size:12px;border-top:1px solid #e9edf3;border-bottom:1px solid #e9edf3;padding:10px 0;margin:20px 0}}.score{{min-width:90px;text-align:center;background:#edf4ff;border-radius:12px;padding:12px;height:max-content}}.score strong{{display:block;font-size:30px;line-height:1.2;color:#17569c}}.score span{{font-size:11px;color:#526b89}}.badge{{display:inline-block;border-radius:50px;padding:3px 10px;font-size:11px;font-weight:700;letter-spacing:.04em}}.candidatar{{background:#e5f6eb;color:#176437}}.avaliar{{background:#fff2d5;color:#875900}}.colunas{{display:grid;grid-template-columns:1fr 1fr;gap:28px}}ul{{padding-left:19px;margin:5px 0 18px}}li{{margin:7px 0}}.botao{{display:inline-block;background:#17569c;color:white;text-decoration:none;border-radius:8px;padding:10px 17px;font-weight:600;margin-top:8px}}.botao:hover{{background:#0c376b}}footer{{color:#64748b;font-size:12px;padding:0 18px 30px;text-align:center}}@media(max-width:650px){{header{{padding:28px 18px}}h1{{font-size:25px}}.card{{padding:19px}}.colunas{{grid-template-columns:1fr;gap:0}}.topo{{gap:10px}}.score{{min-width:72px;padding:9px}}.score strong{{font-size:25px}}}}
</style>
</head>
<body>
<header><div class="wrap"><h1>JobHunter AI</h1><p class="intro">Seu radar de oportunidades · Relatório local</p></div></header>
<main class="wrap">
<p class="muted">Gerado em {seguro(agora)} · {len(vagas)} vaga(s) · Análises dos últimos {dias} dias</p>
<p>Vagas ordenadas pelo score da IA. As recomendações são estimativas: confirme os requisitos, a modalidade e a disponibilidade diretamente com a empresa.</p>
{conteudo}
</main>
<footer>Relatório gerado a partir do MySQL local. Nenhum e-mail foi enviado.</footer>
</body></html>"""


def gerar_relatorio(limite=10, dias=30):
    vagas = buscar_vagas(limite=limite, dias=dias)
    html = montar_html(vagas, dias=dias)
    ARQUIVO_RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQUIVO_RELATORIO.with_suffix(".html.tmp")
    temporario.write_text(html, encoding="utf-8")
    os.replace(temporario, ARQUIVO_RELATORIO)
    return ARQUIVO_RELATORIO, len(vagas)


def main():
    parser = argparse.ArgumentParser(description="Prévia local das vagas analisadas.")
    parser.add_argument("--abrir", action="store_true", help="Abre o relatório no navegador.")
    parser.add_argument("--limite", type=int, default=10, help="Máximo de vagas (1 a 50).")
    parser.add_argument("--dias", type=int, default=30, help="Período das análises (1 a 365 dias).")
    args = parser.parse_args()

    try:
        caminho, quantidade = gerar_relatorio(args.limite, args.dias)
    except Exception as erro:
        # Não imprimir exceções brutas: conectores podem incluir dados sensíveis.
        print(f"Não foi possível gerar o relatório ({type(erro).__name__}).")
        print("Confira se o MySQL está ligado e se o .env está configurado.")
        raise SystemExit(1) from None

    print(f"Relatório gerado: {caminho}")
    print(f"Vagas incluídas: {quantidade}")
    print("Nenhuma análise foi executada e nenhum e-mail foi enviado.")
    if args.abrir:
        webbrowser.open(caminho.as_uri())


if __name__ == "__main__":
    main()
