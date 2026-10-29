"""Fixture tests for bin/hash-release. Run: python3 -m unittest discover tests"""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/fixtures"
loader = importlib.machinery.SourceFileLoader("hash_release", str(ROOT / "bin/hash-release"))
spec = importlib.util.spec_from_loader("hash_release", loader)
hr = importlib.util.module_from_spec(spec)
loader.exec_module(hr)


def git(cwd, *args):
  env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
  subprocess.run(["git", "-c", "core.autocrlf=false"] + list(args), cwd=cwd, check=True, capture_output=True, env=env)


class Fixture(unittest.TestCase):
  def test_package_tree_matches_expected(self):
    expected = json.loads((FIXTURES / "package.expected.json").read_text())
    self.assertEqual(hr.hash_dir(FIXTURES / "package"), expected)

  def test_tree_is_sha256_of_the_lines_file(self):
    expected = json.loads((FIXTURES / "package.expected.json").read_text())
    lines = (FIXTURES / "package.lines.txt").read_bytes()
    self.assertEqual(hashlib.sha256(lines).hexdigest(), expected["tree"])
    rebuilt = "".join("%s %s\n" % (h, p) for p, h in expected["files"].items()).encode()
    self.assertEqual(rebuilt, lines)

  def test_source_with_dsignore_hashes_like_the_package(self):
    self.assertEqual(hr.hash_dir(FIXTURES / "source"), hr.hash_dir(FIXTURES / "package"))

  def test_bytewise_order(self):
    files = list(json.loads((FIXTURES / "package.expected.json").read_text())["files"])
    self.assertLess(files.index("Zeta.txt"), files.index("a-b.txt"))
    self.assertLess(files.index("a-b.txt"), files.index("a/b.txt"))
    self.assertLess(files.index("a/b.txt"), files.index("a_b.txt"))
    self.assertLess(files.index("binary.bin"), files.index("caf\u00e9.txt"))
    self.assertLess(files.index("caf\u00e9.txt"), files.index("crlf.txt"))

  def test_only_top_level_signature_is_left_out(self):
    files = json.loads((FIXTURES / "package.expected.json").read_text())["files"]
    self.assertNotIn("dirigible-signature.json", files)
    self.assertIn("a/dirigible-signature.json", files)


class DsIgnore(unittest.TestCase):
  def test_rules_the_server_rejects(self):
    for rule in ["!keep", "*.log", "a?", "[ab]", "a\\b", "../up", "foo..bar", "a//b", "./a", "/", "C:/x"]:
      with self.subTest(rule=rule), self.assertRaises(hr.Rejected):
        hr.parse_dsignore(rule.encode() + b"\n")

  def test_rules_the_server_accepts(self):
    rules = hr.parse_dsignore(b"\xef\xbb\xbf# comment\n\n /lead \r\ntrail/\nplain\n")
    self.assertEqual(rules, [("lead", False), ("trail", True), ("plain", False)])

  def test_matching(self):
    rules = [("docs", False), ("build", True), ("a/b.txt", False)]
    self.assertTrue(hr.ignored("docs", rules))
    self.assertTrue(hr.ignored("docs/x/y.md", rules))  # an ignored folder hides its contents
    self.assertTrue(hr.ignored("build/x", rules))
    self.assertTrue(hr.ignored("build", rules))
    self.assertTrue(hr.ignored("a/b.txt", rules))
    self.assertTrue(hr.ignored(".dsignore", rules))
    self.assertFalse(hr.ignored("docsx/y", rules))
    self.assertFalse(hr.ignored("sub/.dsignore", rules))
    self.assertFalse(hr.ignored("a/b.txt.orig", rules))

  def test_symlink_rejected(self):
    with tempfile.TemporaryDirectory() as tmp:
      (pathlib.Path(tmp) / "x.txt").write_text("x")
      os.symlink("x.txt", pathlib.Path(tmp) / "link")
      with self.assertRaises(hr.Rejected):
        hr.hash_dir(tmp)


class Tag(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.mkdtemp()
    self.repo = pathlib.Path(self.tmp)
    git(self.repo, "init", "-q", "-b", "main")
    shutil.copytree(FIXTURES / "source", self.repo, dirs_exist_ok=True)
    (self.repo / "demo.php").write_text("<?php\n/**\n * Plugin Name: Demo\n * Version: 1.2.3\n */\n")
    (self.repo / ".gitattributes").write_text("* -text\n/tests export-ignore\n/.gitattributes export-ignore\n/demo.php -text\n")
    (self.repo / "tests").mkdir()
    (self.repo / "tests/t.php").write_text("export-ignored")
    git(self.repo, "add", "-A")
    git(self.repo, "commit", "-q", "-m", "1.2.3")
    git(self.repo, "tag", "-a", "1.2.3", "-m", "1.2.3")

  def tearDown(self):
    shutil.rmtree(self.tmp)

  def release(self, tag="1.2.3", main="demo.php"):
    return hr.hash_release(self.repo, tag, "demo", "Owner/demo", "plugin", main, "2026-10-29T00:00:00Z")

  def test_tag_matches_fixture_plus_main_file(self):
    data = self.release()
    package = hr.hash_dir(FIXTURES / "package")["files"]
    self.assertEqual(set(data["files"]), set(package) | {"demo.php"})
    for path, digest in package.items():
      self.assertEqual(data["files"][path], digest)
    self.assertNotIn("tests/t.php", data["files"])
    self.assertEqual(data["format"], "dirigible-hashes-v1")
    self.assertEqual(data["version"], "1.2.3")
    self.assertEqual(len(data["commit"]), 40)

  def test_v_prefix_is_normalized(self):
    git(self.repo, "tag", "v1.2.3", "1.2.3^{commit}")
    self.assertEqual(self.release("v1.2.3")["version"], "1.2.3")

  def test_header_mismatch_rejected(self):
    git(self.repo, "tag", "1.2.4", "1.2.3^{commit}")
    with self.assertRaises(hr.Rejected):
      self.release("1.2.4")

  def test_bad_tag_rejected(self):
    git(self.repo, "tag", "release-1", "1.2.3^{commit}")
    with self.assertRaises(hr.Rejected):
      self.release("release-1")

  def test_missing_main_rejected(self):
    with self.assertRaises(hr.Rejected):
      self.release(main="other.php")

  def test_main_excluded_by_dsignore_rejected(self):
    (self.repo / ".dsignore").write_text("demo.php\n")
    git(self.repo, "commit", "-q", "-am", "x")
    git(self.repo, "tag", "-f", "1.2.3")
    with self.assertRaises(hr.Rejected):
      self.release()

  def test_export_subst_refused(self):
    (self.repo / ".gitattributes").write_text("version.txt export-subst\n")
    git(self.repo, "commit", "-q", "-am", "x")
    git(self.repo, "tag", "-f", "1.2.3")
    with self.assertRaises(ValueError):
      self.release()

  def test_symlink_in_tag_rejected(self):
    os.symlink("README.md", self.repo / "link")
    git(self.repo, "add", "link")
    git(self.repo, "commit", "-q", "-m", "x")
    git(self.repo, "tag", "-f", "1.2.3")
    with self.assertRaises(hr.Rejected):
      self.release()


if __name__ == "__main__":
  unittest.main()
