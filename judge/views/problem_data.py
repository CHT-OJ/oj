import json
import mimetypes
import os
from contextlib import ExitStack
from itertools import chain
from uuid import UUID
from zipfile import ZipFile

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import FileField
from django.forms import BaseModelFormSet, CharField, ChoiceField, HiddenInput, ModelForm, NumberInput, Select, \
    formset_factory
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from django.utils.text import get_valid_filename
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.cache import never_cache
from django.views.generic import DetailView

from judge.highlight_code import highlight_code
from judge.models import Problem, ProblemData, ProblemDataUpload, ProblemTestCase, Submission, problem_data_storage
from judge.models.problem_data import CUSTOM_CHECKERS, IO_METHODS
from judge.tasks.test_data import CHUNK_BYTES, ZIP_ERRORS, fits_web_worker, member_names, schedule_verification, \
    verify_members
from judge.utils.problem_data import ProblemDataCompiler, ProblemDataError, parse_batch_dependencies
from judge.utils.unicode import utf8text
from judge.utils.views import TitleMixin, add_file_response, generic_message
from judge.views.problem import ProblemMixin
from judge.widgets import Select2Widget

mimetypes.init()
mimetypes.add_type('application/x-yaml', '.yml')


def checker_args_cleaner(self):
    data = self.cleaned_data['checker_args']
    if not data or data.isspace():
        return ''
    try:
        if not isinstance(json.loads(data), dict):
            raise ValidationError(_('Checker arguments must be a JSON object.'))
    except ValueError:
        raise ValidationError(_('Checker arguments is invalid JSON.'))
    return data


def grader_args_cleaner(self):
    data = self.cleaned_data['grader_args']
    if not data or data.isspace():
        return ''
    try:
        if not isinstance(json.loads(data), dict):
            raise ValidationError(_('Grader arguments must be a JSON object'))
    except ValueError:
        raise ValidationError(_('Grader arguments is invalid JSON'))
    return data


class ProblemDataForm(ModelForm):
    io_method = ChoiceField(choices=IO_METHODS, label=gettext_lazy('IO Method'), initial='standard', required=False,
                            widget=Select2Widget(attrs={'style': 'width: 200px'}))
    io_input_file = CharField(max_length=100, label=gettext_lazy('Input from file'), required=False)
    io_output_file = CharField(max_length=100, label=gettext_lazy('Output to file'), required=False)
    checker_type = ChoiceField(choices=CUSTOM_CHECKERS, widget=Select2Widget(attrs={'style': 'width: 200px'}))

    def clean_zipfile(self):
        if getattr(self, 'requires_staging', False):
            raise ValidationError(
                _('For a large ZIP, enable JavaScript and select the archive in the test data editor.'))
        if getattr(self, 'zip_too_large', False):
            raise ValidationError(_('The ZIP exceeds the size limit for this account.'))
        if hasattr(self, 'zip_valid') and not self.zip_valid:
            raise ValidationError(_('Your zip file is invalid!'))
        return self.cleaned_data['zipfile']

    clean_checker_args = checker_args_cleaner
    clean_grader_args = grader_args_cleaner

    class Meta:
        model = ProblemData
        fields = [
            'zipfile',
            'grader', 'io_method', 'io_input_file', 'io_output_file',
            'custom_grader', 'custom_header', 'grader_args',
            'checker', 'custom_checker', 'checker_args', 'checker_type',
            'output_limit',
        ]
        widgets = {
            'checker_args': HiddenInput,
            'checker': Select2Widget(attrs={'style': 'width: 200px'}),
            'grader': Select2Widget(attrs={'style': 'width: 200px'}),
        }
        help_texts = {
            'output_limit': _('Can be left blank. In case the output can be too long (over 20MB), please set this.'),
        }


