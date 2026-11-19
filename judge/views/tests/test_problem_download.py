import contextlib
import io
import shutil
import tempfile
import zipfile
from unittest import mock

import requests
from django.test import TestCase, override_settings
from django.urls import reverse

from judge.models import ProblemData, problem_data_storage
from judge.models.tests.util import create_problem, create_user


@contextlib.contextmanager
def temp_problem_data_root():
    """Point problem_data_storage at a throwaway directory.

    ProblemDataStorage captures DMOJ_PROBLEM_DATA_ROOT at construction time, so
    override_settings cannot reach it; swap the location and bust the cached
    properties instead.
    """
    tmp = tempfile.mkdtemp()
    previous = problem_data_storage._location
    problem_data_storage._location = tmp
    for cached in ('location', 'base_location'):
        problem_data_storage.__dict__.pop(cached, None)
    try:
        yield tmp
    finally:
        problem_data_storage._location = previous
        for cached in ('location', 'base_location'):
            problem_data_storage.__dict__.pop(cached, None)
        shutil.rmtree(tmp, ignore_errors=True)


class ProblemPackageDownloadTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.editor = create_user(
            username='pkg_editor',
            user_permissions=('edit_own_problem',),
        )
        cls.outsider = create_user(username='pkg_outsider')
        cls.problem = create_problem(
            code='pkgprob',
            description='# Statement body',
            authors=('pkg_editor',),
        )

    def _url(self, code=None):
        return reverse('problem_download_full_package', args=[code or self.problem.code])

    def _download(self):
        self.client.force_login(self.editor)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        return response

    def _archive(self, response):
        return zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))

    def _names(self, response):
        return set(self._archive(response).namelist())

    # --- authorization -------------------------------------------------

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login', response['Location'])

    def test_non_editor_gets_404_and_no_package(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(response['Content-Type'], 'application/zip')

    def test_non_editor_cannot_learn_problem_exists(self):
        """A missing problem and a forbidden problem look the same."""
        self.client.force_login(self.outsider)
        existing = self.client.get(self._url())
        missing = self.client.get(self._url('does-not-exist'))
        self.assertEqual(existing.status_code, missing.status_code)

    def test_editor_can_download(self):
        response = self._download()
        self.assertEqual(response['Content-Type'], 'application/zip')

    # --- response shape ------------------------------------------------

    def test_filename_is_problem_code_package_zip(self):
        response = self._download()
        self.assertEqual(response['Content-Disposition'],
                         'attachment; filename="pkgprob_package.zip"')

    def test_statement_md_included_when_description_present(self):
        response = self._download()
        archive = self._archive(response)
        self.assertIn('statement.md', archive.namelist())
        self.assertEqual(archive.read('statement.md').decode(), '# Statement body')

    def test_statement_md_omitted_when_description_blank(self):
        blank = create_problem(code='blankprob', description='   ', authors=('pkg_editor',))
        self.client.force_login(self.editor)
        response = self.client.get(self._url(blank.code))
        self.assertNotIn('statement.md', self._names(response))

    # --- data files ----------------------------------------------------

    def test_data_files_are_included(self):
        with temp_problem_data_root():
            data = ProblemData.objects.create(problem=self.problem)
            for field, name, content in (
                ('zipfile', 'pkgprob/tests.zip', b'ZIPDATA'),
                ('custom_checker', 'pkgprob/checker.cpp', b'CHECKER'),
                ('custom_grader', 'pkgprob/grader.cpp', b'GRADER'),
                ('custom_header', 'pkgprob/header.h', b'HEADER'),
            ):
                problem_data_storage.save(name, io.BytesIO(content))
                setattr(getattr(data, field), 'name', name)
            data.save()

            response = self._download()
            archive = self._archive(response)
            self.assertEqual(archive.getinfo('tests.zip').compress_type, zipfile.ZIP_STORED)
            self.assertEqual(archive.read('tests.zip'), b'ZIPDATA')
            self.assertEqual(archive.read('checker.cpp'), b'CHECKER')
            self.assertEqual(archive.read('grader.cpp'), b'GRADER')
            self.assertEqual(archive.read('header.h'), b'HEADER')

    def test_missing_file_yields_error_entry_not_a_failed_package(self):
        with temp_problem_data_root():
            data = ProblemData.objects.create(problem=self.problem)
            data.zipfile.name = 'pkgprob/vanished.zip'
            data.save()

            response = self._download()
            archive = self._archive(response)
            names = set(archive.namelist())
            # The package still builds, with an error note in place of the file.
            self.assertIn('zipfile_error.txt', names)
            self.assertNotIn('vanished.zip', names)
            self.assertIn('statement.md', names)

            self.assertIn('File recorded but not found on disk',
                          archive.read('zipfile_error.txt').decode())

    # --- pdf -----------------------------------------------------------

    @override_settings(PROBLEM_PACKAGE_PDF_HOSTS=('example.invalid',))
    def test_pdf_is_fetched_and_stored_as_statement_pdf(self):
        self.problem.pdf_url = 'https://example.invalid/statement.pdf'
        self.problem.save(update_fields=['pdf_url'])

        fake = mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.status_code = 200
        fake.iter_content.return_value = [b'%PDF-1.4 fake']
        with mock.patch('judge.views.problem_download.requests.get', return_value=fake) as get:
            response = self._download()

        get.assert_called_once()
        archive = self._archive(response)
        self.assertEqual(archive.read('statement.pdf'), b'%PDF-1.4 fake')
        self.assertNotIn('statement_pdf_error.txt', archive.namelist())

    @override_settings(PROBLEM_PACKAGE_PDF_HOSTS=('example.invalid',))
    def test_pdf_failure_yields_error_entry_not_a_failed_package(self):
        self.problem.pdf_url = 'https://example.invalid/statement.pdf'
        self.problem.save(update_fields=['pdf_url'])

        with mock.patch('judge.views.problem_download.requests.get',
                        side_effect=requests.exceptions.ConnectionError('boom')):
            response = self._download()

        archive = self._archive(response)
        self.assertIn('statement_pdf_error.txt', archive.namelist())
        self.assertIn('Failed to download PDF', archive.read('statement_pdf_error.txt').decode())
        # The rest of the package survived the PDF failure.
        self.assertIn('statement.md', archive.namelist())

    def test_external_pdf_link_is_kept_without_a_server_request(self):
        self.problem.pdf_url = 'https://external.example/statement.pdf'
        self.problem.save()
        with mock.patch('judge.views.problem_download.requests.get') as fetch:
            archive = self._archive(self._download())
        fetch.assert_not_called()
        self.assertEqual(archive.read('statement_pdf_url.txt').decode(), self.problem.pdf_url)

    def test_no_pdf_entry_when_problem_has_no_pdf_url(self):
        with mock.patch('judge.views.problem_download.requests.get') as get:
            response = self._download()
        get.assert_not_called()
        names = self._names(response)
        self.assertNotIn('statement.pdf', names)
        self.assertNotIn('statement_pdf_error.txt', names)

    # --- contents are limited to what VNOJ packages ---------------------

    def test_package_contains_only_expected_entries(self):
        response = self._download()
        self.assertEqual(self._names(response), {'statement.md'})
