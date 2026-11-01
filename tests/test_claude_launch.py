import json
import os
import tempfile
import unittest
from pathlib import Path

from dashboard.backends import claude_launch as cl

ROOT = Path(__file__).resolve().parents[1]
SAFETY = "SAFE"


def role_file(directory, name, model="opus", effort="high", extra="", desc='"A role."'):
    agents = Path(directory) / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\nmodel: {model}\neffort: {effort}\n{extra}---\nBody line.\n"
    )


def argv(**kw):
    base = dict(prompt="do it", alias="opus", role_name="qa_engineer", role_json="{}",
                instructions="INS", safety=SAFETY, effort=None, resume=None)
    base.update(kw)
    return cl.build_argv("/bin/claude", **base)


class RolesTests(unittest.TestCase):
    def test_roles_load_from_generated_files_and_validate(self):
        roles = cl.load_claude_roles(ROOT)
        self.assertEqual(len(roles), 14)
        qa = roles["qa_engineer"]
        self.assertEqual(qa["label"], "Qa Engineer")
        self.assertIn(qa["model"], cl.CLAUDE_MODELS)
        self.assertEqual(qa["profile_model"], qa["model"])
        self.assertIn(qa["reasoning"], cl.CLAUDE_EFFORTS)
        self.assertTrue(qa["instructions"] and not qa["instructions"].startswith("\n"))
        self.assertTrue(qa["description"])
        with tempfile.TemporaryDirectory() as tmp:
            role_file(tmp, "a_role", extra="tools: Read, Grep\ndisallowedTools: Agent\n")
            role = cl.load_claude_roles(Path(tmp))["a_role"]
            self.assertEqual(role["tools"], ["Read", "Grep"])
            self.assertEqual(role["disallowed_tools"], ["Agent"])
            self.assertEqual(role["description"], "A role.")
            self.assertEqual(role["instructions"], "Body line.\n")
            role_file(tmp, "bad_role", model="gpt-x")
            with self.assertRaises(ValueError):
                cl.load_claude_roles(Path(tmp))

    def test_role_with_unknown_model_or_effort_is_rejected(self):
        for kw in ({"model": "nope"}, {"effort": "turbo"}):
            with tempfile.TemporaryDirectory() as tmp:
                role_file(tmp, "r_one", **kw)
                with self.assertRaises(ValueError):
                    cl.load_claude_roles(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            role_file(tmp, "r_one")
            p = Path(tmp) / ".claude" / "agents" / "r_one.md"
            p.write_text(p.read_text().replace("name: r_one", "name: other"))
            with self.assertRaises(ValueError):
                cl.load_claude_roles(Path(tmp))
            p.write_text("---\nname: r_one\n" + "x" * 70000)
            with self.assertRaises(ValueError):
                cl.load_claude_roles(Path(tmp))

    def test_blank_description_and_dotfile_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            role_file(tmp, "r_one", desc='"   "')
            with self.assertRaises(ValueError):
                cl.load_claude_roles(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            role_file(tmp, "r_one")
            agents = Path(tmp) / ".claude" / "agents"
            (agents / ".hidden.md").write_text("garbage")
            self.assertEqual(list(cl.load_claude_roles(Path(tmp))), ["r_one"])

    def test_agents_json_matches_the_live_shape(self):
        role = {"id": "r_one", "description": "dé", "instructions": "p", "model": "sonnet",
                "tools": ["Read", "Grep"], "disallowed_tools": ["Agent"]}
        text = cl.agents_json(role)
        self.assertEqual(text, '{"r_one":{"description":"d\\u00e9","prompt":"p",'
                               '"tools":["Read","Grep"],"model":"sonnet"}}')
        role["tools"] = None
        self.assertNotIn("tools", json.loads(cl.agents_json(role))["r_one"])


class ExpandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)

    def write(self, name, text):
        (self.p / name).write_text(text)

    def test_expand_inlines_agents_md_one_level(self):
        self.write("CLAUDE.md", "head\n@AGENTS.md\ntail\n@ not an import\nx @AGENTS.md\n")
        self.write("AGENTS.md", "agents text\n@NESTED.md\n")
        out = cl.expand_project_instructions(self.p)
        self.assertEqual(out, "head\nagents text\n@NESTED.md\ntail\n@ not an import\nx @AGENTS.md\n")

    def test_expand_refuses_outside_project_symlink_missing_oversize_and_nested_import(self):
        self.assertEqual(cl.expand_project_instructions(self.p), "")
        def refuse(text, **kw):
            self.write("CLAUDE.md", text)
            with self.assertRaisesRegex(ValueError, "Invalid project instructions"):
                cl.expand_project_instructions(self.p, **kw)
        refuse("@../x.md\n")
        refuse("@/etc/hosts\n")
        refuse("@missing.md\n")
        refuse("a\0b\n")
        refuse("a\x1bb\n")
        refuse("x" * 100, max_bytes=50)
        self.write("big.md", "y" * 100)
        refuse("@big.md\n", max_bytes=50)
        self.write("bin.md", "ok\0")
        refuse("@bin.md\n")
        (self.p / "latin.md").write_bytes(b"\xff\xfe")
        refuse("@latin.md\n")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "o.md").write_text("secret")
        os.symlink(Path(outside.name) / "o.md", self.p / "link.md")
        refuse("@link.md\n")
        (self.p / "sub").mkdir()
        refuse("@sub\n")
        (self.p / "CLAUDE.md").unlink()
        os.symlink(self.p / "AGENTS.md", self.p / "CLAUDE.md")
        self.write("AGENTS.md", "a")
        with self.assertRaises(ValueError):
            cl.expand_project_instructions(self.p)
        (self.p / "CLAUDE.md").unlink()
        (self.p / "CLAUDE.md").mkdir()
        with self.assertRaises(ValueError):
            cl.expand_project_instructions(self.p)

    def test_symlinked_directory_dotfiles_and_fifo_are_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "s.md").write_text("secret")
        os.symlink(outside.name, self.p / "d")
        (self.p / ".git").mkdir()
        (self.p / ".git" / "config").write_text("c")
        self.write(".env", "K=v")
        os.mkfifo(self.p / "fifo.md")
        for line in ("@d/s.md\n", "@.env\n", "@.git/config\n", "@fifo.md\n"):
            self.write("CLAUDE.md", line)
            with self.assertRaisesRegex(ValueError, "Invalid project instructions"):
                cl.expand_project_instructions(self.p)
        os.mkfifo(self.p / "f2")
        (self.p / "CLAUDE.md").unlink()
        os.rename(self.p / "f2", self.p / "CLAUDE.md")
        with self.assertRaises(ValueError):
            cl.expand_project_instructions(self.p)

    def test_fenced_import_is_expanded_and_read_is_bounded(self):
        self.write("CLAUDE.md", "```\n@A.md\n```\n")
        self.write("A.md", "inner")
        self.assertEqual(cl.expand_project_instructions(self.p), "```\ninner\n```\n")
        self.write("big.md", "z" * 5000)
        self.write("CLAUDE.md", "@big.md\n")
        with self.assertRaises(ValueError):
            cl.expand_project_instructions(self.p, max_bytes=100)
        import unittest.mock as mock
        reads = []
        real = os.read
        def spy(fd, n):
            reads.append(n)
            return real(fd, n)
        with mock.patch.object(cl.os, "read", spy):
            with self.assertRaises(ValueError):
                cl._read_text(self.p / "big.md", 10, "e")
        self.assertTrue(all(n <= 65536 for n in reads))

    def test_real_repository_claude_md_expands(self):
        out = cl.expand_project_instructions(ROOT)
        agents = (ROOT / "AGENTS.md").read_text().rstrip("\n")
        self.assertIn(agents, out)
        self.assertNotIn("@AGENTS.md", out.split("\n"))


