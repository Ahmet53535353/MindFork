"""`beyin.py sablon <ad>`: a template named out loud must resolve, or say why it cannot.

A template is a procedure the agent follows, not a note it retrieves. Its whole value is the
guarantee that the *named* procedure was the one opened, so this module refuses loudly instead
of opening whatever resembles the name: a wrong template becomes a wrong action, and an action
on the outside (an issue that stays open) cannot be undone by rewriting the file.
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))

TEMPLATE_DIR = '📋 Templates'
ISSUE_BODY = '# GitHub Issue\n\nDegismezler.\n'


def load_cli():
    spec = importlib.util.spec_from_file_location('beyin_v3_cli', ROOT / 'scripts' / 'beyin_v3.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SablonCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / 'vault'
        (self.vault / TEMPLATE_DIR).mkdir(parents=True)
        (self.vault / TEMPLATE_DIR / 'GithubIssue.md').write_text(ISSUE_BODY, encoding='utf-8')
        (self.vault / TEMPLATE_DIR / 'Kisi.md').write_text('# Kisi\n', encoding='utf-8')
        self.cli = load_cli()

    def sablon(self, *args):
        """Run through the real main(): a wrapper could pass while the command is unwired."""
        argv = ['--vault', str(self.vault), 'sablon', *args]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result, code = self.cli.main(argv, return_result=True)
        return code, (result if result is not None else json.loads(out.getvalue()))

    def test_listing_names_every_template_in_the_folder(self):
        code, result = self.sablon()
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(sorted(result['templates']), ['GithubIssue', 'Kisi'])

    def test_a_named_template_comes_back_whole(self):
        """Truncated output is worse than none: the template is the instruction being followed."""
        code, result = self.sablon('GithubIssue')
        self.assertEqual(code, 0)
        self.assertEqual(result['template'], 'GithubIssue')
        self.assertEqual(result['content'], ISSUE_BODY)

    def test_name_matching_ignores_case_and_separators(self):
        """Ahmet types 'github issue'; the file is GithubIssue.md."""
        for spoken in ('githubissue', 'GitHubIssue', 'github_issue', 'GitHub Issue'):
            with self.subTest(spoken=spoken):
                self.assertEqual(self.sablon(spoken)[1]['template'], 'GithubIssue')

    def test_a_prefix_refuses_instead_of_opening_the_near_miss(self):
        """'github' is not 'GithubIssue'. One turn to retry costs less than the wrong action."""
        for spoken in ('github', 'issue', 'k'):
            with self.subTest(spoken=spoken):
                code, result = self.sablon(spoken)
                self.assertNotEqual(code, 0)
                self.assertIn('GithubIssue', result['message'])

    def test_unknown_name_refuses_and_lists_what_exists(self):
        """A wrong name must stop with a list, never open something that merely resembles it."""
        code, result = self.sablon('issue')
        self.assertNotEqual(code, 0)
        self.assertEqual(result['error'], 'ValueError')
        self.assertIn('GithubIssue', result['message'])
        self.assertIn('Kisi', result['message'])

    def test_missing_template_folder_is_reported_not_silently_empty(self):
        (self.vault / TEMPLATE_DIR).rename(self.vault / 'Templates')
        (self.vault / 'Templates' / 'GithubIssue.md').rename(self.vault / 'Templates' / 'GithubIssue.md')
        code, result = self.sablon()
        self.assertEqual(code, 0, 'a renamed folder is still found by its generic words')

    def test_empty_template_folder_lists_nothing_and_says_so(self):
        for path in (self.vault / TEMPLATE_DIR).glob('*.md'):
            path.unlink()
        code, result = self.sablon()
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['templates'], [])


if __name__ == '__main__':
    unittest.main()