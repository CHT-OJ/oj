from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from judge.models import Submission
from judge.models.tests.util import create_organization, create_problem, create_user


class OrganizationLearningTest(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    @classmethod
    def setUpTestData(cls):
        cls.teacher = create_user('teacher')
        cls.student = create_user('student')
        cls.a = create_organization('classa', admins=('teacher',))
        cls.b = create_organization('classb')
        cls.a.members.add(cls.student.profile, cls.teacher.profile)
        cls.shared = create_problem('shared', organizations=('classa', 'classb'), is_public=True,
                                    is_organization_private=True)
        cls.other = create_problem('other', organizations=('classb',), is_public=True)
        cls.hidden = create_problem('hidtask', organizations=('classa',), is_public=False)
        cls.tag = cls.a.problem_tags.create(name='DP')
        cls.foreign = cls.b.problem_tags.create(name='Secret Class B')
        cls.foreign.problems.add(cls.shared)

    def test_tag_edit_is_scoped_even_for_a_shared_problem(self):
        self.client.force_login(self.teacher)
        url = reverse('organization_problem_tags', args=[self.a.slug, self.shared.code])
        self.assertNotContains(self.client.get(url), self.foreign.name)
        self.assertEqual(self.client.post(url, {'tags': [self.foreign.pk]}).status_code, 200)
        self.assertEqual(self.client.post(url, {'tags': [self.tag.pk]}).status_code, 302)
        self.assertEqual(set(self.shared.organization_tags.all()), {self.tag, self.foreign})
        self.client.post(url, {})
        self.assertEqual(set(self.shared.organization_tags.all()), {self.foreign})

    def test_tag_list_filter_and_lifecycle(self):
        self.client.force_login(self.teacher)
        manage = reverse('organization_tags', args=[self.a.slug])
        self.client.post(manage, {'name': 'Graphs'})
        self.client.post(manage, {'name': 'Graphs'})
        self.assertEqual(self.a.problem_tags.filter(name='Graphs').count(), 1)
        self.tag.problems.add(self.shared)
        url = reverse('problem_list_organization', args=[self.a.slug])
        for tag, expected in [(self.tag.pk, [self.shared]), (self.foreign.pk, []), ('invalid', [])]:
            page = self.client.get(url, {'tag': tag})
            self.assertEqual(list(page.context_data['problems']), expected)
            self.assertNotContains(page, self.foreign.name)
        self.client.post(manage, {'delete': self.foreign.pk})
        self.assertTrue(self.b.problem_tags.exists())
        self.client.post(manage, {'delete': self.tag.pk})
        self.assertFalse(self.a.problem_tags.filter(pk=self.tag.pk).exists())

    def test_only_admin_can_see_full_ac_on_visible_org_problems(self):
        for problem in [self.shared, self.hidden, self.other]:
            Submission.objects.create(user=self.student.profile, problem=problem,
                                      language=self.student.profile.language, result='AC', case_points=1, case_total=1)
        partial = create_problem('partialtask', organizations=('classa',), is_public=True)
        Submission.objects.create(user=self.student.profile, problem=partial, language=self.student.profile.language,
                                  result='AC', case_points=1, case_total=2)
        url = reverse('organization_solved', args=[self.a.slug, self.student.username])
        self.client.force_login(self.teacher)
        self.assertEqual(list(self.client.get(url).context_data['problems']), [self.shared])
        missing = reverse('organization_solved', args=[self.a.slug, 'unknown'])
        self.assertEqual(self.client.get(missing).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse('organization_tags', args=[self.a.slug]),
                                          {'name': 'denied'}).status_code, 403)
