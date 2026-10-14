import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
UPDATE = WORKFLOWS / "update-app.yml"
CI = WORKFLOWS / "ci.yml"
USES = re.compile(r"^\s*(?:- )?uses:\s*(\S+)\s*$", re.MULTILINE)


def read(path):
    return path.read_text(encoding="utf-8")


def job_block(text, name):
    """Lines of the job `name:` (two-space indent under `jobs:`), up to the next job."""
    lines = text.splitlines()
    start = lines.index(f"  {name}:") + 1
    end = next((i for i in range(start, len(lines)) if re.match(r"^  \S", lines[i])), len(lines))
    return "\n".join(lines[start:end])


def run_blocks(text):
    """Each `run:` value, including the lines of a `run: |` block."""
    lines = text.splitlines()
    blocks = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:(.*)$", line)
        if not m:
            continue
        indent = len(m.group(1))
        body = [m.group(2)]
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            body.append(nxt)
        blocks.append("\n".join(body))
    return blocks


class UpdateWorkflowTest(unittest.TestCase):
    def test_manual_trigger_with_app_and_version(self):
        text = read(UPDATE)
        self.assertIn("on:\n  workflow_dispatch:\n    inputs:\n", text)
        for name in ("app", "version"):
            with self.subTest(input=name):
                block = re.search(rf"^      {name}:\n((?:        .*\n)+)", text, re.MULTILINE)
                self.assertIsNotNone(block)
                self.assertIn("required: true", block.group(1))
                self.assertIn("type: string", block.group(1))

    def test_permissions(self):
        text = read(UPDATE)
        self.assertIn("permissions:\n  contents: read\n", text)
        pr = job_block(text, "pr")
        self.assertIn("contents: write", pr)
        self.assertIn("pull-requests: write", pr)
        self.assertNotIn("packages: write", text)

    def test_write_token_never_meets_third_party_actions(self):
        # The linter is a third-party Docker action; a job that can push to main must not run it.
        text = read(UPDATE)
        check, pr = job_block(text, "check"), job_block(text, "pr")
        self.assertIn('python tools/sync_app.py update "$APP" "$VERSION"', check)
        self.assertIn("frenck/action-addon-linter@v2", check)
        self.assertNotIn("contents: write", check)
        self.assertNotIn("pull-requests: write", check)
        self.assertIn("needs: check", pr)
        for ref in USES.findall(pr):
            with self.subTest(ref=ref):
                self.assertTrue(ref.startswith("actions/"), ref)
        # The pull request job rebuilds the folder from the release itself instead of taking files from `check`.
        self.assertIn('python tools/sync_app.py update "$APP" "$VERSION" --skip-image', pr)
        self.assertIn("gh auth setup-git", pr)
        self.assertEqual(text.count("actions/checkout@"), text.count("persist-credentials: false"))

    def test_inputs_reach_the_shell_only_through_env(self):
        text = read(UPDATE)
        self.assertIn("APP: ${{ inputs.app }}", text)
        self.assertIn("VERSION: ${{ inputs.version }}", text)
        blocks = run_blocks(text)
        self.assertTrue(blocks)
        for block in blocks:
            with self.subTest(run=block.strip()[:40]):
                self.assertNotIn("${{ inputs.", block)
                self.assertNotIn("${{ github.event.inputs.", block)

    def test_checks_run_before_the_pull_request(self):
        text = read(UPDATE)
        update = text.index('python tools/sync_app.py update "$APP" "$VERSION"')
        lint = text.index("frenck/action-addon-linter@v2")
        switch = text.index('git switch -c "update/$APP-$VERSION"')
        pr = text.index('gh pr create --title "$APP $VERSION"')
        self.assertLess(update, lint)
        self.assertLess(lint, switch)
        self.assertLess(switch, pr)
        self.assertIn("GH_TOKEN: ${{ github.token }}", text)
        self.assertIn("/releases/tag/v$VERSION", text)

    def test_commits_as_the_actions_bot(self):
        text = read(UPDATE)
        self.assertIn("github-actions[bot]", text)
        self.assertIn("41898282+github-actions[bot]@users.noreply.github.com", text)


class CiWorkflowTest(unittest.TestCase):
    def test_triggers_and_read_only_token(self):
        text = read(CI)
        self.assertIn("  push:\n    branches: [main]", text)
        self.assertIn("  pull_request:", text)
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertNotIn("packages: write", text)
        self.assertNotIn("contents: write", text)

    def test_jobs(self):
        text = read(CI)
        self.assertIn("python -m unittest discover -s tests -v", job_block(text, "tests"))
        self.assertIn("python tools/sync_app.py check", job_block(text, "check"))
        self.assertIn("python tools/sync_app.py list", job_block(text, "apps"))
        lint = job_block(text, "lint")
        for s in ("needs: apps", "if: needs.apps.outputs.apps != '[]'", "fromJSON(needs.apps.outputs.apps)",
                  "frenck/action-addon-linter@v2", "path: ./${{ matrix.app }}"):
            with self.subTest(s=s):
                self.assertIn(s, lint)


class PinnedActionsTest(unittest.TestCase):
    def test_actions_are_pinned_to_a_major_tag(self):
        for path in (UPDATE, CI):
            uses = USES.findall(read(path))
            self.assertTrue(uses, path.name)
            for ref in uses:
                with self.subTest(file=path.name, ref=ref):
                    self.assertRegex(ref, r"^[\w.-]+/[\w.-]+@v\d+$")


if __name__ == "__main__":
    unittest.main()
