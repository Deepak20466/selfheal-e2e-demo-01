import unittest

from apps.calculator import add_numbers


class CalculatorTests(unittest.TestCase):
    def test_add_numbers(self) -> None:
        self.assertEqual(add_numbers(20, 22), 42)


if __name__ == "__main__":
    unittest.main()