class ProblemCaseForm(ModelForm):
    clean_checker_args = checker_args_cleaner

    class Meta:
        model = ProblemTestCase
        fields = ('order', 'type', 'input_file', 'output_file', 'points',
                  'is_pretest',  # 'output_limit', 'output_prefix',
                  'checker', 'checker_args', 'generator_args', 'public', 'batch_dependencies')
        widgets = {
            'generator_args': HiddenInput,
            'type': Select(attrs={'style': 'width: 100%'}),
            'points': NumberInput(attrs={'style': 'width: 4em'}),
            # 'output_prefix': NumberInput(attrs={'style': 'width: 4.5em'}),
            # 'output_limit': NumberInput(attrs={'style': 'width: 6em'}),
            'checker_args': HiddenInput,
        }


class ProblemCaseFormSet(formset_factory(ProblemCaseForm, formset=BaseModelFormSet, extra=0, max_num=1,
                                         can_delete=True)):
    model = ProblemTestCase

    def __init__(self, *args, **kwargs):
        self.valid_files = kwargs.pop('valid_files', None)
        super(ProblemCaseFormSet, self).__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        batches = sorted((form for form in self.forms if form.cleaned_data.get('type') == 'S' and
                          not form.cleaned_data.get('DELETE')), key=lambda f: f.cleaned_data['order'])
        pretests = any(form.cleaned_data.get('is_pretest') for form in batches)
        for number, form in enumerate(batches, 1):
            try:
                deps = parse_batch_dependencies(form.cleaned_data['batch_dependencies'], number)
            except ProblemDataError as error:
                form.add_error('batch_dependencies', error.message)
            else:
                if deps and pretests:
                    form.add_error('batch_dependencies',
                                   _('Batch dependencies are not supported for problems with pretest batches.'))

    def _construct_form(self, i, **kwargs):
        form = super(ProblemCaseFormSet, self)._construct_form(i, **kwargs)
        form.valid_files = self.valid_files
        return form


class ProblemManagerMixin(LoginRequiredMixin, ProblemMixin, DetailView):
    def get_object(self, queryset=None):
        problem = super(ProblemManagerMixin, self).get_object(queryset)
        if problem.is_manually_managed:
            raise Http404()
        if self.request.user.is_superuser or problem.is_editable_by(self.request.user):
            return problem
        raise Http404()


@method_decorator(never_cache, name='dispatch')
class ProblemUploadView(ProblemManagerMixin):
    http_method_names = ['get', 'post']

    def get(self, request, upload_id, **kwargs):
        problem = self.get_object()
        upload = get_object_or_404(ProblemDataUpload, pk=upload_id, owner=request.user, problem=problem,
                                   updated__gte=ProblemDataUpload.cutoff())
        result = {'state': upload.state, 'offset': upload.offset}
        if upload.state == 'ready':
            try:
                with ZipFile(upload.path) as archive:
                    result['files'] = member_names(archive)
            except ZIP_ERRORS:
                return JsonResponse({'state': 'invalid'}, status=410)
        return JsonResponse(result)

    def post(self, request, upload_id=None, **kwargs):
        problem = self.get_object()
        if upload_id is None:
            return self.start(request, problem)
        chunk = request.FILES.get('chunk')
        if not chunk or not 0 < chunk.size <= CHUNK_BYTES:
            return JsonResponse({'state': 'invalid_chunk'}, status=400)
        with transaction.atomic():
            upload = get_object_or_404(ProblemDataUpload.objects.select_for_update(), pk=upload_id, problem=problem,
                                       owner=request.user, updated__gte=ProblemDataUpload.cutoff())
            if upload.state == 'uploading' and str(upload.offset) == request.POST.get('offset'):
                if upload.offset + chunk.size > upload.size:
                    return JsonResponse({'state': 'invalid_chunk'}, status=400)
                upload.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with upload.path.open('r+b' if upload.offset else 'wb') as destination:
                    destination.seek(upload.offset)
                    for block in chunk.chunks():
                        destination.write(block)
                    destination.truncate()
                upload.offset += chunk.size
                if upload.offset == upload.size:
                    upload.state = 'checking'
                    transaction.on_commit(lambda: schedule_verification(upload))
                upload.save(update_fields=['offset', 'state', 'updated'])
        return JsonResponse({'state': upload.state, 'offset': upload.offset})

    def start(self, request, problem):
        try:
            size = int(request.POST.get('size', ''))
        except ValueError:
            size = 0
        if not 0 < size < 2 ** 63:
            return JsonResponse({'state': 'invalid'}, status=400)
        if not request.user.is_superuser and size > settings.CHTOJ_EDITOR_ZIP_MAX_BYTES:
            return JsonResponse({'state': 'too_large'}, status=413)
        name = request.POST.get('name', '').replace('\\', '/').rsplit('/', 1)[-1]
        filename = get_valid_filename(name) if name.lower().endswith('.zip') else 'tests.zip'
        if len(filename) + len(problem.code) + 1 > ProblemData._meta.get_field('zipfile').max_length:
            filename = 'tests.zip'
        ProblemDataUpload.purge_expired()
        with transaction.atomic():
            # Keep a bounded number of independent candidates for simultaneous editor tabs.
            Problem.objects.select_for_update().only('pk').get(pk=problem.pk)
            previous = ProblemDataUpload.objects.filter(problem=problem, owner=request.user)
            older = list(previous.order_by('-updated').values_list('pk', flat=True)[2:])
            previous.filter(pk__in=older).delete()
            upload = ProblemDataUpload.objects.create(problem=problem, owner=request.user, filename=filename, size=size)
        return JsonResponse({'url': reverse('problem_upload', args=[problem.code, upload.pk]),
                             'id': str(upload.pk), 'chunk_size': CHUNK_BYTES}, status=201)


