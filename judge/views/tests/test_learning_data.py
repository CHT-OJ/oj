import io
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.urls import reverse

from judge.models import ProblemData, ProblemTestCase, problem_data_storage
from judge.models.tests.util import create_problem, create_user
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
