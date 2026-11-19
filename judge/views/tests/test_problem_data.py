from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext as _

from judge.jinja2.format import htmltojs
from judge.models.tests.util import create_problem, create_user


class ProblemDataZipBuilderTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.editor = create_user(username='data_editor', is_staff=True, is_superuser=True)
        cls.problem = create_problem(code='zipbuilder', authors=('data_editor',))

    def _get_page(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('problem_data', args=[self.problem.code]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_zip_builder_ui_is_rendered(self):
        html = self._get_page()
        self.assertIn('btn-build-test-data', html)
        self.assertIn(htmltojs(_('or click here to build zip file')), html)
        self.assertIn('build-test-data-modal', html)
        self.assertIn('build-drop-zone', html)
        self.assertIn('build-files-input', html)
        self.assertIn('build-folder-input', html)
        self.assertIn('btn-build-upload', html)

    def test_zip_is_built_client_side_with_expected_semantics(self):
        html = self._get_page()
        # macOS metadata is filtered out of both uploaded and built archives.
        self.assertIn('shouldIgnoreFile', html)
        self.assertIn('.ds_store', html)
        self.assertIn('__MACOSX/', html)
        self.assertIn("'._'", html)
        self.assertIn(reverse('problem_upload_start', args=[self.problem.code]), html)
        self.assertIn('test-data-upload.js', html)
        self.assertIn("compression: 'DEFLATE'", html)
        self.assertIn("'tests.zip'", html)
        self.assertIn('new DataTransfer()', html)
        # Graceful fallback when the browser lacks DataTransfer.
        self.assertIn("typeof DataTransfer === 'undefined'", html)

    def test_cht_public_testcase_support_survives(self):
        """CHT-specific functionality that must not be lost to the VNOJ port."""
        html = self._get_page()
        # Per-testcase "Public?" column header.
        self.assertIn(_('Public?'), html)
        # "Public all testcases" bulk checkbox and its handler.
        self.assertIn('public-tests', html)
        self.assertIn(_('Public all testcases ?'), html)
        self.assertIn("input[type=checkbox][id$='-public']", html)

    def test_manual_zip_upload_still_available(self):
        html = self._get_page()
        self.assertIn('id_problem-data-zipfile', html)
        self.assertIn(_('Please press this button if you have just updated the zip data'), html)

    def test_checker_and_grader_ui_survive(self):
        html = self._get_page()
        self.assertIn('id_problem-data-checker', html)
        self.assertIn('id_problem-data-grader', html)


class HtmlToJsFilterTestCase(TestCase):
    def test_wraps_in_single_quotes(self):
        self.assertEqual(htmltojs('hello'), "'hello'")

    def test_escapes_quotes_so_translations_cannot_break_out(self):
        self.assertEqual(htmltojs("it's"), "'it\\u0027s'")

    def test_unescapes_html_entities_before_escaping_for_js(self):
        self.assertEqual(htmltojs('Build &amp; Upload ZIP'), "'Build \\u0026 Upload ZIP'")