class ProblemSubmissionDiff(TitleMixin, ProblemMixin, DetailView):
    template_name = 'problem/submission-diff.html'

    def get_title(self):
        return _('Comparing submissions for {0}').format(self.object.name)

    def get_content_title(self):
        return mark_safe(escape(_('Comparing submissions for {0}')).format(
            format_html('<a href="{1}">{0}</a>', self.object.name, reverse('problem_detail', args=[self.object.code])),
        ))

    def get_object(self, queryset=None):
        problem = super(ProblemSubmissionDiff, self).get_object(queryset)
        if problem.is_editable_by(self.request.user):
            return problem
        raise Http404()

    def get_context_data(self, **kwargs):
        context = super(ProblemSubmissionDiff, self).get_context_data(**kwargs)

        subs = None
        if 'username' in self.request.GET:
            usernames = self.request.GET.getlist('username')
            subs = Submission.objects.filter(problem=self.object, user__user__username__in=usernames)
        elif 'id' in self.request.GET:
            ids = self.request.GET.getlist('id')
            subs = Submission.objects.filter(problem=self.object, id__in=ids)

        if not subs:
            raise Submission.DoesNotExist()

        subs = subs.order_by('id')
        context['submissions'] = subs.filter(language__file_only=False)

        # If we have associated data we can do better than just guess
        data = ProblemTestCase.objects.filter(dataset=self.object, type='C')
        if data:
            num_cases = data.count()
        else:
            num_cases = subs.first().test_cases.count()
        context['num_cases'] = num_cases
        return context

    def get(self, request, *args, **kwargs):
        try:
            return super(ProblemSubmissionDiff, self).get(request, *args, **kwargs)
        except Submission.DoesNotExist:
            return generic_message(self.request, _('No such submissions'), _('Could not find any submissions.'))


