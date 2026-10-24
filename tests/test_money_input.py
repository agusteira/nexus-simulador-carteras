"""Amount parsing and actual client formatter/interaction regressions."""

from pathlib import Path
import shutil
import subprocess
import unittest

from nexus.ui.money_input import format_money, parse_money


class MoneyInputTest(unittest.TestCase):
    def test_argentine_amounts_round_trip(self):
        for text, expected in (("", None), ("0", 0.0), ("1.234.567,89", 1234567.89),
                               ("250000,5", 250000.5), ("0,01", 0.01), ("123,", 123.0)):
            with self.subTest(text=text):
                actual = parse_money(text)
                self.assertEqual(actual, expected)
                self.assertEqual(parse_money(format_money(actual)), expected)

    def test_invalid_and_unsafe_amounts_are_rejected(self):
        for text in ("-100", "NaN", "Infinity", "1,234.56", "1,234", "12.34", "9" * 30, 100):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_money(text)

    def test_float_boundary_preserves_cents(self):
        for text in ("45.035.996.273.704,95", "45.035.996.273.704,94", "45.035.996.273.704,93"):
            self.assertEqual(format_money(parse_money(text)), text)
        for text in ("45.035.996.273.704,96", "90.071.992.547.409,91"):
            with self.assertRaises(ValueError):
                parse_money(text)

    @unittest.skipUnless(shutil.which("node"), "Node unavailable; JS suite can run separately")
    def test_client_formatter_and_events(self):
        script = Path(__file__).with_name("money_input_client.mjs")
        result = subprocess.run([shutil.which("node"), str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
