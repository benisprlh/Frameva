import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from frameva.source import inspect_archive, inspect_repository, build_launch_plan


class SourceTests(unittest.TestCase):
    def make_zip(self, files):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as z:
            for path, content in files.items():
                z.writestr(path, content)
        return output.getvalue()

    def test_zip_evidence_and_plan(self):
        data = self.make_zip({"demo/package.json": json.dumps({"name": "Demo", "dependencies": {"react": "19"}}),
            "demo/README.md": "# Demo\n## Features\n- Project boards\n- Export reports\n## Roadmap\n- Time travel",
            "demo/.env": "SECRET=please-never-read", "demo/node_modules/a/index.js": "ignore"})
        result = inspect_archive(data)
        self.assertEqual(result["frameworks"], ["React"])
        self.assertEqual([x["title"] for x in result["features"]], ["Project boards", "Export reports"])
        self.assertEqual(result["features"][0]["evidence"][0]["line"], 3)
        self.assertNotIn(".env", str(result))
        shots = build_launch_plan(result, "Demo", "portrait")
        self.assertEqual(len(shots), 4)
        self.assertEqual(shots[1]["width"], 720)
        self.assertIn("README.md:3", shots[1]["prompt"])

    def test_unsafe_zip(self):
        for path in ["../escape.py", "/root/key.py", "C:/foo.py", "a\\b.py"]:
            with self.assertRaises(ValueError):
                inspect_archive(self.make_zip({path: "x"}))

    def test_reject_symlink_zip(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            info = zipfile.ZipInfo("linked.py")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            z.writestr(info, "../secrets")
        with self.assertRaises(ValueError):
            inspect_archive(data.getvalue())

    def test_repo_no_execution_no_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("# App\n## Features\n- API key: secret-value\n- Shared workspaces")
            (root / ".env").write_text("DO_NOT_READ=1")
            (root / "evil.py").write_text("raise RuntimeError('must not run')")
            result = inspect_repository(root)
            self.assertNotIn("secret-value", json.dumps(result))
            self.assertNotIn(".env", result["files"])
            self.assertIn("evil.py", result["files"])

    def test_invalid_and_empty(self):
        with self.assertRaises(ValueError):
            inspect_archive(b"not a zip")
        result = inspect_archive(self.make_zip({".env": "secret"}))
        self.assertEqual(result["stats"]["files_scanned"], 0)
        self.assertEqual(len(build_launch_plan(result, "App")), 3)

    def test_markdown_code_comments_are_not_product_titles(self):
        result = inspect_archive(self.make_zip({"README.md": "# Frameva\n## Capabilities\n| Capability | Implementation |\n|---|---|\n| Source analysis | Evidence |\n```bash\n# Activate the environment\n```\n"}))
        self.assertEqual(result["name"], "Frameva")
        self.assertEqual(result["features"][0]["title"], "Source analysis")

if __name__ == "__main__":
    unittest.main()