class ProblemDataView(TitleMixin, ProblemManagerMixin):
    template_name = 'problem/data.html'

    def get_title(self):
        return _('Editing data for {0}').format(self.object.name)

    def get_content_title(self):
        return mark_safe(escape(_('Editing data for %s')) % (
            format_html('<a href="{1}">{0}</a>', self.object.name,
                        reverse('problem_detail', args=[self.object.code]))))

    def get_data_form(self, post=False):
        return ProblemDataForm(data=self.request.POST if post else None, prefix='problem-data',
                               files=self.request.FILES if post else None,
                               instance=ProblemData.objects.get_or_create(problem=self.object)[0])

    def get_case_formset(self, files, post=False):
        return ProblemCaseFormSet(data=self.request.POST if post else None, prefix='cases', valid_files=files,
                                  queryset=ProblemTestCase.objects.filter(dataset_id=self.object.pk).order_by('order'))

    def get_valid_files(self, form, post=False):
        upload = self.request.FILES.get('problem-data-zipfile') if post else None
        if post and not upload and 'problem-data-zipfile-clear' in self.request.POST:
            return []
        if (upload and upload.size > settings.CHTOJ_EDITOR_ZIP_MAX_BYTES and not self.request.user.is_superuser):
            form.zip_too_large = True
            return []
        archive = upload or form.instance.zipfile
        if not archive:
            return []
        try:
            with ZipFile(upload or archive.path) as zipped:
                if upload and not getattr(self, 'verified_upload', None):
                    expanded = sum(entry.file_size for entry in zipped.infolist())
                    if expanded > settings.CHTOJ_EDITOR_ZIP_MAX_EXPANDED_BYTES and not self.request.user.is_superuser:
                        form.zip_too_large = True
                        return []
                    if not fits_web_worker(zipped):
                        form.requires_staging = True
                        return []
                    verify_members(zipped)
                return member_names(zipped)
        except ZIP_ERRORS:
            form.zip_valid = False
            return []
        finally:
            if upload:
                upload.seek(0)

    def get_context_data(self, **kwargs):
        context = super(ProblemDataView, self).get_context_data(**kwargs)
        if 'data_form' not in context:
            context['data_form'] = self.get_data_form()
            valid_files = context['valid_files'] = self.get_valid_files(context['data_form'])
            context['cases_formset'] = self.get_case_formset(valid_files)
        context['valid_files'] = set(context['valid_files'])
        context['all_case_forms'] = chain(context['cases_formset'], [context['cases_formset'].empty_form])

        if self.request.user.has_perm('judge.create_mass_testcases'):
            context['testcase_limit'] = 9999
            context['testcase_soft_limit'] = 9999
        else:
            context['testcase_limit'] = settings.VNOJ_TESTCASE_HARD_LIMIT
            context['testcase_soft_limit'] = settings.VNOJ_TESTCASE_SOFT_LIMIT
        return context

    def check_valid(self, data_form, cases_formset):
        data_valid = data_form.is_valid()
        cases_valid = cases_formset.is_valid()
        if not data_valid or not cases_valid:
            return False
        if self.request.FILES.get('problem-data-zipfile') and not data_form.instance.generator:
            filenames = set(cases_formset.valid_files)
            for form in cases_formset.forms:
                row = form.cleaned_data
                if row.get('type') == 'C' and not row.get('DELETE'):
                    for field in ('input_file', 'output_file'):
                        if row[field] not in filenames:
                            form.add_error(field, _('File not found in the uploaded ZIP.'))
            if not cases_formset.is_valid():
                return False
        number_of_cases = cases_formset.total_form_count() - len(cases_formset.deleted_forms)
        if number_of_cases > settings.VNOJ_TESTCASE_HARD_LIMIT and \
           not self.request.user.has_perm('judge.create_mass_testcases'):
            error = ValidationError(
                _('Too many testcases, number of testcases must not exceed %s') % settings.VNOJ_TESTCASE_HARD_LIMIT,
                code='too_many_testcases',
            )
            cases_formset._non_form_errors.append(error)
            return False
        return True

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        self.object = self.get_object(Problem.objects.select_for_update())
        with ExitStack() as files:
            token = request.POST.get('test_upload')
            self.verified_upload = None
            if token:
                try:
                    upload_id = UUID(token)
                except ValueError:
                    raise Http404()
                candidates = ProblemDataUpload.objects.select_for_update().filter(
                    updated__gte=ProblemDataUpload.cutoff(),
                )
                upload = get_object_or_404(candidates, pk=upload_id, owner=request.user, problem=self.object)
                if upload.state == 'applied':
                    return self.saved_response()
                if upload.state != 'ready' or request.FILES.get('problem-data-zipfile'):
                    return HttpResponse(_('Please select the ZIP again.'), status=409)
                try:
                    source = files.enter_context(upload.path.open('rb'))
                except FileNotFoundError:
                    return HttpResponse(_('Please select the ZIP again.'), status=410)
                candidate = UploadedFile(source, name=upload.filename, size=upload.size)
                candidate.verified_path = upload.path
                request.FILES['problem-data-zipfile'] = candidate
                self.verified_upload = upload
            return self.save_forms()

    def saved_response(self):
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return HttpResponse(status=204)
        return HttpResponseRedirect(self.request.get_full_path())

    def save_forms(self):
        problem = self.object
        data_form = self.get_data_form(post=True)
        valid_files = self.get_valid_files(data_form, post=True)
        cases_formset = self.get_case_formset(valid_files, post=True)
        if self.check_valid(data_form, cases_formset):
            try:
                with transaction.atomic():
                    self.save_configuration(problem, data_form, cases_formset, valid_files)
            except ProblemDataError as error:
                data_form.add_error(None, error.message)
            else:
                if self.verified_upload:
                    self.verified_upload.state = 'applied'
                    self.verified_upload.save(update_fields=['state', 'updated'])
                    self.verified_upload.remove_file_after_commit()
                return self.saved_response()
        return self.render_to_response(self.get_context_data(
            data_form=data_form, cases_formset=cases_formset,
            valid_files=valid_files, staged_upload=self.verified_upload,
        ))

    def save_configuration(self, problem, data_form, cases_formset, valid_files):
        data = data_form.save(commit=False)
        for case in cases_formset.save(commit=False):
            case.dataset_id = problem.pk
            case.save()
        for case in cases_formset.deleted_objects:
            case.delete()
        compiler = ProblemDataCompiler(problem, data, problem.cases.order_by('order'), set(valid_files))
        if self.request.FILES.get('problem-data-zipfile'):
            # Compile against the final storage names before overwriting a working archive.
            with ExitStack() as pending:
                for field in data._meta.fields:
                    if isinstance(field, FileField):
                        attachment = getattr(data, field.name)
                        if attachment and not attachment._committed:
                            pending.callback(setattr, attachment, 'name', attachment.name)
                            attachment.name = field.generate_filename(data, attachment.name)
                init = compiler.make_init()
            compiler.save_init(init)
        else:
            data_form.save()
            compiler.compile()

    put = post


