import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "update_access_ip", Path(__file__).resolve().parents[1] / "update-access-ip.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AccessIPTests(unittest.TestCase):
    def test_preserves_other_values_and_comments(self):
        original = ('# local\neks_public_access_cidrs = ["8.8.8.8/32"] # EKS\n'
                    'app_access_cidrs = ["8.8.4.4/32", "1.0.0.1/32"]\nname = "lab"\n')
        result = module.updated_config(original, "1.1.1.1")
        self.assertIn('eks_public_access_cidrs = ["1.1.1.1/32"] # EKS', result)
        self.assertIn('app_access_cidrs = ["1.1.1.1/32"]', result)
        self.assertIn('name = "lab"', result)
        self.assertEqual(module.updated_config(result, "1.1.1.1"), result)

    def test_rejects_non_public_or_invalid_addresses(self):
        for address in ("127.0.0.1", "10.0.0.1", "0.0.0.0", "::1", "invalid"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                module.public_ipv4(address)

    def test_requires_both_single_line_assignments(self):
        for text in ('name = "lab"', 'eks_public_access_cidrs = [\n"1.1.1.1/32"\n]'):
            with self.assertRaises(ValueError):
                module.updated_config(text, "1.1.1.1")


if __name__ == "__main__":
    unittest.main()
