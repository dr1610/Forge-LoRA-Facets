"""Local metadata catalog. No model weights or existing sidecars are modified."""
import hashlib
import json
import os
import threading
import time
from pathlib import Path

GENRES = {
    'character': 'キャラクター', 'style': '画風', 'concept': 'コンセプト',
    'clothing': '衣装', 'background': '背景', 'poses': 'ポーズ',
    'expression': '表情', 'tool': 'ツール', 'vehicle': '乗り物',
    'assets': '素材', 'buildings': '建物', 'objects': '小物',
    'animal': '動物', 'action': '動作', 'other': 'その他', 'unclassified': '未分類',
}
ALIASES = {
    'character': ['character', 'characters', 'キャラクター'],
    'style': ['style', 'styles', 'art style', '画風'],
    'concept': ['concept', 'concepts', 'コンセプト'],
    'clothing': ['clothing', 'clothes', 'outfit', 'outfits', 'costume', '衣装'],
    'background': ['background', 'backgrounds', 'landscape', 'scenery', '背景'],
    'poses': ['pose', 'poses', 'ポーズ'],
    'expression': ['expression', 'expressions', 'facial expression', '表情'],
    'tool': ['tool', 'tools', 'ツール'], 'vehicle': ['vehicle', 'vehicles', '乗り物'],
    'assets': ['asset', 'assets', '素材'],
    'buildings': ['building', 'buildings', 'architecture', '建物'],
    'objects': ['object', 'objects', '小物'], 'animal': ['animal', 'animals', '動物'],
    'action': ['action', 'actions', '動作'], 'other': ['other', 'その他'],
}


def normalized(value):
    return ' '.join(str(value).lower().replace('_', ' ').split())


def strings(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, dict):
            item = item.get('name', '')
        if isinstance(item, str) and item.strip():
            result.append(item.strip()[:200])
    return list(dict.fromkeys(result))[:1000]


def parse_info(data):
    """Accept civbrowser model JSON, Civitai Helper version JSON and API responses."""
    if not isinstance(data, dict):
        return {}
    model = data.get('model') if isinstance(data.get('model'), dict) else {}
    versions = data.get('modelVersions')
    version = versions[0] if isinstance(versions, list) and versions and isinstance(versions[0], dict) else data
    tags = strings(data.get('tags')) + strings(model.get('tags'))
    for source in (data, model):
        tags += strings(source.get('category')) + strings(source.get('categories'))
    tags = sorted(set(tags), key=str.casefold)
    values = {normalized(t) for t in tags}
    genres = [key for key, aliases in ALIASES.items() if values.intersection(aliases)]
    model_id = data.get('modelId') or model.get('id') or (data.get('id') if versions else None)
    return {
        'tags': tags, 'genres': genres or ['unclassified'],
        'model_id': model_id if isinstance(model_id, int) and not isinstance(model_id, bool) else None,
        'model_name': model.get('name') or data.get('name') or '',
        'base_model': data.get('baseModel') or version.get('baseModel') or '',
    }