@login_required
def problem_data_file(request, problem, path):
    object = get_object_or_404(Problem, code=problem)
    if not object.is_editable_by(request.user):
        raise Http404()

    problem_dir = problem_data_storage.path(problem)
    if os.path.commonpath((problem_data_storage.path(os.path.join(problem, path)), problem_dir)) != problem_dir:
        raise Http404()

    response = HttpResponse()

    if hasattr(settings, 'DMOJ_PROBLEM_DATA_INTERNAL'):
        url_path = '%s/%s/%s' % (settings.DMOJ_PROBLEM_DATA_INTERNAL, problem, path)
    else:
        url_path = None

    try:
        add_file_response(request, response, url_path, os.path.join(problem, path), problem_data_storage)
    except IOError:
        raise Http404()

    response['Content-Type'] = 'application/octet-stream'
    return response


@login_required
def problem_init_view(request, problem):
    problem = get_object_or_404(Problem, code=problem)
    if not problem.is_editable_by(request.user):
        raise Http404()

    try:
        with problem_data_storage.open(os.path.join(problem.code, 'init.yml'), 'rb') as f:
            data = utf8text(f.read()).rstrip('\n')
    except IOError:
        raise Http404()

    return render(request, 'problem/yaml.html', {
        'raw_source': data, 'highlighted_source': highlight_code(data, 'yaml'),
        'title': _('Generated init.yml for %s') % problem.name,
        'content_title': mark_safe(escape(_('Generated init.yml for %s')) % (
            format_html('<a href="{1}">{0}</a>', problem.name,
                        reverse('problem_detail', args=[problem.code])))),
    })
