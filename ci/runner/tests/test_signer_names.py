import base64
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "signer_names", Path(__file__).resolve().parents[1] / "signer_names.py"
)
signer_names = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signer_names)

CN = "Apple Distribution: Sam Example (ABCDE12345)"


class SignerNamesTests(unittest.TestCase):
    def test_both_openssl_subject_styles_give_the_owner_names(self):
        expected = [CN, "Example Studio", "Sam Example"]
        libressl = f"subject= /UID=ABCDE12345/CN={CN}/OU=ABCDE12345/O=Example Studio/C=US"
        openssl3 = f"subject=UID=ABCDE12345, CN={CN}, OU=ABCDE12345, O=Example Studio, C=US"
        self.assertEqual(signer_names.names(libressl), expected)
        self.assertEqual(signer_names.names(openssl3), expected)
        self.assertEqual(signer_names.names(""), [])

    def test_reads_a_real_pkcs12_and_prints_mask_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            key, cert, p12 = (os.path.join(folder, n) for n in ("k.pem", "c.pem", "c.p12"))
            subject = f"/CN={CN}/O=Example Studio/C=US"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    key,
                    "-out",
                    cert,
                    "-days",
                    "1",
                    "-subj",
                    subject,
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "pkcs12",
                    "-export",
                    "-inkey",
                    key,
                    "-in",
                    cert,
                    "-out",
                    p12,
                    "-passout",
                    "pass:synthetic-pass",
                ],
                check=True,
                capture_output=True,
            )
            data = Path(p12).read_bytes()
        found = signer_names.names(signer_names.subject(data, "synthetic-pass"))
        self.assertEqual(found, [CN, "Example Studio", "Sam Example"])
        self.assertEqual(signer_names.subject(data, "wrong"), "")
        env = {
            "IOS_P12_BASE64": base64.b64encode(data).decode(),
            "IOS_P12_PASSWORD": "synthetic-pass",
        }
        out = subprocess.run(
            ["python3", str(Path(spec.origin))], env=dict(os.environ, **env), capture_output=True
        ).stdout.decode()
        self.assertIn("::add-mask::Sam Example\n", out)


if __name__ == "__main__":
    unittest.main()