class EnvAndArgvTests(unittest.TestCase):
    def test_environment_is_exactly_the_allow_list(self):
        parent = {"ANTHROPIC_API_KEY": "k", "AWS_PROFILE": "p", "CLAUDE_CODE_USE_BEDROCK": "1",
                  "PATH": "/bin", "HOME": "/h", "LC_ALL": "C", "LANG": "en", "TERM": "x",
                  "USER": "u", "TMPDIR": "/t", "SHELL": "/bin/sh", "BAD": "a\0b", "LC_X": "v"}
        self.assertEqual(cl.child_environment(parent), {
            "PATH": "/bin", "HOME": "/h", "LC_ALL": "C", "LANG": "en", "TERM": "x",
            "USER": "u", "TMPDIR": "/t", "SHELL": "/bin/sh", "LC_X": "v"})
        self.assertEqual(cl.child_environment({"PATH": "/a\0", "HOME": 3}), {})

    def test_argv_is_exact_and_fixed_flags_come_first(self):
        self.assertEqual(argv(), [
            "/bin/claude", "-p", "do it", "--output-format", "stream-json", "--verbose",
            "--setting-sources", "user", "--model", "opus", "--agents", "{}",
            "--agent", "qa_engineer", "--append-system-prompt", "SAFE\n\nINS"])
        self.assertEqual(argv(instructions="")[-1], "SAFE")
        for kw in ({"alias": "gpt"}, {"alias": ["opus"]}, {"role_name": "Bad-Name"}, {"role_name": ""},
                   {"safety": ""}, {"safety": "  "}, {"safety": "-x"}, {"role_json": "[]"}):
            with self.assertRaises(ValueError):
                argv(**kw)
        with self.assertRaises(ValueError):
            cl.build_argv("", prompt="x", alias="opus", role_name="r", role_json="{}",
                          instructions="", safety="s", effort=None, resume=None)

    def test_prompt_edge_cases_are_refused(self):
        for prompt in ("-x", "--version", " -x", "", "  \n ", "a" * 16001, "a\0b"):
            with self.assertRaisesRegex(ValueError, "Invalid instruction"):
                argv(prompt=prompt)
        self.assertEqual(argv(prompt="line1\nline2")[2], "line1\nline2")
        self.assertEqual(argv(prompt="a" * 16000)[2], "a" * 16000)

    def test_resume_is_appended_only_with_a_session_id(self):
        self.assertNotIn("--resume", argv())
        self.assertEqual(argv(resume="abc-123")[-2:], ["--resume", "abc-123"])
        bad_ids = ("", "a b", "-x", "--dangerously-skip-permissions", "a/b", "../a", "x" * 201, "a\nb")
        for bad in bad_ids:
            with self.assertRaises(ValueError):
                argv(resume=bad)
        from dashboard.backends import claude_stream
        for bad in bad_ids:
            self.assertIsNone(claude_stream._SESSION.match(bad), bad)
        for good in ("123e4567-e89b-12d3-a456-426614174000", "abc_1.2:3-4"):
            self.assertEqual(argv(resume=good)[-1], good)
            self.assertTrue(claude_stream._SESSION.match(good))

    def test_effort_flag_only_when_given(self):
        self.assertNotIn("--effort", argv())
        out = argv(effort="max", resume="s1")
        self.assertEqual(out[-4:], ["--effort", "max", "--resume", "s1"])
        for bad in ("", "ultra"):
            with self.assertRaises(ValueError):
                argv(effort=bad)

    def test_argv_size_bound(self):
        with self.assertRaises(ValueError):
            argv(role_json="{" + "x" * 900000)
        self.assertTrue(argv(role_json="{" + "x" * 800000))


if __name__ == "__main__":
    unittest.main()
