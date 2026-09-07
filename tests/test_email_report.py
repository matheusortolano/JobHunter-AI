"""Testes locais do envio: não usam Gmail real, Gemini ou MySQL."""
import contextlib
import importlib.util
import io
import json
import multiprocessing
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

RAIZ = Path(__file__).resolve().parents[1]
FONTE = RAIZ / "src" / "email_report.py"

# Substitui apenas os módulos locais de acesso ao banco e de HTML.
# Todas as chamadas de rede serão simuladas nos testes.
banco_falso = ModuleType("database")
banco_falso.conectar_banco = MagicMock(side_effect=AssertionError("MySQL real não permitido"))
html_falso = ModuleType("relatorio_vagas")
html_falso.montar_html = lambda vagas, dias=30: "<html>Relatório simulado</html>"
with patch.dict(sys.modules, {"database": banco_falso, "relatorio_vagas": html_falso}):
    spec = importlib.util.spec_from_file_location("email_report_tested", FONTE)
    MOD = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = MOD
    spec.loader.exec_module(MOD)


def tentar_trava_filho(caminho, fila):
    MOD.TRAVA = Path(caminho)
    try:
        with MOD.bloquear_envio():
            fila.put("adquiriu")
    except MOD.EnvioEmExecucao:
        fila.put("bloqueado")


