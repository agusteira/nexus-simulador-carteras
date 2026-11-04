"""Verifica la demostración completa de los casos del cliente."""

from contextlib import redirect_stdout
import io
import unittest

from scripts.correr_casos_cliente import main


class CorrerCasosClienteTest(unittest.TestCase):
    def test_diez_casos_coinciden(self):
        salida = io.StringIO()
        with redirect_stdout(salida):
            codigo = main([])
        self.assertEqual(codigo, 0)
        self.assertIn("10/10 casos coinciden con lo esperado por el cliente", salida.getvalue())
        self.assertEqual(salida.getvalue().count("OK (coincide"), 10)
