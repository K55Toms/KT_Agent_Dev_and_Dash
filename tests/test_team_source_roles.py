"""Role source parser: front matter, harness blocks and directory loading."""

from pathlib import Path
import tempfile
import unittest

from team_source.roles import Role, RoleSourceError, load_roles_dir, parse_role, resolve


def role_text(body, profile="editor", role_id="backend"):
    return (
        "---\n"
        f'id: "{role_id}"\n'
        'description: "Builds the API."\n'
        f'profile: "{profile}"\n'
        "---\n"
        + body
    )


BLOCKS = "a\n<!-- codex-only -->\nb\n<!-- /codex-only -->\nc\n"


class ParseRoleTests(unittest.TestCase):
    def test_parse_reads_front_matter_and_body(self):
        body = "Intro\n" + BLOCKS
        role = parse_role(role_text(body), "roles/backend.md")
        self.assertEqual(
            role,
            Role(id="backend", description="Builds the API.", profile="editor", body=body),
        )

    def test_unbalanced_marker_raises_with_role_id_and_line(self):
        # The source path deliberately does not contain the role id, so the
        # assertion on "(role backend)" pins the id the parser reports itself.
        text = role_text("a\n<!-- codex-only -->\nb\n")
        with self.assertRaises(RoleSourceError) as caught:
            parse_role(text, "roles/source_file.md")
        message = str(caught.exception)
        self.assertIn("(role backend)", message)
        self.assertIn("line 7", message)
        text = role_text("a\n<!-- /claude-only -->\n")
        with self.assertRaises(RoleSourceError) as caught:
            parse_role(text, "roles/source_file.md")
        self.assertIn("(role backend)", str(caught.exception))
        self.assertIn("line 7", str(caught.exception))

    def test_closing_marker_of_other_kind_raises(self):
        text = role_text("<!-- codex-only -->\nb\n<!-- /claude-only -->\n")
        with self.assertRaises(RoleSourceError) as caught:
            parse_role(text, "roles/backend.md")
        self.assertIn("line 8", str(caught.exception))

    def test_nested_marker_raises(self):
        text = role_text(
            "<!-- codex-only -->\n<!-- claude-only -->\nx\n"
            "<!-- /claude-only -->\n<!-- /codex-only -->\n"
        )
        with self.assertRaises(RoleSourceError) as caught:
            parse_role(text, "roles/backend.md")
        message = str(caught.exception)
        self.assertIn("nested", message)
        self.assertIn("line 7", message)

    def test_marker_text_inside_other_text_is_ordinary_body(self):
        body = "Use `<!-- codex-only -->` to mark a block.\n"
        role = parse_role(role_text(body), "roles/backend.md")
        self.assertEqual(role.body, body)
        self.assertEqual(resolve(role.body, "claude"), body)

    def test_unknown_profile_raises(self):
        with self.assertRaises(RoleSourceError) as caught:
            parse_role(role_text("x\n", profile="admin"), "roles/backend.md")
        self.assertIn("admin", str(caught.exception))

    def test_missing_key_raises(self):
        text = '---\nid: "backend"\nprofile: "editor"\n---\nx\n'
        with self.assertRaises(RoleSourceError) as caught:
            parse_role(text, "roles/backend.md")
        self.assertIn("description", str(caught.exception))

    def test_malformed_front_matter_raises(self):
        cases = {
            "missing opening": 'id: "backend"\n',
            "no closing": '---\nid: "backend"\n',
            "not key value": '---\njust some text\n---\n',
            "not a string": '---\nid: 5\n---\n',
            "invalid json": '---\nid: backend\n---\n',
            "unknown key": role_text("x\n").replace("---\nx", 'extra: "v"\n---\nx'),
            "duplicate key": role_text("x\n").replace("---\nx", 'id: "other"\n---\nx'),
            "empty id": role_text("x\n", role_id=""),
        }
        for name, text in cases.items():
            with self.subTest(name):
                with self.assertRaises(RoleSourceError) as caught:
                    parse_role(text, "roles/backend.md")
                self.assertIn("roles/backend.md", str(caught.exception))

    def test_error_text_includes_source(self):
        with self.assertRaises(RoleSourceError) as caught:
            parse_role("no front matter\n", "roles/odd-name.md")
        self.assertIn("roles/odd-name.md", str(caught.exception))

    def test_carriage_returns_in_body_do_not_crash(self):
        body = "a\r\n<!-- codex-only -->\r\nb\r\n"
        with self.assertRaises(RoleSourceError):
            parse_role(role_text(body), "roles/backend.md")
        role = parse_role(role_text("a\r\nb\r\n"), "roles/backend.md")
        self.assertEqual(resolve(role.body, "codex"), "a\r\nb\r\n")


class ResolveTests(unittest.TestCase):
    def test_resolve_keeps_matching_harness_block_and_drops_other(self):
        body = (
            "head\n"
            "<!-- codex-only -->\ncodex line\n<!-- /codex-only -->\n"
            "<!-- claude-only -->\nclaude line\n<!-- /claude-only -->\n"
            "tail\n"
        )
        self.assertEqual(resolve(body, "codex"), "head\ncodex line\ntail\n")
        self.assertEqual(resolve(body, "claude"), "head\nclaude line\ntail\n")

    def test_resolve_removes_marker_lines_exactly(self):
        self.assertEqual(resolve(BLOCKS, "codex"), "a\nb\nc\n")
        self.assertEqual(resolve(BLOCKS, "claude"), "a\nc\n")

    def test_resolve_preserves_trailing_newline_status(self):
        self.assertEqual(resolve("a\nb", "codex"), "a\nb")
        self.assertEqual(resolve("a\nb\n", "codex"), "a\nb\n")
        closed = "a\n<!-- codex-only -->\nb\n<!-- /codex-only -->"
        self.assertEqual(resolve(closed, "claude"), "a\n")
        self.assertEqual(resolve(closed, "codex"), "a\nb\n")
        self.assertEqual(resolve("", "claude"), "")

    def test_resolve_rejects_unknown_harness(self):
        with self.assertRaises(RoleSourceError) as caught:
            resolve("a\n", "gemini")
        self.assertIn("gemini", str(caught.exception))


class LoadRolesDirTests(unittest.TestCase):
    def test_load_roles_dir_returns_roles_keyed_by_id_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "zeta.md").write_text(role_text("z\n", role_id="zeta"), encoding="utf-8")
            (directory / "alpha.md").write_text(role_text("a\n", role_id="alpha"), encoding="utf-8")
            (directory / "notes.txt").write_text("ignored", encoding="utf-8")
            roles = load_roles_dir(directory)
        self.assertEqual(list(roles), ["alpha", "zeta"])
        self.assertEqual(roles["zeta"].body, "z\n")

    def test_load_roles_dir_rejects_id_that_differs_from_filename_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "backend.md").write_text(
                role_text("x\n", role_id="frontend"), encoding="utf-8"
            )
            with self.assertRaises(RoleSourceError) as caught:
                load_roles_dir(directory)
        message = str(caught.exception)
        self.assertIn("backend.md", message)
        self.assertIn("backend", message)
        self.assertIn("frontend", message)

    def test_load_roles_dir_rejects_directory_without_role_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RoleSourceError):
                load_roles_dir(Path(tmp))


if __name__ == "__main__":
    unittest.main()