class Catalog:
    def __init__(self, storage, provider):
        self.storage = Path(storage)
        self.index_storage = self.storage.with_name(self.storage.stem + '-index.json')
        self.provider = provider
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.job = {'running': False, 'done': 0, 'total': 0, 'ok': 0, 'errors': 0, 'message': ''}
        self.records = {}
        self.auto = {}
        self.overrides = {}
        self.local_cache = {}
        self.load_error = ''
        try:
            if self.storage.exists():
                saved = json.loads(self.storage.read_text(encoding='utf-8'))
                if not isinstance(saved.get('auto', {}), dict) or not isinstance(saved.get('overrides', {}), dict):
                    raise ValueError('invalid catalog')
                self.auto = saved.get('auto', {})
                self.overrides = saved.get('overrides', {})
        except (OSError, ValueError, TypeError) as exc:
            self.load_error = '分類データを読めません。元ファイル保護のため保存を停止しています: ' + type(exc).__name__
        try:
            if self.index_storage.exists():
                index = json.loads(self.index_storage.read_text(encoding='utf-8'))
                if isinstance(index, dict):
                    self.local_cache = index
        except (OSError, ValueError):
            pass  # Derived cache can always be rebuilt from unchanged sidecars.

    def save(self):
        if self.load_error:
            raise ValueError(self.load_error)
        self.storage.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage.with_suffix('.tmp')
        tmp.write_text(json.dumps({'schema': 1, 'auto': self.auto, 'overrides': self.overrides}, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, self.storage)

    def scan(self):
        records = {}
        next_cache = {}
        for name, path in self.provider():
            path = Path(path)
            try:
                stat = path.stat()
            except OSError:
                continue
            identity = os.path.normcase(os.path.abspath(path))
            key = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
            info, source, warnings = {}, '', []
            sidecars = []
            for suffix in ('.civitai.info', '.civitai.json', '.info.json'):
                sidecar = path.with_suffix(suffix)
                try:
                    side_stat = sidecar.stat()
                    sidecars.append((sidecar, side_stat.st_size, side_stat.st_mtime_ns))
                except FileNotFoundError:
                    continue
                except OSError:
                    warnings.append(sidecar.name + ' にアクセスできません')
            stamp = [[str(p), size, modified] for p, size, modified in sidecars]
            cached_local = self.local_cache.get(key, {})
            if cached_local.get('stamp') == stamp:
                info = cached_local.get('info', {})
                source = cached_local.get('source', '')
                warnings += cached_local.get('warnings', [])
                to_read = []
            else:
                to_read = sidecars
            for sidecar, _, _ in to_read:
                try:
                    parsed = parse_info(json.loads(sidecar.read_text(encoding='utf-8-sig')))
                    if parsed:
                        if not info:
                            info = parsed
                        else:
                            info['tags'] = sorted(set(info['tags'] + parsed['tags']), key=str.casefold)
                            info['genres'] = list(dict.fromkeys(info['genres'] + parsed['genres']))
                            if len(info['genres']) > 1:
                                info['genres'] = [g for g in info['genres'] if g != 'unclassified']
                            info['model_id'] = info.get('model_id') or parsed.get('model_id')
                        source = '保存済みCivitai情報'
                except (OSError, ValueError, TypeError, AttributeError):
                    warnings.append(sidecar.name + ' を読めません')
            next_cache[key] = {'stamp': stamp, 'info': info, 'source': source, 'warnings': warnings}
            records[key] = {'id': key, 'name': str(name), 'path': str(path),
                            'fingerprint': [stat.st_size, stat.st_mtime_ns],
                            'local': info, 'source': source, 'warnings': warnings}
        with self.lock:
            self.records = records
            self.local_cache = next_cache
            self.index_storage.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.index_storage.with_suffix('.tmp')
            tmp.write_text(json.dumps(next_cache, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, self.index_storage)
        return self.snapshot()

    def effective(self, record):
        cached = self.auto.get(record['id'], {})
        if cached.get('fingerprint') != record['fingerprint']:
            cached = {}
        info = dict(record['local'])
        # A successful model lookup supersedes older sidecars; failures never erase metadata.
        info.update(cached.get('info', {}))
        manual = self.overrides.get(record['id'])
        result = {'id': record['id'], 'name': record['name'], 'tags': info.get('tags', []),
                  'genres': info.get('genres', ['unclassified']), 'model_id': info.get('model_id'),
                  'base_model': info.get('base_model', ''), 'source': 'Civitai取得済み' if cached.get('info') else record['source'] or '情報なし',
                  'manual': manual is not None, 'status': cached.get('status', ''),
                  'warnings': record['warnings']}
        if manual is not None:
            result.update(manual)
        return result

    def snapshot(self):
        with self.lock:
            return {'items': [self.effective(r) for r in self.records.values()],
                    'genres': GENRES, 'job': dict(self.job), 'error': self.load_error}

    def edit(self, key, genres, tags, reset=False):
        with self.lock:
            if self.load_error:
                raise ValueError(self.load_error)
            if key not in self.records:
                raise KeyError(key)
            previous = self.overrides.get(key)
            if reset:
                self.overrides.pop(key, None)
            else:
                if any(g not in GENRES for g in genres):
                    raise ValueError('不明なジャンルです')
                genres = list(dict.fromkeys(genres)) or ['unclassified']
                if len(genres) > 1:
                    genres = [g for g in genres if g != 'unclassified']
                self.overrides[key] = {'genres': genres, 'tags': strings(tags)}
            try:
                self.save()
            except Exception:
                if previous is None:
                    self.overrides.pop(key, None)
                else:
                    self.overrides[key] = previous
                raise
            return self.effective(self.records[key])

    @staticmethod
    def request_json(url):
        import requests
        response = requests.get(url, timeout=(10, 30), headers={'User-Agent': 'Forge-LoRA-Facets/1.0'}, allow_redirects=False)
        if response.status_code == 404:
            raise LookupError('Civitaiに該当情報なし')
        if response.status_code != 200:
            raise RuntimeError('Civitai HTTP ' + str(response.status_code))
        return response.json()

    def lookup(self, record):
        model_id = record['local'].get('model_id')
        if model_id:
            info = parse_info(self.request_json(f'https://civitai.com/api/v1/models/{int(model_id)}'))
            info['base_model'] = record['local'].get('base_model') or info['base_model']
            return info
        digest = hashlib.sha256()
        with open(record['path'], 'rb') as stream:
            while True:
                if self.stop.is_set():
                    raise InterruptedError()
                block = stream.read(4 * 1024 * 1024)
                if not block:
                    break
                digest.update(block)
        version = self.request_json('https://civitai.com/api/v1/model-versions/by-hash/' + digest.hexdigest())
        info = parse_info(version)
        if info.get('model_id'):
            model = parse_info(self.request_json(f"https://civitai.com/api/v1/models/{info['model_id']}"))
            model['base_model'] = info['base_model'] or model['base_model']
            return model
        return info

    def start(self, ids=None):
        with self.lock:
            if self.load_error:
                raise ValueError(self.load_error)
            if self.job['running']:
                raise ValueError('取得はすでに実行中です')
            if ids is not None and any(key not in self.records for key in ids):
                raise ValueError('一覧を再読込してください')
            selected = [dict(r) for key, r in self.records.items() if key in ids] if ids is not None else [
                dict(r) for r in self.records.values() if not self.effective(r)['tags']]
            self.stop.clear()
            self.job = {'running': True, 'done': 0, 'total': len(selected), 'ok': 0, 'errors': 0, 'message': '取得を開始します'}
            threading.Thread(target=self._worker, args=(selected,), daemon=True).start()
            return dict(self.job)

    def _worker(self, selected):
        try:
            for record in selected:
                if self.stop.is_set():
                    break
                key = record['id']
                with self.lock:
                    self.job['message'] = record['name']
                try:
                    info = self.lookup(record)
                    stat = Path(record['path']).stat()
                    if [stat.st_size, stat.st_mtime_ns] != record['fingerprint']:
                        raise RuntimeError('取得中にファイルが変更されました。再読込してください')
                    with self.lock:
                        self.auto[key] = {'info': info, 'status': '取得済み', 'fingerprint': record['fingerprint']}
                        self.job['ok'] += 1
                except InterruptedError:
                    break
                except Exception as exc:
                    with self.lock:
                        old = self.auto.get(key, {})
                        if old.get('fingerprint') != record['fingerprint']:
                            old = {}
                        self.auto[key] = {**old, 'status': str(exc)[:200], 'fingerprint': record['fingerprint']}
                        self.job['errors'] += 1
                with self.lock:
                    self.job['done'] += 1
                    self.save()
                if self.stop.wait(1.0):
                    break
        except Exception as exc:
            with self.lock:
                self.job['message'] = '保存エラー: ' + str(exc)[:200]
        finally:
            with self.lock:
                if not self.job['message'].startswith('保存エラー:'):
                    self.job['message'] = '停止しました' if self.stop.is_set() else '取得完了'
                self.job['running'] = False
