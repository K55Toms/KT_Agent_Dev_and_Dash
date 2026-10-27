"""Role renderers: Codex TOML and Claude Markdown from one role source."""

import json
import tomllib
import unittest

from team_source.roles import Role, RoleSourceError, render_claude, render_codex, resolve

BODY = (
    "Intro line.\n"
    "<!-- codex-only -->\n"
    "Codex only line.\n"
    "<!-- /codex-only -->\n"
    "<!-- claude-only -->\n"
    "Claude only line.\n"
    "<!-- /claude-only -->\n"
    "Closing line.\n"
)


def make_role(body=BODY, profile="editor", description="Builds the API.", role_id="backend"):
    return Role(id=role_id, description=description, profile=profile, body=body)


def front_matter(text):
    """Return the lines between the two --- fences of rendered Markdown."""
    lines = text.split("\n")
    assert lines[0] == "---"
    return lines[1 : lines.index("---", 1)]


class RenderCodexTests(unittest.TestCase):
    def test_render_codex_parses_back_to_same_values(self):
        role = make_role(description='Builds the "API" \u2014 caf\u00e9.')
        text = render_codex(role, "gpt-5", "high")
        data = tomllib.loads(text)
        self.assertEqual(
            list(data),
            ["name", "model", "model_reasoning_effort", "description", "developer_instructions"],
        )
        self.assertEqual(data["name"], "backend")
        self.assertEqual(data["model"], "gpt-5")
        self.assertEqual(data["model_reasoning_effort"], "high")
        self.assertEqual(data["description"], role.description)
        self.assertEqual(data["developer_instructions"], resolve(role.body, "codex"))
        self.assertTrue(text.endswith('"""\n'))
        self.assertFalse(text.endswith("\n\n"))

    def test_render_codex_starts_with_the_generated_file_header(self):
        role = make_role(role_id="qa_engineer")
        text = render_codex(role, "gpt-5", "high")
        self.assertTrue(
            text.startswith(
                "# Generated from team_source/roles/qa_engineer.md and team_source/models.toml"
                " by scripts/sync_roles.py.\n"
                "# Edit those files, then run: python3 scripts/sync_roles.py\n"
                'name = "qa_engineer"\n'
            ),
            text[:300],
        )
        # Comments do not change the parsed values or their order.
        data = tomllib.loads(text)
        self.assertEqual(data["name"], "qa_engineer")
        self.assertEqual(data["developer_instructions"], resolve(role.body, "codex"))
        self.assertEqual(text.count("# Generated from"), 1)

    def test_render_codex_keeps_only_codex_blocks(self):
        text = render_codex(make_role(), "gpt-5", "high")
        self.assertIn("Codex only line.", text)
        self.assertNotIn("Claude only line.", text)
        self.assertNotIn("<!--", text)

    def test_render_codex_body_without_trailing_newline_round_trips(self):
        role = make_role(body='Say "hi"')
        data = tomllib.loads(render_codex(role, "gpt-5", "high"))
        self.assertEqual(data["developer_instructions"], 'Say "hi"')

    def test_render_codex_rejects_triple_quote_and_backslash(self):
        for body in ('a """ b\n', "path C:\\temp\n", 'ends with """'):
            with self.subTest(body=body):
                with self.assertRaises(RoleSourceError) as caught:
                    render_codex(make_role(body=body), "gpt-5", "high")
                self.assertIn("backend", str(caught.exception))

    def test_render_codex_ignores_triple_quote_in_claude_only_block(self):
        body = 'a\n<!-- claude-only -->\n"""\\\n<!-- /claude-only -->\nb\n'
        data = tomllib.loads(render_codex(make_role(body=body), "gpt-5", "high"))
        self.assertEqual(data["developer_instructions"], "a\nb\n")

    def test_render_codex_round_trip_check_rejects_unparseable_output(self):
        # A raw control character passes the up-front check but is illegal TOML.
        for body in ("a\x01b\n", "a\rb\n", "a\x7fb\n"):
            with self.subTest(body=body):
                with self.assertRaises(RoleSourceError) as caught:
                    render_codex(make_role(body=body), "gpt-5", "high")
                self.assertIn("backend", str(caught.exception))
        with self.assertRaises(RoleSourceError) as caught:
            render_codex(make_role(description="bad\x7fvalue"), "gpt-5", "high")
        self.assertIn("backend", str(caught.exception))

    def test_render_codex_body_ending_in_quotes_is_checked_by_round_trip(self):
        # One or two quotes before the closing delimiter are valid TOML and
        # must survive; the round trip is what proves it.
        for body in ('ends "', 'ends ""', 'ends\n"', 'ends\n""'):
            with self.subTest(body=body):
                data = tomllib.loads(render_codex(make_role(body=body), "gpt-5", "high"))
                self.assertEqual(data["developer_instructions"], body)


