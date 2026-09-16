import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lora_facets_core import Catalog, parse_info


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'blue_hair.safetensors'
        self.model.write_bytes(b'model fixture')
        self.storage = self.root / 'data' / 'catalog.json'
        self.catalog = Catalog(self.storage, lambda: [('blue_hair', self.model)])

    def sidecar(self, data):
        self.model.with_suffix('.civitai.json').write_text(json.dumps(data), encoding='utf-8')

    def test_existing_civbrowser_sidecar_and_exact_categories(self):
        self.sidecar({'id': 123, 'tags': ['character', 'clothing', 'anime', 'characteristic'], 'modelVersions': [{'baseModel': 'Anima'}]})
        item = self.catalog.scan()['items'][0]
        self.assertEqual(item['genres'], ['character', 'clothing'])
        self.assertEqual(item['model_id'], 123)
        self.assertEqual(item['base_model'], 'Anima')
        self.assertEqual(parse_info({'tags': ['characteristic']})['genres'], ['unclassified'])

    def test_version_sidecar(self):
        item = parse_info({'modelId': 45, 'baseModel': 'SDXL', 'model': {'name': 'Example', 'tags': [{'name': 'style'}]}})
        self.assertEqual(item['model_id'], 45)
        self.assertEqual(item['genres'], ['style'])

    def test_manual_overrides_survive_refresh_and_restart(self):
        self.sidecar({'tags': ['character']})
        key = self.catalog.scan()['items'][0]['id']
        self.catalog.edit(key, ['style', 'clothing'], ['blue_hair', 'anime'])
        self.sidecar({'tags': ['background']})
        restarted = Catalog(self.storage, self.catalog.provider)
        item = restarted.scan()['items'][0]
        self.assertEqual(item['genres'], ['style', 'clothing'])
        self.assertEqual(item['tags'], ['blue_hair', 'anime'])
        self.assertTrue(item['manual'])
        reset = restarted.edit(key, [], [], reset=True)
        self.assertEqual(reset['genres'], ['background'])
        self.assertFalse(reset['manual'])

    def test_unknown_and_invalid_sidecar(self):
        self.model.with_suffix('.civitai.json').write_text('{bad', encoding='utf-8')
        item = self.catalog.scan()['items'][0]
        self.assertEqual(item['genres'], ['unclassified'])
        self.assertEqual(len(item['warnings']), 1)

    def test_index_cache_survives_restart_and_refreshes_changed_sidecar(self):
        self.sidecar({'tags': ['style']})
        self.catalog.scan()
        restarted = Catalog(self.storage, self.catalog.provider)
        self.assertTrue(restarted.local_cache)
        self.assertEqual(restarted.scan()['items'][0]['genres'], ['style'])
        self.sidecar({'tags': ['character', 'clothing']})
        self.assertEqual(restarted.scan()['items'][0]['genres'], ['character', 'clothing'])

    def test_cached_information_invalidated_when_model_changes(self):
        key = self.catalog.scan()['items'][0]['id']
        self.catalog.auto[key] = {'info': {'tags': ['style'], 'genres': ['style']}, 'fingerprint': self.catalog.records[key]['fingerprint']}
        self.assertEqual(self.catalog.snapshot()['items'][0]['genres'], ['style'])
        self.model.write_bytes(b'new model bytes')
        self.assertEqual(self.catalog.scan()['items'][0]['genres'], ['unclassified'])

    def test_corrupt_catalog_is_not_overwritten(self):
        self.storage.parent.mkdir()
        self.storage.write_text('{broken', encoding='utf-8')
        catalog = Catalog(self.storage, self.catalog.provider)
        key = catalog.scan()['items'][0]['id']
        with self.assertRaises(ValueError):
            catalog.edit(key, ['style'], [])
        self.assertEqual(self.storage.read_text(), '{broken')

    def test_worker_refresh_keeps_manual_override(self):
        key = self.catalog.scan()['items'][0]['id']
        self.catalog.edit(key, ['clothing'], ['uniform'])
        self.catalog.lookup = lambda record: {'genres': ['style'], 'tags': ['watercolor']}
        self.catalog._worker([self.catalog.records[key]])
        item = self.catalog.snapshot()['items'][0]
        self.assertEqual(item['genres'], ['clothing'])
        self.assertEqual(item['tags'], ['uniform'])
        self.assertEqual(self.catalog.auto[key]['info']['genres'], ['style'])

    def test_api_lookup_uses_full_file_hash_and_fetches_model_tags(self):
        import hashlib
        self.catalog.scan()
        calls = []
        def fake(url):
            calls.append(url)
            if '/by-hash/' in url:
                return {'modelId': 123, 'baseModel': 'Anima'}
            return {'id': 123, 'tags': ['character', 'anime'], 'modelVersions': [{'baseModel': 'Other'}]}
        self.catalog.request_json = fake
        info = self.catalog.lookup(next(iter(self.catalog.records.values())))
        self.assertTrue(calls[0].endswith(hashlib.sha256(self.model.read_bytes()).hexdigest()))
        self.assertTrue(calls[1].endswith('/models/123'))
        self.assertEqual(info['genres'], ['character'])
        self.assertEqual(info['base_model'], 'Anima')


if __name__ == '__main__':
    unittest.main()
