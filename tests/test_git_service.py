"""Disposable Git fixtures; every publication command is intercepted before execution."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dashboard.git_service import GitService, GitServiceError, _bounded, _environment, _creation_environment


REMOTE = "https://github.com/example/synthetic.git"


class SafeRunner:
    def __init__(self):
        self.calls = []
        self.pushes = []
        self.push_code = 0
        self.on_push = None
        self.creations = []
        self.creation_code = 0
        self.on_create = None

    def __call__(self, argv, root, env, **kwargs):
        # Record command metadata only; inherited environments may contain credentials.
        self.calls.append((list(argv), None))
        if argv[1:3] == ["repo", "create"]:
            self.creations.append(list(argv))
            if self.on_create:
                self.on_create()
            return self.creation_code, b""
        if "push" in argv:
            self.pushes.append(list(argv))
            if self.on_push:
                self.on_push()
            return self.push_code, b""
        return _bounded(argv, root, env, **kwargs)


class GitServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dashboard-git-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "project"
        self.repo.mkdir()
        self.global_config = self.root / "global-config"
        self.global_config.write_text("")
        # Isolate Git's global config without touching real user identity or credentials.
        original = _environment

        def environment(scan=False):
            result = original(scan)
            result.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(self.global_config))
            return result

        self.environment = environment
        self.addCleanup(patch.stopall)
        patch("dashboard.git_service._environment", side_effect=environment).start()
        self.runner = SafeRunner()
        self.service = GitService(runner=self.runner)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Synthetic Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", REMOTE)
        self.write("README.md", "Synthetic source documentation.\n")
        self.commit("Initial synthetic commit")

    def git(self, *args, expected=0, data=None):
        result = subprocess.run(["git", *args], cwd=self.repo, env=self.environment(),
                                input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, expected, "Synthetic Git fixture failed; output suppressed")
        return result.stdout

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "-m", message)

    def confirmation(self):
        state = self.service.status(self.repo)
        return {key: state[key] for key in ("head", "branch", "remote")} | {"confirmed": True}

    def assert_blocked(self, function, status=None):
        with self.assertRaises(GitServiceError) as raised:
            function()
        if status is not None:
            self.assertEqual(raised.exception.status, status)
        self.assertFalse(self.runner.pushes)
        return str(raised.exception)

    @staticmethod
    def synthetic_value():
        return "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"

    def test_clean_status_has_safe_destination_without_network(self):
        state = self.service.status(self.repo)
        self.assertTrue(state["is_repository"])
        self.assertTrue(state["clean"])
        self.assertTrue(state["can_publish"])
        self.assertEqual(state["branch"], "main")
        self.assertEqual(state["repository"], "example/synthetic")
        self.assertEqual(state["remote"], REMOTE)
        self.assertFalse(state["can_create_repository"])
        self.assertIsNone(state["ahead"])
        self.assertIsNone(state["behind"])
        self.assertFalse(any(any(arg in ("fetch", "ls-remote", "push") for arg in argv)
                             for argv, _env in self.runner.calls))

    def test_dirty_counts_and_credential_paths_hidden(self):
        self.write("README.md", "Working change.\n")
        self.write("staged.py", "print('synthetic')\n")
        self.git("add", "--", "staged.py")
        self.write("untracked.py", "# Synthetic file\n")
        self.write(".env", "SYNTHETIC_SETTING=1\n")
        state = self.service.status(self.repo)
        self.assertEqual(state["counts"], {"staged": 1, "modified": 1, "untracked": 1})
        self.assertEqual(state["hidden_changes"], 1)
        self.assertNotIn(".env", [item["path"] for item in state["changes"]])
        self.assertFalse(state["can_publish"])
        self.assertFalse(state["clean"])

    def test_tracked_ignored_changes_are_hidden_but_not_clean(self):
        self.write("hidden.txt", "Safe initial content.\n")
        self.write(".gitignore", "hidden.txt\n")
        self.git("add", "-f", "hidden.txt")
        self.commit("Add synthetic ignored source")
        self.write("hidden.txt", "Changed safe content.\n")
        state = self.service.status(self.repo)
        self.assertEqual(state["changes"], [])
        self.assertEqual(state["hidden_changes"], 1)
        self.assertFalse(state["clean"])

    def test_nonrepo_and_nested_registration_cannot_publish_parent(self):
        plain = self.root / "plain"
        plain.mkdir()
        nested = self.repo / "nested"
        nested.mkdir()
        self.assertFalse(self.service.status(plain)["is_repository"])
        self.assertFalse(self.service.status(nested)["is_repository"])
        self.assert_blocked(lambda: self.service.publish(nested, self.confirmation()), 409)

    def test_detached_and_unborn_branches_cannot_publish(self):
        self.git("checkout", "--detach")
        self.assertFalse(self.service.status(self.repo)["can_publish"])
        self.git("checkout", "--orphan", "unborn")
        state = self.service.status(self.repo)
        self.assertIsNone(state["head"])
        self.assertFalse(state["can_publish"])

    def test_local_upstream_counts_without_fetch(self):
        head = self.git("rev-parse", "HEAD").decode().strip()
        self.git("update-ref", "refs/remotes/origin/main", head)
        self.git("config", "branch.main.remote", "origin")
        self.git("config", "branch.main.merge", "refs/heads/main")
        self.write("README.md", "Second source revision.\n")
        self.commit("Second synthetic commit")
        state = self.service.status(self.repo)
        self.assertEqual(state["upstream"], "origin/main")
        self.assertEqual((state["ahead"], state["behind"]), (1, 0))

    def test_unsafe_remote_credentials_and_pushurl_never_exposed(self):
        sensitive = "https://" + self.synthetic_value() + "@github.com/example/synthetic.git"
        self.git("remote", "set-url", "origin", sensitive)
        state = self.service.status(self.repo)
        self.assertIsNone(state["remote"])
        self.assertNotIn(self.synthetic_value(), str(state))
        self.assertFalse(state["can_publish"])
        self.git("remote", "set-url", "origin", REMOTE)
        self.git("config", "remote.origin.pushurl", "https://github.com/example/other.git")
        self.assertIsNone(self.service.status(self.repo)["remote"])

    def test_ssh_destination_is_visible_but_requires_independent_transport_review(self):
        for safe in ("git@github.com:example/synthetic.git", "ssh://git@github.com/example/synthetic.git"):
            self.git("remote", "set-url", "origin", safe)
            state = self.service.status(self.repo)
            self.assertEqual(state["remote"], safe)
            self.assertFalse(state["can_publish"])
        for unsafe in ("file:///tmp/synthetic", "/tmp/synthetic", "https://example.invalid/repo.git",
                       "https://github.com/example/synthetic.git?x=1", "ssh://other@github.com/example/repo.git"):
            self.git("remote", "set-url", "origin", unsafe)
            self.assertFalse(self.service.status(self.repo)["can_publish"])

    def test_applicable_global_rewrite_is_blocked(self):
        self.global_config.write_text('[url "https://example.invalid/"]\n\tinsteadOf = https://github.com/\n')
        state = self.service.status(self.repo)
        self.assertFalse(state["can_publish"])
        self.assertIn("rewrite", state["reason"])

    def test_url_shaped_remote_alias_with_only_pushurl_is_blocked(self):
        self.git("config", "remote." + REMOTE + ".pushurl", "https://github.com/example/other.git")
        state = self.service.status(self.repo)
        self.assertFalse(state["can_publish"])
        self.assertIn("alias", state["reason"])

    def test_unrelated_rewrite_does_not_block(self):
        self.git("config", "url.https://example.invalid/.insteadOf", "synthetic:")
        self.assertTrue(self.service.status(self.repo)["can_publish"])

    def test_custom_transports_and_local_credentials_require_review(self):
        for key, value in (("core.sshCommand", "false"), ("remote.origin.receivepack", "false"),
                           ("http.sslVerify", "false"), ("credential.helper", "synthetic-helper")):
            self.git("config", key, value)
            self.assertFalse(self.service.status(self.repo)["can_publish"])
            self.git("config", "--unset", key)

    def test_worktree_credentials_and_includes_block_publish_and_creation(self):
        self.git("config", "extensions.worktreeConfig", "true")
        included = self.root / "worktree-policy"
        included.write_text("[credential]\n helper = synthetic-untrusted-helper\n")
        for key, value in (("credential.helper", "synthetic-untrusted-helper"),
                           ("include.path", str(included))):
            with self.subTest(setting=key):
                self.git("config", "--worktree", key, value)
                state = self.service.status(self.repo)
                self.assertFalse(state["can_publish"])
                self.assertIn("credential", state["reason"].lower())
                self.assert_blocked(lambda: self.service.publish(self.repo, {
                    **{name: state[name] for name in ("head", "branch", "remote")}, "confirmed": True}))
                self.git("remote", "remove", "origin")
                self.assertFalse(self.service.status(self.repo)["can_create_repository"])
                self.assert_blocked(lambda: self.service.create_repository(self.repo, {
                    "owner": "example", "name": "synthetic", "visibility": "private", "confirmed": True}))
                self.assertFalse(self.runner.creations)
                self.git("remote", "add", "origin", REMOTE)
                self.git("config", "--worktree", "--unset-all", key)

    def test_approved_global_credentials_remain_available_with_worktree_config(self):
        self.git("config", "extensions.worktreeConfig", "true")
        self.global_config.write_text("[credential]\n helper = synthetic-approved-helper\n")
        self.assertTrue(self.service.status(self.repo)["can_publish"])
        self.git("remote", "remove", "origin")
        self.assertTrue(self.service.status(self.repo)["can_create_repository"])
        self.assertFalse(self.runner.pushes)
        self.assertFalse(self.runner.creations)

    def test_local_and_global_clean_filters_are_rejected_before_execution(self):
        self.write(".gitattributes", "README.md filter=synthetic\n")
        self.commit("Declare synthetic driver without executable config")
        self.write("README.md", "Modified source triggering clean conversion.\n")
        marker = self.root / "filter-executed"
        command = "touch '" + str(marker) + "'; cat"
        self.git("config", "filter.synthetic.clean", command)
        self.assert_blocked(lambda: self.service.status(self.repo), 403)
        self.assertFalse(marker.exists())
        self.git("config", "--unset", "filter.synthetic.clean")
        self.global_config.write_text('[filter "synthetic"]\n\tclean = ' + command + '\n')
        self.assert_blocked(lambda: self.service.status(self.repo), 403)
        self.assertFalse(marker.exists())

    def test_process_filter_is_rejected_without_execution(self):
        self.git("config", "filter.synthetic.process", "false")
        self.assert_blocked(lambda: self.service.status(self.repo), 403)

    def test_strict_confirmation_and_stale_snapshot(self):
        data = self.confirmation()
        for invalid in (data | {"confirmed": 1}, data | {"extra": True},
                        data | {"head": "HEAD"}, data | {"branch": "bad..branch"}):
            self.assert_blocked(lambda invalid=invalid: self.service.publish(self.repo, invalid), 400)
        self.write("README.md", "Unreviewed local change.\n")
        self.assert_blocked(lambda: self.service.publish(self.repo, data), 409)

    def test_remote_and_head_mutations_after_scan_block_push(self):
        data = self.confirmation()
        with patch.object(self.service, "_scan", side_effect=lambda *_: self.git("remote", "set-url", "origin", "https://github.com/example/other.git")):
            self.assert_blocked(lambda: self.service.publish(self.repo, data), 409)
        self.git("remote", "set-url", "origin", REMOTE)

        def changed_head(*_args):
            self.write("README.md", "Unreviewed new commit.\n")
            self.commit("Changed synthetic head")

        with patch.object(self.service, "_scan", side_effect=changed_head):
            self.assert_blocked(lambda: self.service.publish(self.repo, data), 409)

    @unittest.skipUnless(shutil.which("gitleaks"), "Reviewed scanner unavailable")
    def test_safe_history_passes_and_push_is_single_exact_sha_without_force(self):
        data = self.confirmation()
        result = self.service.publish(self.repo, data)
        self.assertTrue(result["published"])
        self.assertEqual(len(self.runner.pushes), 1)
        command = self.runner.pushes[0]
        self.assertEqual(command[-2:], [REMOTE, data["head"] + ":refs/heads/main"])
        self.assertIn("--verify", command)
        self.assertIn("--no-follow-tags", command)
        self.assertNotIn("--no-verify", command)
        self.assertNotIn("--force", command)
        self.assertNotIn("--set-upstream", command)
        scans = [argv for argv, _env in self.runner.calls if Path(argv[0]).name == "gitleaks"]
        self.assertTrue(any("--ignore-gitleaks-allow" in argv for argv in scans))

    def test_historical_forbidden_path_is_rejected_before_scanner_reads(self):
        self.write(".env", "SYNTHETIC_SETTING=1\n")
        self.commit("Historical synthetic forbidden path")
        self.git("rm", ".env")
        self.commit("Remove historical forbidden path")
        self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 403)
        self.assertFalse(any(Path(argv[0]).name == "gitleaks" for argv, _env in self.runner.calls))

    def test_historical_symlink_is_blocked(self):
        (self.repo / "linked").symlink_to("README.md")
        self.commit("Synthetic unsupported link")
        self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 403)

    @unittest.skipUnless(shutil.which("gitleaks"), "Reviewed scanner unavailable")
    def test_deleted_secret_and_allow_comment_cannot_bypass_history_scan(self):
        value = self.synthetic_value()
        self.write("docs/setup.md", value + " # gitleaks:" + "allow\n")
        self.commit("Synthetic contaminated source")
        self.write("docs/setup.md", "Safe current document.\n")
        self.commit("Remove synthetic value")
        message = self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 403)
        self.assertNotIn(value, message)

    @unittest.skipUnless(shutil.which("gitleaks"), "Reviewed scanner unavailable")
    def test_attributes_cannot_hide_raw_historical_secrets(self):
        self.write(".gitattributes", "hidden.txt -diff\n")
        self.write("hidden.txt", self.synthetic_value() + "\n")
        self.commit("Synthetic binary-marked historical source")
        self.write("hidden.txt", "Current safe text.\n")
        self.commit("Remove historical synthetic value")
        self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 403)

    @unittest.skipUnless(shutil.which("gitleaks"), "Reviewed scanner unavailable")
    def test_replace_ref_cannot_hide_historical_blob(self):
        initial = self.git("rev-parse", "HEAD").decode().strip()
        self.write("README.md", self.synthetic_value() + "\n")
        self.commit("Synthetic contaminated revision")
        bad = self.git("rev-parse", "HEAD").decode().strip()
        self.write("README.md", "Current safe content.\n")
        self.commit("Current safe synthetic revision")
        self.git("replace", bad, initial)
        self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 403)

    @unittest.skipUnless(shutil.which("gitleaks"), "Reviewed scanner unavailable")
    def test_log_signature_settings_cannot_execute_external_verifier(self):
        marker = self.root / "signature-executed"
        helper = self.root / "signature-helper"
        helper.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\nexit 1\n")
        helper.chmod(0o700)
        head = self.git("rev-parse", "HEAD").decode().strip()
        tree = self.git("rev-parse", "HEAD^{tree}").decode().strip()
        signed = ("tree " + tree + "\nparent " + head + "\n"
                  "author Synthetic Test <test@example.invalid> 1 +0000\n"
                  "committer Synthetic Test <test@example.invalid> 1 +0000\n"
                  "gpgsig -----BEGIN PGP SIGNATURE-----\n synthetic-signature\n"
                  " -----END PGP SIGNATURE-----\n\nSynthetic signed commit.\n").encode()
        oid = self.git("hash-object", "-t", "commit", "-w", "--stdin", data=signed).decode().strip()
        self.git("update-ref", "refs/heads/main", oid)
        self.git("config", "log.showSignature", "true")
        self.git("config", "gpg.program", str(helper))
        self.assertTrue(self.service.publish(self.repo, self.confirmation())["published"])
        self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which("gitleaks"), "Reviewed scanner unavailable")
    def test_commit_message_and_nested_tag_annotation_are_scanned(self):
        self.git("commit", "--allow-empty", "-m", self.synthetic_value())
        self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 403)
        # Move the branch back to the safe commit only inside this disposable synthetic fixture.
        self.git("update-ref", "refs/heads/main", "HEAD~1")
        self.git("tag", "-a", "inner", "-m", self.synthetic_value())
        self.git("tag", "-a", "outer", "inner", "-m", "Safe outer annotation")
        self.git("tag", "-d", "inner")
        self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 403)

    def test_missing_scanner_and_changed_config_fail_closed(self):
        with patch("dashboard.git_service.shutil.which", return_value=None):
            self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 503)
        changed = self.root / "changed-policy.toml"
        changed.write_text('title = "Unreviewed synthetic policy"\n')
        with patch("dashboard.git_service.CONFIG", changed):
            self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 503)

    def test_scanner_environment_drops_ambient_suppression_and_git_injection(self):
        with patch.dict(os.environ, {"GITLEAKS_CONFIG": "synthetic-invalid-path", "GIT_DIR": "synthetic-invalid-path"}):
            env = self.environment(scan=True)
        self.assertNotIn("GITLEAKS_CONFIG", env)
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["GIT_NO_REPLACE_OBJECTS"], "1")

    def test_shallow_and_grafts_cannot_hide_history(self):
        self.git("config", "extensions.worktreeConfig", "true")
        self.write(".git/shallow", self.git("rev-parse", "HEAD").decode())
        self.assertFalse(self.service.status(self.repo)["can_publish"])
        (self.repo / ".git/shallow").unlink()
        self.write(".git/info/grafts", self.git("rev-parse", "HEAD").decode())
        self.assert_blocked(lambda: self.service.publish(self.repo, self.confirmation()), 403)

    def test_failure_output_never_leaks_and_outcome_is_not_claimed_successful(self):
        self.runner.push_code = 1
        with patch.object(self.service, "_scan"):
            with self.assertRaises(GitServiceError) as raised:
                self.service.publish(self.repo, self.confirmation())
        self.assertEqual(raised.exception.status, 502)
        self.assertIn("verify GitHub state", str(raised.exception))

    def creation_data(self, **changes):
        return {"owner": "Synthetic-Owner", "name": "synthetic_repository", "visibility": "private", "confirmed": True} | changes

    def remove_origin(self):
        self.git("remote", "remove", "origin")

    def test_missing_origin_can_create_without_clean_commit_requirement(self):
        self.remove_origin()
        self.write("README.md", "Uncommitted local source remains local.\n")
        state = self.service.status(self.repo)
        self.assertTrue(state["can_create_repository"])
        self.assertFalse(state["clean"])
        self.assertFalse(state["can_publish"])
        self.git("checkout", "--orphan", "unborn")
        self.assertTrue(self.service.status(self.repo)["can_create_repository"])

    def test_explicit_creation_attaches_https_origin_without_upload(self):
        self.remove_origin()
        for visibility in ("private", "public"):
            with self.subTest(visibility=visibility), patch("dashboard.git_service.shutil.which", return_value="/synthetic/gh"):
                result = self.service.create_repository(self.repo, self.creation_data(visibility=visibility))
            self.assertTrue(result["created"])
            self.assertTrue(result["attached"])
            self.assertEqual(result["remote"], "https://github.com/Synthetic-Owner/synthetic_repository.git")
            self.assertEqual(result["visibility"], visibility)
            self.assertEqual(self.runner.creations[-1], ["/synthetic/gh", "repo", "create", "Synthetic-Owner/synthetic_repository", "--" + visibility])
            self.assertFalse(self.runner.pushes)
            self.assertFalse(any(arg in {"--source", "--clone", "--push", "--add-readme"} for arg in self.runner.creations[-1]))
            self.remove_origin()

    def test_creation_uses_isolated_cwd_fixed_host_without_returning_cli_output(self):
        self.remove_origin()
        original = self.runner
        seen = []

        def runner(argv, root, env, **kwargs):
            if argv[1:3] == ["repo", "create"]:
                seen.append(root)
                self.assertNotEqual(root, self.repo)
                self.assertFalse((root / ".git").exists())
                self.assertEqual(env["GH_HOST"], "github.com")
                self.assertEqual(env["GH_PROMPT_DISABLED"], "1")
                self.assertNotIn("GH_DEBUG", env)
                self.assertNotIn("HTTPS_PROXY", env)
                return 0, b"Untrusted command response withheld"
            return original(argv, root, env, **kwargs)

        service = GitService(runner=runner)
        with patch("dashboard.git_service.shutil.which", return_value="/synthetic/gh"):
            result = service.create_repository(self.repo, self.creation_data())
        self.assertTrue(seen)
        self.assertNotIn("Untrusted command", str(result))

    def test_creation_strict_payload_and_names_reject_before_cli(self):
        self.remove_origin()
        invalid = [self.creation_data(confirmed=1), self.creation_data(extra=True),
                   self.creation_data(owner="bad/owner"), self.creation_data(owner="-bad"),
                   self.creation_data(owner="bad--owner"), self.creation_data(owner="a" * 40),
                   self.creation_data(name="../other"), self.creation_data(name="--public"),
                   self.creation_data(name=".."), self.creation_data(name="a" * 101),
                   self.creation_data(name="synthetic.git"), self.creation_data(visibility="internal")]
        for data in invalid:
            with self.subTest(data=data):
                self.assert_blocked(lambda: self.service.create_repository(self.repo, data), 400)
        self.assertFalse(self.runner.creations)

    def test_existing_or_push_only_origin_cannot_create(self):
        with patch("dashboard.git_service.shutil.which", return_value="/synthetic/gh"):
            self.assert_blocked(lambda: self.service.create_repository(self.repo, self.creation_data()), 409)
            self.remove_origin()
            self.git("config", "remote.origin.pushurl", REMOTE)
            self.assertFalse(self.service.status(self.repo)["can_create_repository"])
            self.assert_blocked(lambda: self.service.create_repository(self.repo, self.creation_data()), 409)
        self.assertFalse(self.runner.creations)

    def test_creation_rejects_nonroot_unsafe_transport_and_url_rewrites(self):
        self.remove_origin()
        nested = self.repo / "nested"
        nested.mkdir()
        with patch("dashboard.git_service.shutil.which", return_value="/synthetic/gh"):
            self.assert_blocked(lambda: self.service.create_repository(nested, self.creation_data()), 409)
            for key, value in (("http.proxy", "https://example.invalid/"), ("credential.helper", "false"),
                               ("url.https://example.invalid/.insteadOf", "https://github.com/")):
                self.git("config", key, value)
                self.assertFalse(self.service.status(self.repo)["can_create_repository"])
                self.assert_blocked(lambda: self.service.create_repository(self.repo, self.creation_data()), 409)
                self.git("config", "--unset", key)
        self.assertFalse(self.runner.creations)

    def test_creation_failure_is_unknown_no_attach_and_no_replay(self):
        self.remove_origin()
        self.runner.creation_code = 1
        with patch("dashboard.git_service.shutil.which", return_value="/synthetic/gh"):
            message = self.assert_blocked(lambda: self.service.create_repository(self.repo, self.creation_data()), 502)
        self.assertIn("verify", message)
        self.assertEqual(len(self.runner.creations), 1)
        self.assertTrue(self.service.status(self.repo)["can_create_repository"])

    def test_creation_timeout_is_unknown_no_attach_no_replay(self):
        self.remove_origin()
        self.runner.on_create = lambda: (_ for _ in ()).throw(GitServiceError(503, "Synthetic timeout"))
        with patch("dashboard.git_service.shutil.which", return_value="/synthetic/gh"):
            message = self.assert_blocked(lambda: self.service.create_repository(self.repo, self.creation_data()), 502)
        self.assertIn("unknown", message)
        self.assertEqual(len(self.runner.creations), 1)
        self.assertTrue(self.service.status(self.repo)["can_create_repository"])

    def test_origin_added_during_creation_is_preserved_with_partial_success(self):
        self.remove_origin()
        self.runner.on_create = lambda: self.git("remote", "add", "origin", REMOTE)
        with patch("dashboard.git_service.shutil.which", return_value="/synthetic/gh"):
            result = self.service.create_repository(self.repo, self.creation_data())
        self.assertTrue(result["created"])
        self.assertFalse(result["attached"])
        self.assertIn("do not repeat", result["warning"])
        self.assertEqual(self.git("remote", "get-url", "origin").decode().strip(), REMOTE)
        self.assertEqual(len(self.runner.creations), 1)
        self.assertFalse(self.runner.pushes)

    def test_changed_root_after_creation_is_partial_success_without_attaching(self):
        self.remove_origin()
        moved = self.root / "moved-project"

        def replace_root():
            self.repo.rename(moved)
            self.repo.mkdir()

        self.runner.on_create = replace_root
        with patch("dashboard.git_service.shutil.which", return_value="/synthetic/gh"):
            result = self.service.create_repository(self.repo, self.creation_data())
        self.assertTrue(result["created"])
        self.assertFalse(result["attached"])
        self.assertFalse((self.repo / ".git").exists())
        self.assertEqual(len(self.runner.creations), 1)

    def test_missing_github_cli_fails_before_creation(self):
        self.remove_origin()
        with patch("dashboard.git_service.shutil.which", return_value=None):
            self.assert_blocked(lambda: self.service.create_repository(self.repo, self.creation_data()), 503)
        self.assertFalse(self.runner.creations)

    def test_creation_environment_drops_host_override_debug_proxy_and_git_injection(self):
        with patch.dict(os.environ, {"GH_HOST": "example.invalid", "GH_DEBUG": "api", "GH_REPO": "other/repo",
                                     "GH_HTTP_UNIX_SOCKET": "/synthetic/socket", "HTTPS_PROXY": "https://example.invalid/",
                                     "GIT_DIR": "/synthetic/git"}):
            env = _creation_environment()
        self.assertEqual(env["GH_HOST"], "github.com")
        for name in ("GH_DEBUG", "GH_REPO", "GH_HTTP_UNIX_SOCKET", "HTTPS_PROXY", "GIT_DIR"):
            self.assertNotIn(name, env)


if __name__ == "__main__":
    unittest.main()
