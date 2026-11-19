import os
import zipfile
from io import BytesIO
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse, JsonResponse
from django.views.generic import View
from django.views.generic.detail import SingleObjectMixin

from judge.models import Problem, problem_data_storage
from judge.utils.url import get_absolute_pdf_url
from judge.views.problem import ProblemMixin


class ProblemDownloadMixin(ProblemMixin):
    """Mixin to check if user can download problem data"""
    def get_object(self, queryset=None):
        problem = super().get_object(queryset)
        user = self.request.user

        # Check if user has permission to download problem data
        # Only editors (authors, curators) can download
        if not problem.is_editable_by(user):
            raise Http404()
        return problem


class DownloadProblemFullPackage(LoginRequiredMixin, ProblemDownloadMixin, SingleObjectMixin, View):
    """Download complete problem package: statement.pdf + tests.zip, all zipped together."""

    def get(self, request, *args, **kwargs):
        problem = self.get_object()

        try:
            buffer = BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:

                self._add_statement(zip_file, problem)
                self._add_pdf(zip_file, problem)

                data_files = getattr(problem, 'data_files', None)
                self._add_file_to_zip(zip_file, data_files, 'zipfile')
                self._add_file_to_zip(zip_file, data_files, 'custom_checker')
                self._add_file_to_zip(zip_file, data_files, 'custom_grader')
                self._add_file_to_zip(zip_file, data_files, 'custom_header')

            response = HttpResponse(buffer.getvalue(), content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename="{problem.code}_package.zip"'
            return response

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    def _add_file_to_zip(self, zip_file, data_files, field_name):
        try:
            if data_files and getattr(data_files, field_name):
                file_path = getattr(data_files, field_name).name
                file_basename = os.path.basename(file_path)

                if problem_data_storage.exists(file_path):
                    with problem_data_storage.open(file_path, 'rb') as f:
                        zip_file.writestr(file_basename, f.read())
                else:
                    zip_file.writestr(f'{field_name}_error.txt', f'File recorded but not found on disk: {file_path}')
        except Exception as e:
            zip_file.writestr(f'{field_name}_error.txt', f'Error processing {field_name}: {str(e)}')

    def _add_pdf(self, zip_file, problem):
        if not problem.pdf_url:
            return
        url = get_absolute_pdf_url(problem.pdf_url)
        prefix = get_absolute_pdf_url(settings.PDF_STATEMENT_UPLOAD_URL_PREFIX).rstrip('/') + '/'
        limit = settings.PDF_STATEMENT_MAX_FILE_SIZE
        try:
            if url.startswith(prefix):
                name = url[len(prefix):]
                if not name.lower().endswith('.pdf') or any(char in name for char in '/\\%?#'):
                    raise ValueError('Invalid statement filename')
                with default_storage.open(os.path.join(settings.PDF_STATEMENT_UPLOAD_MEDIA_DIR, name), 'rb') as pdf:
                    content = pdf.read(limit + 1)
            else:
                address = urlsplit(url)
                if (address.scheme != 'https' or address.username or address.password or
                        address.netloc not in settings.PROBLEM_PACKAGE_PDF_HOSTS):
                    zip_file.writestr('statement_pdf_url.txt', url)
                    return
                with requests.get(url, stream=True, allow_redirects=False, timeout=10) as response:
                    if response.status_code != 200:
                        raise ValueError('PDF host did not return HTTP 200')
                    content = bytearray()
                    for chunk in response.iter_content(65536):
                        content.extend(chunk)
                        if len(content) > limit:
                            break
            if len(content) > limit:
                raise ValueError('PDF exceeds the statement upload limit')
            zip_file.writestr('statement.pdf', content)
        except (OSError, ValueError, requests.RequestException) as error:
            zip_file.writestr('statement_pdf_error.txt', f'Failed to download PDF: {error}')

    def _add_statement(self, zip_file, problem: Problem):
        """Add statement.pdf to the zip file if it exists."""
        try:
            statement = problem.description.strip()
            if statement:
                zip_file.writestr('statement.md', statement)
        except Exception as e:
            zip_file.writestr('statement_md_error.txt', f'Error processing statement: {str(e)}')
