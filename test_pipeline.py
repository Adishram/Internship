"""Offline regression tests and a small known-label fixture generator.

All provider responses are mocked at the HTTP boundary. These tests establish
mapping, isolation and failure handling, not real-model classification accuracy.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
import requests

from pipeline import (ANSWER, DECISION, Chat, Client, PipelineError, classify, export,
                      extract, image_for_process, load_targets, selected_sections)


def fixture(path):
    """Create mixed-page evidence, a cross-page continuation and known edge cases."""
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 24, 24), False)
    pix.clear_with(90)
    png = pix.tobytes('png')

    def text(page, y, value):
        """Keep fixture lines separated and large enough for stable extraction."""
        page.insert_text((40, y), value, fontsize=11)

    def section(page, y, name, close=True):
        """Add one process's original text and an embedded raster image."""
        text(page, y, f'Service start evidence - {name}')
        text(page, y + 20, f'Service: {name}; operation: start; state: active')
        page.insert_image(pymupdf.Rect(40, y + 30, 120, y + 80), stream=png)
        text(page, y + 100, f'Evidence capture for {name}')
        if close:
            text(page, y + 120, 'Evidence section closed')

    p = doc.new_page()
    section(p, 50, 'alpha-api')
    section(p, 300, 'beta-api', close=False)
    text(p, 770, 'Repeated table row: keep this evidence')
    p = doc.new_page()
    text(p, 50, 'Service beta-api stop verification: inactive')
    text(p, 70, 'Repeated table row: keep this evidence')
    text(p, 90, 'Evidence section closed')
    section(p, 150, 'alpha-api and beta-api')
    section(p, 400, 'other-api')
    p = doc.new_page()
    p.insert_image(pymupdf.Rect(40, 40, 120, 100), stream=png)
    text(p, 130, 'Evidence section closed')
    text(p, 200, 'Service start evidence - unknown identity')
    text(p, 220, 'No service name available')
    text(p, 250, 'Evidence section closed')
    doc.save(path)
    doc.close()


def response(result, status=200):
    """Provide the minimal requests.Response surface used by the backend."""
    from unittest.mock import Mock
    obj = Mock(status_code=status)
    obj.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}
    return obj


def router(method, url, **kwargs):
    """Deterministic test oracle; inspect actual serialized HTTP request bodies."""
    body = kwargs['json']
    assert all(isinstance(m['content'], str) for m in body['messages'])
    serialized = json.dumps(body)
    assert 'data:image' not in serialized and 'image_url' not in serialized
    assert 'base64' not in serialized and '/Users/' not in serialized
    payload = json.loads(body['messages'][1]['content'])
    evidence = payload['evidence']
    text = '\n'.join(b['text'] for b in evidence['blocks'])
    if 'alpha-api' in text and 'beta-api' in text:
        status, target = 'mixed', None
    elif 'alpha-api' in text:
        status, target = 'assigned', 'alpha-api'
    elif 'beta-api' in text:
        status, target = 'assigned', 'beta-api'
    elif 'other-api' in text:
        status, target = 'unmatched', None
    else:
        status, target = 'uncertain', None
    return response(dict(section_id=evidence['section_id'], status=status, target=target,
                         confidence=0.9, reason='Controlled mock response; not a real model assessment.'))


