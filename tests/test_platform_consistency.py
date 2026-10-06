import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlatformConsistencyTests(unittest.TestCase):
    def test_deployment_and_ci_use_the_same_python_version(self):
        version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
        runtime = (ROOT / "runtime.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(runtime, f"python-{version}")

    def test_time_zone_database_is_a_declared_dependency(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(line.startswith("tzdata==") for line in requirements))


if __name__ == "__main__":
    unittest.main()
