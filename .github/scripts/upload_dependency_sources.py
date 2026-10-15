"""Reproduce the existing dependency archive and stage it on a beta draft only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

METADATA = json.loads((Path(__file__).parents[1] / 'beta-sources-metadata.json').read_text())


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): result.update(chunk)
    return result.hexdigest()


def download(entry, cache, local=None):
    name = Path(entry['info']['name']).name
    destination = cache / name
    if local:
        source = local / name
        if sha(source) != entry['source']['sha256']: raise ValueError('Changed cached source: ' + name)
        return source
    if not entry['source']['url'].startswith('https://'): raise ValueError('Expected HTTPS input')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(entry['source']['url'], timeout=90) as response, destination.open('wb') as output:
                while chunk := response.read(1024 * 1024): output.write(chunk)
            if sha(destination) != entry['source']['sha256']: raise ValueError('Changed public source: ' + name)
            print('Verified source:', name, flush=True)
            return destination
        except (OSError, urllib.error.URLError):
            if attempt == 2: raise
            time.sleep(2)


def reproduce(destination, cache, local=None):
    with ThreadPoolExecutor(max_workers=4) as workers:
        inputs = list(workers.map(lambda entry: download(entry, cache, local), METADATA['entries']))
    with destination.open('wb') as raw:
        with gzip.GzipFile(filename=METADATA['filename'], mode='wb', fileobj=raw, mtime=METADATA['gzip_mtime']) as zipped:
            with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for entry, path in zip(METADATA['entries'], inputs):
                    values = entry['info'].copy(); values['type'] = values['type'].encode()
                    info = tarfile.TarInfo()
                    for key, value in values.items(): setattr(info, key, value)
                    if path.stat().st_size != info.size: raise ValueError('Changed source size')
                    with path.open('rb') as source: archive.addfile(info, source)
    actual = sha(destination)
    if actual != METADATA['sha256']: raise ValueError('Reproduced archive differs: ' + actual)
    print('Reproduced exact archive:', actual, flush=True)


def github(method, path, payload=None, upload=None):
    host = 'uploads.github.com' if upload else 'api.github.com'
    headers = {'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'], 'Accept': 'application/vnd.github+json',
               'User-Agent': 'Wizard101-beta-source-staging'}
    if upload:
        headers.update({'Content-Type': 'application/octet-stream', 'Content-Length': str(upload.stat().st_size)})
        with upload.open('rb') as data:
            request = urllib.request.Request('https://' + host + path, data=data, headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=600) as response: return json.load(response)
    data = json.dumps(payload).encode() if payload is not None else None
    if data: headers['Content-Type'] = 'application/json'
    request = urllib.request.Request('https://' + host + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response: return json.load(response)


def stage(archive):
    repo = METADATA['repository']; release_id = METADATA['release_id']
    release = github('GET', f'/repos/{repo}/releases/{release_id}')
    if release['draft'] is not True or release['tag_name'] != METADATA['tag']:
        raise ValueError('Refusing to upload to a public or different release')
    assets = github('GET', f'/repos/{repo}/releases/{release_id}/assets?per_page=100')
    existing = next((asset for asset in assets if asset['name'] == METADATA['filename']), None)
    expected = 'sha256:' + METADATA['sha256']
    if existing:
        if existing.get('digest') == expected and existing['size'] == archive.stat().st_size:
            print('Draft already contains the exact archive'); return
        raise ValueError('Refusing to replace an existing, different draft asset')
    asset = github('POST', f'/repos/{repo}/releases/{release_id}/assets?name=' + METADATA['filename'], upload=archive)
    if asset.get('digest') != expected or asset['size'] != archive.stat().st_size: raise ValueError('Uploaded archive differs')
    print('Verified draft source upload:', asset['name'], asset['digest'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-cache', type=Path)
    parser.add_argument('--upload', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='w101-beta-sources-') as temporary:
        work = Path(temporary); archive = work / METADATA['filename']
        reproduce(archive, work, args.local_cache)
        if args.upload: stage(archive)