class RenderClaudeTests(unittest.TestCase):
    def test_render_claude_editor_has_no_tools_line(self):
        text = render_claude(make_role(), "opus", "high", coordinator=True)
        keys = [line.partition(":")[0] for line in front_matter(text)]
        self.assertEqual(keys, ["name", "description", "model", "effort"])
        self.assertNotIn("tools", keys)

    def test_render_claude_reviewer_has_read_only_tools_and_no_agent_tool(self):
        role = make_role(profile="reviewer", role_id="code_review")
        text = render_claude(role, "opus", "high", coordinator=False)
        lines = front_matter(text)
        self.assertIn("tools: Read, Grep, Glob", lines)
        self.assertIn("disallowedTools: Agent", lines)
        self.assertEqual(
            [line.partition(":")[0] for line in lines],
            ["name", "description", "model", "effort", "tools", "disallowedTools"],
        )
        tools_line = next(line for line in lines if line.startswith("tools:"))
        self.assertNotIn("Bash", tools_line)
        self.assertNotIn("Bash", "\n".join(lines))

    def test_render_claude_coordinator_keeps_agent_tool(self):
        text = render_claude(make_role(), "opus", "high", coordinator=True)
        self.assertNotIn("disallowedTools", text)
        text = render_claude(make_role(), "opus", "high", coordinator=False)
        self.assertIn("disallowedTools: Agent", front_matter(text))

    def test_render_claude_coordinator_is_keyword_only(self):
        with self.assertRaises(TypeError):
            render_claude(make_role(), "opus", "high", True)

    def test_render_claude_layout_and_body(self):
        text = render_claude(make_role(), "opus", "high", coordinator=False)
        self.assertEqual(
            text,
            "---\n"
            "name: backend\n"
            'description: "Builds the API."\n'
            "model: opus\n"
            "effort: high\n"
            "disallowedTools: Agent\n"
            "---\n"
            + resolve(BODY, "claude"),
        )
        self.assertIn("Claude only line.", text)
        self.assertNotIn("Codex only line.", text)
        self.assertNotIn("<!--", text)

    def test_render_claude_description_survives_quotes(self):
        description = 'Says "hello" and \u2014 more: colon # hash'
        text = render_claude(make_role(description=description), "opus", "high", coordinator=True)
        line = next(item for item in front_matter(text) if item.startswith("description: "))
        self.assertEqual(json.loads(line[len("description: ") :]), description)

    def test_render_claude_parse_back_rejects_injected_front_matter_keys(self):
        # A Role built directly bypasses parse_role's id check; the renderer's own
        # parse-back of the front matter must still refuse the extra key.
        crafted = {
            "newline key": "x\npermissionMode: bypassPermissions",
            "closing fence": "x\n---\nhooks: {}",
            "indented key": "x\n tools: Bash",
            "line without colon": "x\nstray",
        }
        for name, role_id in crafted.items():
            for profile, coordinator in (("editor", False), ("reviewer", False), ("editor", True)):
                with self.subTest(name, profile=profile, coordinator=coordinator):
                    role = make_role(role_id=role_id, profile=profile)
                    with self.assertRaises(RoleSourceError) as caught:
                        render_claude(role, "opus", "high", coordinator=coordinator)
                    message = str(caught.exception)
                    self.assertIn("front matter", message)
                    self.assertIn(repr(role_id), message)

    def test_render_claude_parse_back_accepts_every_legal_layout(self):
        for profile, coordinator, keys in (
            ("editor", True, ["name", "description", "model", "effort"]),
            ("editor", False, ["name", "description", "model", "effort", "disallowedTools"]),
            ("reviewer", False, ["name", "description", "model", "effort", "tools", "disallowedTools"]),
            ("reviewer", True, ["name", "description", "model", "effort", "tools"]),
        ):
            with self.subTest(profile=profile, coordinator=coordinator):
                text = render_claude(make_role(profile=profile), "opus", "high", coordinator=coordinator)
                self.assertEqual([line.partition(":")[0] for line in front_matter(text)], keys)

    def test_render_claude_rejects_unsafe_model_or_effort(self):
        for model, effort in (("opus\nx: y", "high"), ("opus", "hi gh"), ("", "high"), ("opus", "")):
            with self.subTest(model=model, effort=effort):
                with self.assertRaises(RoleSourceError) as caught:
                    render_claude(make_role(), model, effort, coordinator=True)
                self.assertIn("backend", str(caught.exception))
        text = render_claude(make_role(), "claude-opus-4.5_x", "x-high", coordinator=True)
        self.assertIn("model: claude-opus-4.5_x", text)
        self.assertIn("effort: x-high", text)


if __name__ == "__main__":
    unittest.main()