class PipelineTests(unittest.TestCase):
    """Exercise real PDFs and real client validation with mocked HTTP only."""

    def setUp(self):
        """Use disposable paths so tests never alter the supplied dataset."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / 'fixture.pdf'
        fixture(self.pdf)
        self.run = self.root / 'run'
        self.data = extract(self.pdf, self.run)
        self.targets = ['alpha-api', 'beta-api']
        self.client = Client('http://localhost:3001/v1', 'test-key', 'mock', consent=True)

    def routed(self):
        """Run the classifier using the deterministic HTTP oracle."""
        with patch('pipeline.requests.request', side_effect=router):
            return classify(self.data, self.targets, self.client, self.run)

    def chat(self):
        """Create chat against actual independently exported process HTML files."""
        decisions = self.routed()
        manifest = export(self.data, self.targets, decisions, self.run)
        return Chat(self.data, decisions, self.client, self.run, manifest['documents'])

    def answer(self, target='alpha-api'):
        """Construct a valid quote citation from the actual extracted line ID."""
        s = selected_sections(self.data, self.routed(), target)[0]
        b = next(b for b in s['blocks'] if 'state: active' in b['text'])
        return dict(answer=f'{target} was active.', abstain=False,
                    citations=[dict(section_id=s['id'], block_id=b['id'], page=b['page'], quote=b['text'])])

    def test_pdf_paths_accept_typed_quoted_and_dragged_spaces(self):
        """A single path with spaces works literally or in common terminal quoting."""
        from cli import pdf_path
        path = self.root / 'my evidence.pdf'
        path.write_bytes(self.pdf.read_bytes())
        for value in (str(path), '"' + str(path) + '"', "'" + str(path) + "'",
                      str(path).replace(' ', r'\ ')):
            self.assertEqual(pdf_path(value), path)
        for value in ('', str(self.root), str(self.root / 'missing.pdf')):
            with self.assertRaises(PipelineError):
                pdf_path(value)
        with self.assertRaises(PipelineError):
            extract(self.root, self.root / 'unsupported')

    def test_preview_is_local_and_handles_corrupt_pdf(self):
        """Preview real content without HTTP; invalid files fail before model setup."""
        from cli import preview_pdf
        with patch('pipeline.requests.request') as request, patch('cli.say') as say, \
                patch('cli.supports_images', return_value=False), patch('cli.sys.stdin.isatty', return_value=False):
            preview_pdf(self.pdf)
            printed = '\n'.join(str(call.args[0]) for call in say.call_args_list)
            self.assertIn('Pages: 3', printed)
            self.assertIn('alpha-api', printed)
        request.assert_not_called()
        broken = self.root / 'broken.pdf'
        broken.write_text('invalid PDF')
        with self.assertRaises(PipelineError):
            preview_pdf(broken)

    def test_end_to_end_layout_images_and_no_cross_process_text(self):
        decisions = self.routed()
        manifest = export(self.data, self.targets, decisions, self.run)
        alpha = (self.run / manifest['documents']['alpha-api']).read_text()
        beta = (self.run / manifest['documents']['beta-api']).read_text()
        self.assertIn('alpha-api', alpha)
        self.assertNotIn('beta-api', alpha)
        self.assertIn('beta-api', beta)
        self.assertNotIn('alpha-api', beta)
        self.assertIn('data:image/png;base64,', alpha)
        self.assertIn('position:absolute', alpha)
        self.assertIn('data-block=', alpha)
        self.assertEqual(len(manifest['decisions']), len(self.data['sections']))
        self.assertTrue((self.run / 'index.html').is_file())
        self.assertEqual([d['status'] for d in decisions],
                         ['assigned', 'assigned', 'mixed', 'unmatched', 'uncertain', 'uncertain'])

    def test_cross_page_continuation_and_repeated_rows(self):
        section = self.data['sections'][1]
        self.assertIsNone(section['boundary'])
        self.assertEqual({b['page'] for b in section['blocks']}, {1, 2})
        self.assertEqual(sum('Repeated table row' in b['text'] for b in section['blocks']), 2)

    def test_original_offsets_and_gap(self):
        a = self.root / 'slices'
        a.mkdir()
        with pymupdf.open(self.pdf) as doc:
            doc.save(a / 'Sample_pages_11-13.pdf')
        data = extract(a / 'Sample_pages_11-13.pdf', self.root / 'offset')
        self.assertEqual([p['number'] for p in data['pages']], [11, 12, 13])
        with pymupdf.open(self.pdf) as doc:
            first = pymupdf.open()
            first.insert_pdf(doc, from_page=0, to_page=0)
            first.save(self.root / 'Single_pages_11-11.pdf')
            first.close()
        incomplete = extract(self.root / 'Single_pages_11-11.pdf', self.root / 'partial')
        self.assertIsNotNone(incomplete['sections'][1]['boundary'])

    def test_stable_ids_and_all_blocks_accounted_for(self):
        second = extract(self.pdf, self.root / 'again')
        self.assertEqual([s['id'] for s in self.data['sections']], [s['id'] for s in second['sections']])
        actual = [b['id'] for s in self.data['sections'] for b in s['blocks']] + [b['id'] for b in self.data['furniture']]
        expected = [b['id'] for p in self.data['pages'] for b in p['blocks']]
        self.assertCountEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))

    def test_orphan_withheld_without_api_call(self):
        data = dict(self.data, sections=[self.data['sections'][4]], furniture=[])
        from pipeline import html_document
        (self.run / 'source.html').write_text(html_document('Orphan', data, data['sections'], self.run))
        with patch('pipeline.requests.request') as request:
            result = classify(data, self.targets, self.client, self.run)
        request.assert_not_called()
        self.assertEqual(result[0]['status'], 'uncertain')

    def test_images_local_and_process_isolated(self):
        decisions = self.routed()
        beta = selected_sections(self.data, decisions, 'beta-api')[0]
        image = next(b for b in beta['blocks'] if b['kind'] == 'image')
        with patch('pipeline.requests.request') as request:
            path = image_for_process(self.data, decisions, 'beta-api', image['id'], self.run)
            self.assertTrue(path.is_file())
            with self.assertRaises(PipelineError):
                image_for_process(self.data, decisions, 'alpha-api', image['id'], self.run)
            path.unlink()
            with self.assertRaisesRegex(PipelineError, 'missing'):
                image_for_process(self.data, decisions, 'beta-api', image['id'], self.run)
        request.assert_not_called()

    def test_chat_history_and_text_only_process_isolation(self):
        chat = self.chat()
        with patch('pipeline.requests.request', return_value=response(self.answer())) as request:
            result = chat.ask('alpha-api', 'Is alpha active?')
            self.assertFalse(result['abstain'])
            payload = request.call_args.kwargs['json']
            self.assertNotIn('beta-api', json.dumps(payload))
            self.assertNotIn('data:image', json.dumps(payload))
            self.assertNotIn('images/', json.dumps(payload))
        with patch('pipeline.requests.request', return_value=response(self.answer('beta-api'))) as request:
            chat.ask('beta-api', 'Is beta active?')
            self.assertNotIn('Is alpha active?', json.dumps(request.call_args.kwargs['json']))
        self.assertEqual(len(chat.histories), 2)

    def test_foreign_quote_page_and_empty_citations_rejected(self):
        chat = self.chat()
        cases = [self.answer('beta-api'), self.answer(), self.answer(), self.answer()]
        cases[1]['citations'][0]['quote'] = 'fabricated'
        cases[2]['citations'][0]['page'] = 99
        cases[3]['citations'] = []
        for answer in cases:
            with self.subTest(answer=answer), patch('pipeline.requests.request', return_value=response(answer)):
                self.assertTrue(chat.ask('alpha-api', 'What happened?')['abstain'])
        self.assertEqual(chat.histories, {})

    def test_model_abstention_does_not_display_unsupported_answer(self):
        chat = self.chat()
        with patch('pipeline.requests.request', return_value=response(dict(answer='invented claim', abstain=True, citations=[]))):
            result = chat.ask('alpha-api', 'Unknown question')
        self.assertTrue(result['abstain'])
        self.assertNotIn('invented', result['answer'])

    def test_classification_requires_original_source_html(self):
        """Classification fails before HTTP if the source HTML is missing or changed."""
        path = self.run / 'source.html'
        path.write_text(path.read_text().replace('Service: alpha-api;', 'Service: changed;'))
        with patch('pipeline.requests.request') as request, self.assertRaisesRegex(PipelineError, 'modified'):
            classify(self.data, self.targets, self.client, self.run)
        request.assert_not_called()
        path.unlink()
        with patch('pipeline.requests.request') as request, self.assertRaisesRegex(PipelineError, 'Cannot read'):
            classify(self.data, self.targets, self.client, self.run)
        request.assert_not_called()

    def test_chat_requires_selected_html_without_memory_fallback(self):
        """Missing or modified selected HTML cannot silently use in-memory evidence."""
        chat = self.chat()
        path = self.run / chat.documents['alpha-api']
        original = path.read_text()
        path.write_text(original.replace('Service: alpha-api;', 'Service: foreign-api;'))
        with patch('pipeline.requests.request') as request, self.assertRaisesRegex(PipelineError, 'modified'):
            chat.ask('alpha-api', 'Is it active?')
        request.assert_not_called()
        path.unlink()
        with patch('pipeline.requests.request') as request, self.assertRaisesRegex(PipelineError, 'Cannot read'):
            chat.ask('alpha-api', 'Is it active?')
        request.assert_not_called()

    def test_chat_rejects_other_process_html_as_selected_document(self):
        """Even swapping filenames cannot expose another process to the selected chat."""
        chat = self.chat()
        chat.documents['alpha-api'] = chat.documents['beta-api']
        with patch('pipeline.requests.request') as request, self.assertRaisesRegex(PipelineError, 'foreign'):
            chat.ask('alpha-api', 'Tell me about beta')
        request.assert_not_called()

    def test_context_overflow_makes_no_request(self):
        client = Client('http://localhost:3001/v1', 'secret', 'mock', consent=True, budget=100)
        with patch('pipeline.requests.request') as request, self.assertRaisesRegex(PipelineError, 'Context budget'):
            client.complete('Instruction', {'evidence': 'a' * 1000}, ANSWER)
        request.assert_not_called()

    def test_explicit_chat_chunk_scope(self):
        chat = self.chat()
        with patch('pipeline.requests.request', return_value=response(self.answer('beta-api'))) as request:
            chat.ask('beta-api', 'What happened?', chunk=1)
            payload = json.loads(request.call_args.kwargs['json']['messages'][1]['content'])
        self.assertEqual(payload['scope'], 'section chunk 1')
        self.assertEqual(len(payload['evidence']), 1)
        with self.assertRaises(PipelineError):
            chat.ask('beta-api', 'test', chunk=999)

    def test_invalid_json_bounded_correction(self):
        bad = response(None)
        bad.json.return_value['choices'][0]['message']['content'] = 'prose {"answer": "bad"}'
        with patch('pipeline.requests.request', return_value=bad) as request, self.assertRaisesRegex(PipelineError, 'one correction'):
            self.client.complete('test', {}, ANSWER)
        self.assertEqual(request.call_count, 2)

    def test_json_fence_and_schema_mode(self):
        valid = dict(answer='No evidence', abstain=True, citations=[])
        obj = response(valid)
        obj.json.return_value['choices'][0]['message']['content'] = '```json\n' + json.dumps(valid) + '\n```'
        self.client.mode = 'json_schema'
        with patch('pipeline.requests.request', return_value=obj) as request:
            self.assertEqual(self.client.complete('test', {}, ANSWER), valid)
        self.assertTrue(request.call_args.kwargs['json']['response_format']['json_schema']['strict'])

    def test_schema_echo_and_nonfinite_numbers_rejected(self):
        for content in (json.dumps(ANSWER), '{"confidence":NaN}'):
            obj = response(None)
            obj.json.return_value['choices'][0]['message']['content'] = content
            with patch('pipeline.requests.request', return_value=obj), self.assertRaises(PipelineError):
                self.client.complete('test', {}, ANSWER)

    def test_wrong_ids_and_inconsistent_assignments_stop_run(self):
        valid = self.routed()[0]
        cases = [dict(valid, section_id='unknown'), dict(valid, target='foreign'),
                 dict(valid, status='mixed'), dict(valid, status='assigned', target=None)]
        for result in cases:
            with patch('pipeline.requests.request', return_value=response(result)) as request, self.assertRaises(PipelineError):
                classify(self.data, self.targets, self.client, self.run)
            self.assertEqual(request.call_count, 1)

    def test_missing_duplicate_unknown_decisions_export_rejected(self):
        decisions = self.routed()
        for invalid in (decisions[:-1], decisions + decisions[:1], [dict(d, section_id='unknown') for d in decisions]):
            with self.assertRaises(PipelineError):
                export(self.data, self.targets, invalid, self.run)

    def test_provider_errors_stop_immediately_and_hide_secrets(self):
        for code, expected in ((401, 'Authentication'), (404, 'Model or route'), (429, 'Quota'), (500, 'Provider'), (302, 'Redirect')):
            with patch('pipeline.requests.request', return_value=response({'secret': 'test-key'}, code)) as request:
                with self.assertRaisesRegex(PipelineError, expected) as caught:
                    classify(self.data, self.targets, self.client, self.run)
            self.assertNotIn('test-key', str(caught.exception))
            self.assertEqual(request.call_count, 1)
            self.assertFalse(request.call_args.kwargs['allow_redirects'])

    def test_transport_and_envelope_errors(self):
        with patch('pipeline.requests.request', side_effect=requests.ConnectionError('test-key')), self.assertRaisesRegex(PipelineError, 'Network failure'):
            self.client.complete('test', {}, ANSWER)
        obj = response(None)
        obj.json.return_value = {'unexpected': 'test-key'}
        with patch('pipeline.requests.request', return_value=obj), self.assertRaisesRegex(PipelineError, 'envelope'):
            self.client.complete('test', {}, ANSWER)

    def test_truncated_output_is_not_retried(self):
        obj = response({})
        obj.json.return_value['choices'][0]['finish_reason'] = 'length'
        with patch('pipeline.requests.request', return_value=obj) as request, self.assertRaisesRegex(PipelineError, 'Truncated'):
            self.client.complete('test', {}, ANSWER)
        self.assertEqual(request.call_count, 1)

    def test_consent_and_endpoint_validation(self):
        client = Client('http://localhost:3001/v1', 'key', 'mock')
        with patch('pipeline.requests.request') as request, self.assertRaisesRegex(PipelineError, 'consent'):
            client.models()
        request.assert_not_called()
        for url in ('http://example.com/v1', 'https://u:p@example.com/v1', 'https://example.com/v1?key=secret'):
            with self.assertRaises(PipelineError):
                Client(url, 'key', 'mock')

    def test_hosted_base_urls_and_full_chat_urls(self):
        """Hosted prefixes and complete endpoints resolve without duplicated paths."""
        cases = [
            ('https://example.com/v1', 'https://example.com/v1/chat/completions'),
            ('https://example.com/openai/v1/', 'https://example.com/openai/v1/chat/completions'),
            ('https://example.com/api', 'https://example.com/api/chat/completions'),
            ('https://example.com', 'https://example.com/chat/completions'),
            ('https://example.com/v1/chat/completions', 'https://example.com/v1/chat/completions'),
            ('https://example.com/deployments/test/chat/completions?api-version=2024-10-21',
             'https://example.com/deployments/test/chat/completions?api-version=2024-10-21')]
        for endpoint, expected in cases:
            client = Client(endpoint, 'hidden-key', 'mock', consent=True)
            with patch('pipeline.requests.request', return_value=response({})) as request:
                client.request('POST', '/chat/completions', {})
            self.assertEqual(request.call_args.args[1], expected)
            self.assertEqual(request.call_args.kwargs['headers'], {'Authorization': 'Bearer hidden-key'})

    def test_custom_full_url_and_api_key_authentication(self):
        """Preserve custom endpoint URLs and keep API credentials solely in headers."""
        endpoint = 'https://example.com/inference/?api-version=2024-10-21'
        client = Client(endpoint, 'hidden-key', 'mock', consent=True, endpoint_kind='chat', auth='api-key')
        with patch('pipeline.requests.request', return_value=response({})) as request:
            client.request('POST', '/chat/completions', {})
        self.assertEqual(request.call_args.args[1], endpoint)
        self.assertEqual(request.call_args.kwargs['headers'], {'api-key': 'hidden-key'})
        with patch('pipeline.requests.request') as request, self.assertRaisesRegex(PipelineError, 'catalog'):
            client.models()
        request.assert_not_called()

    def test_model_url_preserves_prefix_and_query(self):
        """Query parameters belong after the catalog route, not before it."""
        client = Client('https://example.com/api/v2?api-version=test', 'key', 'mock', consent=True)
        with patch('pipeline.requests.request', return_value=response({})) as request:
            client.request('GET', '/models')
        self.assertEqual(request.call_args.args[1], 'https://example.com/api/v2/models?api-version=test')

    def test_endpoint_validation_rejects_embedded_keys_and_bad_ports(self):
        """Errors never echo secret-bearing or malformed URLs."""
        for endpoint in ('https://example.com/api?api_key=secret', 'https://example.com:999999/api',
                         'https://example.com/api#fragment', 'https://example.com/api?access_token=secret'):
            with self.assertRaises(PipelineError) as caught:
                Client(endpoint, 'key', 'mock')
            self.assertNotIn('secret', str(caught.exception))

    def test_catalog_excludes_unavailable_routes(self):
        obj = response(None)
        obj.json.return_value = {'data': [{'id': 'ready'}, {'id': 'no-key', 'needsKey': True}, {'id': 'empty', 'exhausted': True}, {'id': 'status-no-key', 'execution_status': 'needsKey'}, {'id': 'status-empty', 'execution_status': 'exhausted'}]}
        with patch('pipeline.requests.request', return_value=obj):
            self.assertEqual(self.client.models(), ['ready'])

    def test_payload_exact_labels_and_invalid_values(self):
        path = self.root / 'targets.json'
        path.write_text(json.dumps({'targets': ['Exact Label', 'similar-label']}))
        self.assertEqual(load_targets(path), ['Exact Label', 'similar-label'])
        for targets in ([], ['a', 'a'], ['a', None], ['only-one']):
            path.write_text(json.dumps({'targets': targets}))
            with self.assertRaises(PipelineError):
                load_targets(path)

    def test_new_heading_without_close_is_quarantined(self):
        pages = copy.deepcopy(self.data['pages'])
        from pipeline import segment
        pages[0]['blocks'] = [b for b in pages[0]['blocks'] if b['text'] != 'Evidence section closed']
        sections, _ = segment(pages)
        self.assertIn('New heading', sections[0]['boundary'])

    def test_gap_between_slices_quarantines_continuation(self):
        """Missing pages must never bridge two otherwise related source slices."""
        from pipeline import segment
        pages = copy.deepcopy(self.data['pages'][:2])
        pages[1]['number'] = 3
        sections, _ = segment(pages)
        self.assertIn('Missing', sections[1]['boundary'])
        self.assertIn('No recognized', sections[2]['boundary'])

    def test_missing_image_export_and_invalid_assignment_fail(self):
        """Do not publish apparently valid HTML when source assets/decisions are broken."""
        decisions = self.routed()
        wrong = [dict(decisions[0], status='mixed')] + decisions[1:]
        with self.assertRaisesRegex(PipelineError, 'inconsistent'):
            export(self.data, self.targets, wrong, self.run)
        image = next(b for b in self.data['sections'][0]['blocks'] if b['kind'] == 'image')
        (self.run / image['path']).unlink()
        with self.assertRaisesRegex(PipelineError, 'Missing/unreadable image'):
            export(self.data, self.targets, decisions, self.run)

    def test_escape_html_without_rewriting_source(self):
        data = copy.deepcopy(self.data)
        b = data['sections'][0]['blocks'][0]
        b['text'] = '<script>alert(1)</script>'
        b['spans'][0]['text'] = b['text']
        from pipeline import html_document
        rendered = html_document('<bad>', data, data['sections'][:1], self.run)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--make-fixture':
        fixture(Path(sys.argv[2]))
        print('Created controlled 3-page fixture. Targets: alpha-api, beta-api.')
    else:
        unittest.main(verbosity=2)