class TestEmailReport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        raiz = Path(self.temp.name)
        substituicoes = {
            "ESTADO": raiz / "email_report_state.json",
            "MARCADOR": raiz / ".email_report_initialized",
            "TRAVA": raiz / ".email_report.lock",
            "PREVIEW": raiz / "reports" / "preview.html",
            "LOG": raiz / "logs" / "email_report.log",
            "TOKEN": raiz / "credentials" / "gmail_token.json",
        }
        for nome, valor in substituicoes.items():
            p = patch.object(MOD, nome, valor)
            p.start()
            self.addCleanup(p.stop)
        self.saida = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.saida)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.vagas = [
            {"id": 4, "titulo": "Vaga simulada", "score_ia": 80,
             "data_analise_ia": datetime.now()},
        ]
        self.buscar = patch.object(
            MOD, "buscar_novas_vagas",
            side_effect=lambda estado=None: [
                v for v in self.vagas
                if v["id"] not in (estado or MOD.carregar_estado())["ids_enviados"]
            ],
        )
        self.buscar.start()
        self.addCleanup(self.buscar.stop)
        self.enderecos = patch.object(
            MOD, "obter_enderecos", return_value=("teste@example.com", "teste@example.com")
        )
        self.enderecos.start()
        self.addCleanup(self.enderecos.stop)
        self.credenciais_patch = patch.object(MOD, "carregar_credenciais", return_value=object())
        self.credenciais = self.credenciais_patch.start()
        self.addCleanup(self.credenciais_patch.stop)
        self.html = patch.object(MOD, "criar_html", return_value="<html>Teste</html>")
        self.html.start()
        self.addCleanup(self.html.stop)
        self.servico = MagicMock()
        self.executar = self.servico.users.return_value.messages.return_value.send.return_value.execute
        self.executar.return_value = {"id": "gmail-confirmado-1"}
        self.cliente = patch.object(MOD, "criar_servico", return_value=self.servico)
        self.cliente.start()
        self.addCleanup(self.cliente.stop)

    def estado(self):
        return MOD.carregar_estado()

    def test_migracao_preserva_ids_e_data(self):
        antigo = {"ids_enviados": [3, 1, 2], "ultimo_envio": "2026-09-07T12:14:18-03:00"}
        MOD.ESTADO.write_text(json.dumps(antigo), encoding="utf-8")
        estado = self.estado()
        self.assertEqual(estado["ids_enviados"], [1, 2, 3])
        self.assertEqual(estado["ultimo_envio"], antigo["ultimo_envio"])
        self.assertIsNone(estado["pendente"])
        self.assertTrue(MOD.MARCADOR.exists())

    def test_historico_perdido_ou_invalido_bloqueia(self):
        MOD.salvar_estado(MOD.novo_estado())
        MOD.ESTADO.unlink()
        with self.assertRaises(RuntimeError):
            MOD.carregar_estado()
        self.assertEqual(self.executar.call_count, 0)
        MOD.ESTADO.write_text("{invalido", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            MOD.carregar_estado()

    def test_envio_sucesso_e_segunda_execucao_sem_duplicacao(self):
        MOD.salvar_estado({"ids_enviados": [1, 2, 3], "ultimo_envio": None, "pendente": None})
        self.assertEqual(MOD.executar_envio(automatico=True), 0)
        self.assertEqual(self.estado()["ids_enviados"], [1, 2, 3, 4])
        self.assertIsNone(self.estado()["pendente"])
        self.assertEqual(self.executar.call_count, 1)
        self.assertEqual(MOD.executar_envio(automatico=True), 0)
        self.assertEqual(self.executar.call_count, 1)
        self.assertTrue(MOD.LOG.exists())

    def test_falha_ambigua_bloqueia_repeticao_e_resolucao_manual(self):
        self.executar.side_effect = TimeoutError("conexão interrompida")
        with self.assertRaises(MOD.EnvioPendente):
            MOD.executar_envio(automatico=True)
        pendente = self.estado()["pendente"]
        self.assertEqual(pendente["fase"], "preparado")
        self.assertEqual(pendente["ids"], [4])
        self.assertTrue(pendente["message_id"].startswith("<"))
        with self.assertRaises(MOD.EnvioPendente):
            MOD.executar_envio(automatico=True)
        self.assertEqual(self.executar.call_count, 1)
        with patch("builtins.input", return_value="ENVIADO"):
            MOD.resolver_pendente(pendente["identificador"], entregue=True)
        self.assertEqual(self.estado()["ids_enviados"], [4])
        self.assertIsNone(self.estado()["pendente"])

    def test_liberacao_explicita_nao_envia_automaticamente(self):
        self.executar.side_effect = TimeoutError("simulado")
        with self.assertRaises(MOD.EnvioPendente):
            MOD.executar_envio(automatico=True)
        identificador = self.estado()["pendente"]["identificador"]
        with patch("builtins.input", return_value="REENVIAR"):
            self.assertEqual(MOD.resolver_pendente(identificador, entregue=False), 0)
        self.assertIsNone(self.estado()["pendente"])
        self.assertEqual(self.executar.call_count, 1)
        self.assertEqual(self.estado()["ids_enviados"], [])

    def test_confirmacao_duravel_recupera_sem_enviar_novamente(self):
        pendente = {
            "identificador": "abc", "ids": [4], "destinatario": "teste@example.com",
            "assunto": "Teste", "message_id": "<abc@jobhunter.local>",
            "criado_em": MOD.agora(), "fase": "aceito", "gmail_id": "gmail-123",
        }
        MOD.salvar_estado({"ids_enviados": [1, 2, 3], "ultimo_envio": None, "pendente": pendente})
        self.assertEqual(MOD.executar_envio(automatico=True), 0)
        self.assertEqual(self.estado()["ids_enviados"], [1, 2, 3, 4])
        self.assertEqual(self.executar.call_count, 0)

    def test_status_e_preview_nao_enviam(self):
        with patch.object(MOD.webbrowser, "open") as navegador:
            MOD.mostrar_status()
            self.assertEqual(MOD.gerar_preview(), 0)
            navegador.assert_called_once()
        self.assertEqual(self.executar.call_count, 0)
        self.credenciais.assert_not_called()
        self.assertFalse(MOD.ESTADO.exists())
        self.assertTrue(MOD.PREVIEW.exists())

    def test_envio_manual_exige_confirmacao(self):
        with patch("builtins.input", return_value="NÃO"):
            self.assertEqual(MOD.executar_envio(automatico=False), 0)
        self.assertEqual(self.executar.call_count, 0)
        self.credenciais.assert_not_called()

    def test_busca_nao_perde_vagas_apos_primeiras_50_enviadas(self):
        self.buscar.stop()
        linhas = [
            {"id": i, "titulo": "Teste", "score_ia": 100-i,
             "data_analise_ia": datetime.now()}
            for i in range(1, 65)
        ]
        cursor = MagicMock()
        cursor.fetchall.return_value = linhas
        conexao = MagicMock()
        conexao.cursor.return_value = cursor
        with patch.object(MOD, "conectar_banco", return_value=conexao):
            novas = MOD.buscar_novas_vagas({"ids_enviados": list(range(1, 51)),
                                           "ultimo_envio": None, "pendente": None})
        self.assertEqual([v["id"] for v in novas], list(range(51, 61)))
        consulta = cursor.execute.call_args.args[0]
        self.assertNotIn("LIMIT", consulta.upper())
        conexao.close.assert_called_once()

    def test_trava_entre_processos(self):
        contexto = multiprocessing.get_context(
            "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
        )
        fila = contexto.Queue()
        with MOD.bloquear_envio():
            processo = contexto.Process(target=tentar_trava_filho, args=(str(MOD.TRAVA), fila))
            processo.start()
            self.assertEqual(fila.get(timeout=15), "bloqueado")
            processo.join(timeout=15)
            self.assertEqual(processo.exitcode, 0)
        with MOD.bloquear_envio():
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
