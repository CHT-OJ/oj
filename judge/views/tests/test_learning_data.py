import io
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest import mock
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import ProblemData, ProblemDataUpload, ProblemTestCase, problem_data_storage
from judge.models.tests.util import create_problem, create_user
from judge.tasks.test_data import verify_test_upload
from judge.utils.codeforces_polygon import ImportPolygonError, resolve_batch_dependencies
from judge.utils.problem_data import ProblemDataCompiler
from judge.views.problem_data import ProblemDataForm, ProblemDataView


class LearningDataTest(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.editor = create_user('testauthor', is_superuser=True)
        cls.problem = create_problem('batchtask', authors=('testauthor',), is_public=True)
        cls.data = ProblemData.objects.create(problem=cls.problem)

    def test_old_cases_and_valid_dependencies_compile(self):
        for i, row_type in enumerate('SCESCE'):
            case = ProblemTestCase.objects.create(dataset=self.problem, order=i, type=row_type, is_pretest=False,
                                                  points=10, input_file='one.in', output_file='one.out')
            if i == 3:
                case.batch_dependencies = '1, 1'
                case.save()
        init = ProblemDataCompiler(self.problem, self.data, self.problem.cases.order_by('order'),
                                   ['one.in', 'one.out']).make_init()
        first, second = init['test_cases']
        self.assertNotIn('dependencies', first)
        self.assertEqual(second['dependencies'], [1])

    def test_invalid_dependencies_do_not_replace_saved_data(self):
        self.client.force_login(self.editor)
        payload = {
            'problem-data-io_method': 'standard', 'problem-data-grader': 'standard',
            'problem-data-checker': 'standard', 'problem-data-checker_type': 'testlib',
            'cases-TOTAL_FORMS': 2, 'cases-INITIAL_FORMS': 0,
            'cases-0-type': 'S', 'cases-0-points': 10, 'cases-0-order': 0,
            'cases-1-type': 'S', 'cases-1-points': 20, 'cases-1-order': 1,
        }
        with TemporaryDirectory() as folder, self.settings(DMOJ_PROBLEM_DATA_ROOT=folder):
            for dependency in ('0', '2', '3', 'abc', '1,'):
                with self.subTest(dependency=dependency):
                    payload['cases-1-batch_dependencies'] = dependency
                    response = self.client.post(reverse('problem_data', args=[self.problem.code]), payload)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('batch_dependencies', response.context_data['cases_formset'].forms[1].errors)
                    self.assertFalse(self.problem.cases.exists())
            payload.update({'cases-1-batch_dependencies': '1', 'cases-0-is_pretest': 'on'})
            response = self.client.post(reverse('problem_data', args=[self.problem.code]), payload)
            self.assertIn('batch_dependencies', response.context_data['cases_formset'].forms[1].errors)
            self.assertFalse(problem_data_storage.exists(self.problem.code + '/init.yml'))

    def test_zip_members_crc_and_rewind(self):
        buffer = io.BytesIO()
        with ZipFile(buffer, 'w') as archive:
            archive.writestr('folder/', b'')
            archive.writestr('folder/one.in', b'unique-contents')
        for content, expected in [(buffer.getvalue(), ['folder/one.in']),
                                  (buffer.getvalue().replace(b'unique-contents', b'wrong-contents!'), []),
                                  (b'not a zip file', [])]:
            view = ProblemDataView()
            view.request = RequestFactory().post('/', {'problem-data-zipfile': SimpleUploadedFile('a.zip', content)})
            form = ProblemDataForm(instance=self.data)
            self.assertEqual(view.get_valid_files(form, post=True), expected)
            self.assertEqual(getattr(form, 'zip_valid', True), bool(expected))
            self.assertEqual(view.request.FILES['problem-data-zipfile'].tell(), 0)

    def test_polygon_ignored_groups_preserve_transitive_prerequisites(self):
        groups = {'final': {'cases': [3], 'dependencies': ['ignored']},
                  'ignored': {'cases': [2], 'dependencies': ['early']},
                  'early': {'cases': [1], 'dependencies': []}}
        ordered = resolve_batch_dependencies(groups, {k: groups[k] for k in ('final', 'early')})
        self.assertEqual(list(ordered), ['early', 'final'])
        self.assertEqual(ordered['final']['dependencies'], {'early'})
        self.assertEqual(ordered['final']['cases'], [2, 3])
        groups['early']['dependencies'] = ['final']
        with self.assertRaises(ImportPolygonError):
            resolve_batch_dependencies(groups, groups)


class StagedTestUploadTests(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.editor = create_user('zipeditor', user_permissions=('edit_own_problem',))
        cls.admin = create_user('zipadmin', is_superuser=True)
        cls.problem = create_problem('zipstaging', authors=('zipeditor',), is_public=True)

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        staging = self.settings(CHTOJ_UPLOAD_STAGING_ROOT=directory.name)
        staging.enable()
        self.addCleanup(staging.disable)
        self.client.force_login(self.editor)
        self.start_url = reverse('problem_upload_start', args=[self.problem.code])
        self.edit_url = reverse('problem_data', args=[self.problem.code])
        buffer = io.BytesIO()
        with ZipFile(buffer, 'w') as archive:
            archive.writestr('01.in', b'1')
            archive.writestr('01.out', b'2')
        self.content = buffer.getvalue()

    def start(self):
        response = self.client.post(self.start_url, {'name': 'tests.zip', 'size': len(self.content)})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def chunk(self, session, offset, content):
        return self.client.post(session['url'], {'chunk': SimpleUploadedFile('part', content), 'offset': offset})

    def test_retried_chunk_is_idempotent_and_apply_keeps_configuration(self):
        from judge.views.tests.test_problem_download import temp_problem_data_root

        with temp_problem_data_root():
            session = self.start()
            split = len(self.content) // 2
            for _ in range(2):
                self.assertEqual(self.chunk(session, 0, self.content[:split]).json()['offset'], split)
            self.assertEqual(self.client.post(self.edit_url, {'test_upload': session['id']}).status_code, 409)
            with self.captureOnCommitCallbacks(execute=True):
                self.chunk(session, split, self.content[split:])
            self.assertEqual(self.client.get(session['url']).json()['files'], ['01.in', '01.out'])
            payload = {
                'test_upload': session['id'], 'problem-data-io_method': 'standard', 'problem-data-grader': 'standard',
                'problem-data-checker': 'standard', 'problem-data-checker_type': 'testlib',
                'cases-TOTAL_FORMS': 1, 'cases-INITIAL_FORMS': 0, 'cases-0-type': 'C', 'cases-0-order': 0,
                'cases-0-input_file': '01.in', 'cases-0-output_file': '01.out', 'cases-0-points': 1,
            }
            data, _ = ProblemData.objects.get_or_create(problem=self.problem)
            data.zipfile.save('tests.zip', SimpleUploadedFile('tests.zip', b'previous archive'))
            config_name = self.problem.code + '/init.yml'
            problem_data_storage.save(config_name, io.BytesIO(b'previous configuration'))
            # Names exist, yet a zero-point configuration cannot go live.
            invalid = self.client.post(self.edit_url, dict(payload, **{'cases-0-points': 0}))
            self.assertEqual(invalid.status_code, 200)
            self.assertTrue(invalid.context_data['data_form'].non_field_errors())
            self.assertEqual(self.problem.cases.count(), 0)
            with data.zipfile.open() as saved, problem_data_storage.open(config_name) as config:
                self.assertEqual(saved.read(), b'previous archive')
                self.assertEqual(config.read(), b'previous configuration')
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.edit_url, payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 204)
            self.assertEqual(self.client.post(self.edit_url, payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                             .status_code, 204)
            upload = ProblemDataUpload.objects.get(pk=session['id'])
            self.assertEqual(upload.state, 'applied')
            self.assertFalse(upload.path.exists())
            self.assertEqual(self.problem.cases.count(), 1)
            with problem_data_storage.open(self.problem.code + '/tests.zip') as saved:
                self.assertEqual(saved.read(), self.content)
            with problem_data_storage.open(self.problem.code + '/init.yml') as config:
                self.assertIn(b'01.out', config.read())

    def test_background_codec_failure_preserves_live_files(self):
        from judge.views.tests.test_problem_download import temp_problem_data_root

        with temp_problem_data_root():
            data = ProblemData.objects.create(problem=self.problem)
            data.zipfile.save('tests.zip', SimpleUploadedFile('tests.zip', self.content))
            config_name = self.problem.code + '/init.yml'
            problem_data_storage.save(config_name, io.BytesIO(b'live configuration'))
            session = self.start()
            with mock.patch('judge.tasks.test_data.INLINE_EXPANDED_BYTES', 1), \
                    mock.patch.object(verify_test_upload, 'delay') as enqueue:
                with self.captureOnCommitCallbacks(execute=True):
                    self.chunk(session, 0, self.content)
            enqueue.assert_called_once_with(session['id'])
            self.assertEqual(self.client.get(session['url']).json()['state'], 'checking')
            with mock.patch('judge.tasks.test_data.verify_members', side_effect=OSError('codec failure')):
                verify_test_upload(session['id'])
            self.assertEqual(self.client.get(session['url']).json()['state'], 'invalid')
            self.assertEqual(self.client.post(self.edit_url, {'test_upload': session['id']}).status_code, 409)
            with data.zipfile.open() as saved, problem_data_storage.open(config_name) as config:
                self.assertEqual(saved.read(), self.content)
                self.assertEqual(config.read(), b'live configuration')

    def test_editor_expansion_limit_applies_to_both_upload_paths(self):
        with self.settings(CHTOJ_EDITOR_ZIP_MAX_EXPANDED_BYTES=1):
            session = self.start()
            with self.captureOnCommitCallbacks(execute=True):
                self.chunk(session, 0, self.content)
            self.assertEqual(self.client.get(session['url']).json()['state'], 'too_large')
            response = self.client.post(self.edit_url, {
                'problem-data-zipfile': SimpleUploadedFile('tests.zip', self.content),
                'cases-TOTAL_FORMS': 0, 'cases-INITIAL_FORMS': 0,
            })
            self.assertIn('zipfile', response.context_data['data_form'].errors)

    def test_limits_ownership_expiration_and_cleanup(self):
        with self.settings(CHTOJ_EDITOR_ZIP_MAX_BYTES=32):
            self.assertEqual(self.client.post(self.start_url, {'size': 33}).status_code, 413)
            self.client.force_login(self.admin)
            session = self.start()
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(session['url']).status_code, 404)
        self.assertEqual(self.chunk(session, 0, b'1').status_code, 404)
        self.assertEqual(self.client.post(self.edit_url, {'test_upload': session['id']}).status_code, 404)
        self.client.force_login(self.admin)
        self.chunk(session, 0, b'a')
        upload = ProblemDataUpload.objects.get(pk=session['id'])
        ProblemDataUpload.objects.filter(pk=upload.pk).update(updated=timezone.now() - timedelta(days=2))
        self.assertEqual(self.client.get(session['url']).status_code, 404)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(ProblemDataUpload.purge_expired(), 1)
        self.assertFalse(upload.path.exists())
