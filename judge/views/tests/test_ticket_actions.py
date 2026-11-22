from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext as _

from judge.models import Problem, Ticket, TicketMessage
from judge.models.tests.util import create_problem, create_user


class TicketTimelineActionTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.author = create_user(username='ticket_author')
        cls.problem = create_problem(code='ticketprob')

    def setUp(self):
        self.ticket = Ticket.objects.create(
            title='Something is wrong',
            user=self.author.profile,
            content_type=ContentType.objects.get_for_model(Problem),
            object_id=self.problem.id,
            is_open=True,
        )
        self.client.force_login(self.author)

    def _post(self, name):
        return self.client.post(reverse(name, args=[self.ticket.id]))

    def _actions(self):
        return self.ticket.messages.exclude(action=TicketMessage.MESSAGE)

    # --- action rows ----------------------------------------------------

    def test_failed_action_insert_rolls_back_status(self):
        with mock.patch.object(TicketMessage, 'save', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                self._post('ticket_close')
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.is_open)
        self.assertFalse(self.ticket.messages.exists())

    def test_close_records_exactly_one_close_action(self):
        response = self._post('ticket_close')
        self.assertEqual(response.status_code, 204)

        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_open)

        actions = list(self._actions())
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, TicketMessage.CLOSE)
        self.assertEqual(actions[0].user_id, self.author.profile.id)
        self.assertEqual(response['X-Ticket-Action-Message-Id'], str(actions[0].id))

    def test_publish_failure_after_commit_does_not_fail_request(self):
        with mock.patch('judge.views.ticket.event') as fake_event:
            fake_event.real = True
            fake_event.post.side_effect = RuntimeError('event daemon down')
            with self.captureOnCommitCallbacks(execute=True):
                response = self._post('ticket_close')
        self.assertEqual(response.status_code, 204)
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_open)
        self.assertEqual(self._actions().count(), 1)

    def test_reopen_records_exactly_one_open_action(self):
        self._post('ticket_close')
        self._post('ticket_open')

        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.is_open)

        actions = list(self._actions())
        self.assertEqual([a.action for a in actions],
                         [TicketMessage.CLOSE, TicketMessage.OPEN])

    def test_setting_same_status_creates_no_duplicate_action(self):
        # Ticket starts open; opening it again must be a no-op.
        self._post('ticket_open')
        self.assertEqual(self._actions().count(), 0)

        self._post('ticket_close')
        self.assertEqual(self._actions().count(), 1)

        # Closing an already-closed ticket must not add a second row.
        self._post('ticket_close')
        self.assertEqual(self._actions().count(), 1)

    def test_action_row_body_may_be_blank(self):
        self._post('ticket_close')
        action = self._actions().get()
        self.assertEqual(action.body, '')
        action.full_clean(exclude=['ticket', 'user'])

    def test_contributive_change_does_not_create_action(self):
        self._post('ticket_good')
        self.assertEqual(self._actions().count(), 0)

    # --- normal messages are unchanged ----------------------------------

    def test_normal_message_defaults_to_message_action(self):
        message = TicketMessage.objects.create(
            ticket=self.ticket, user=self.author.profile, body='hello',
        )
        self.assertEqual(message.action, TicketMessage.MESSAGE)

    @mock.patch('judge.views.ticket.on_new_ticket_message')
    def test_posting_a_reply_creates_a_message_not_an_action(self, mock_task):
        self.client.post(reverse('ticket', args=[self.ticket.id]), {'body': 'a reply'})
        self.assertEqual(self._actions().count(), 0)
        self.assertEqual(self.ticket.messages.filter(action=TicketMessage.MESSAGE).count(), 1)

    # --- rendering ------------------------------------------------------

    def test_action_renders_distinctly_in_the_timeline(self):
        self._post('ticket_close')
        response = self.client.get(reverse('ticket', args=[self.ticket.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ticket-action')
        self.assertContains(response, _('closed this'))

    def test_reopen_renders_reopened_this(self):
        self._post('ticket_close')
        self._post('ticket_open')
        response = self.client.get(reverse('ticket', args=[self.ticket.id]))
        self.assertContains(response, _('reopened this'))

    def test_message_still_renders_as_a_message_section(self):
        TicketMessage.objects.create(ticket=self.ticket, user=self.author.profile, body='plain text')
        response = self.client.get(reverse('ticket', args=[self.ticket.id]))
        self.assertContains(response, 'ticket-message')
        self.assertContains(response, 'plain text')

    def test_ajax_returns_action_markup_and_status_notification(self):
        self._post('ticket_close')
        action = self._actions().get()
        response = self.client.get(reverse('ticket_message_ajax', args=[self.ticket.id]),
                                   {'message': action.id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(_('closed this'), payload['message'])
        self.assertEqual(payload['notification']['body'], _('Status changed'))

    def test_ajax_still_returns_body_for_normal_messages(self):
        message = TicketMessage.objects.create(
            ticket=self.ticket, user=self.author.profile, body='regular body',
        )
        response = self.client.get(reverse('ticket_message_ajax', args=[self.ticket.id]),
                                   {'message': message.id})
        self.assertEqual(response.json()['notification']['body'], 'regular body')


class TicketActionEventPayloadTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.author = create_user(username='event_author')
        cls.problem = create_problem(code='eventprob')

    def setUp(self):
        self.ticket = Ticket.objects.create(
            title='Event ticket',
            user=self.author.profile,
            content_type=ContentType.objects.get_for_model(Problem),
            object_id=self.problem.id,
            is_open=True,
        )
        self.client.force_login(self.author)

    def _capture_events(self, url_name):
        with mock.patch('judge.views.ticket.event') as fake_event:
            fake_event.real = True
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse(url_name, args=[self.ticket.id]))
                fake_event.post.assert_not_called()
        return {call.args[0]: call.args[1] for call in fake_event.post.call_args_list}

    def test_global_tickets_channel_payload_is_unchanged(self):
        posts = self._capture_events('ticket_close')
        payload = posts['tickets']
        self.assertEqual(payload['type'], 'ticket-status')
        self.assertEqual(payload['id'], self.ticket.id)
        self.assertEqual(payload['open'], False)
        self.assertEqual(payload['user'], self.author.profile.id)
        self.assertEqual(payload['title'], 'Event ticket')
        self.assertEqual(payload['assignees'], [])

    def test_per_ticket_channel_emits_unified_action_event(self):
        posts = self._capture_events('ticket_close')
        payload = posts['ticket-%d' % self.ticket.id]
        self.assertEqual(payload['type'], 'ticket-action')
        self.assertEqual(payload['open'], False)
        # The event carries the id of the action row so the client can fetch it.
        action = self.ticket.messages.exclude(action=TicketMessage.MESSAGE).get()
        self.assertEqual(payload['message'], action.id)

    @mock.patch('judge.views.ticket.on_new_ticket_message')
    def test_reply_emits_action_event_without_open_key(self, mock_task):
        with mock.patch('judge.views.ticket.event') as fake_event:
            fake_event.real = True
            self.client.post(reverse('ticket', args=[self.ticket.id]), {'body': 'hi'})
        posts = {call.args[0]: call.args[1] for call in fake_event.post.call_args_list}
        payload = posts['ticket-%d' % self.ticket.id]
        self.assertEqual(payload['type'], 'ticket-action')
        self.assertNotIn('open', payload)
