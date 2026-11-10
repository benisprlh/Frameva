"""Opt-in real-browser source -> recording -> launch film acceptance run.

Requires .[dev,capture] and installed Chromium. It serves only the bundled demo,
uses a fresh isolated project, and writes to a new output directory. This script
is intentionally not part of the default browser-mocked unittest suite.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time
import wave
import struct

from fastapi.testclient import TestClient
from frameva.app import create_app
from frameva.config import Config
from frameva.render import probe
from frameva.source import inspect_repository


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def checked(response):
    if response.status_code >= 300:
        raise RuntimeError(f"API failed ({response.status_code}): {response.text[:1000]}")
    return response.json()


def await_job(client, job, timeout=300):
    until = time.monotonic() + timeout
    last = None
    while time.monotonic() < until:
        current = checked(client.get('/api/jobs/' + job['id']))
        status = current['status']
        if status != last:
            print(f"{current['type']}: {status}", flush=True)
            last = status
        if status == 'succeeded':
            return current
        if status in {'failed', 'cancelled'}:
            raise RuntimeError(current.get('error') or f"Job {status}")
        time.sleep(.25)
    checked(client.post('/api/jobs/' + job['id'] + '/cancel'))
    raise TimeoutError('Job exceeded acceptance-run deadline; cancellation requested.')


def save_asset(client, asset_id, path):
    response = client.get('/api/assets/' + asset_id + '/file')
    response.raise_for_status()
    path.write_bytes(response.content)


def soundtrack(path, duration):
    # Original procedural pad, no third-party music assets.
    rate = 22050
    notes = (164.81, 220.0, 261.63, 329.63)
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(rate)
        for base in range(0, int(duration * rate), rate):
            values = []
            for frame in range(base, min(base + rate, int(duration * rate))):
                t = frame / rate
                envelope = min(1, t / 1.5, (duration - t) / 1.5)
                value = sum(math.sin(2 * math.pi * frequency * t) for frequency in notes) / len(notes)
                values.append(struct.pack('<h', int(value * max(0, envelope) * 10000)))
            audio.writeframes(b''.join(values))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, default=Path('live-demo-output'))
    args = parser.parse_args()
    output = args.output_directory.resolve()
    if output.exists():
        parser.error('Use a new output directory; existing files are never overwritten.')
    demo = Path(__file__).resolve().parents[1] / 'examples' / 'live-demo'
    plan = json.loads((demo / 'launch-flow.json').read_text())
    output.mkdir(parents=True, mode=0o700)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(demo)))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    plan['base_url'] = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with tempfile.TemporaryDirectory(prefix='frameva-live-acceptance-') as scratch:
            config = Config(Path(scratch))
            headers = {'Authorization': 'Bearer ' + config.token}
            with TestClient(create_app(config), base_url='http://127.0.0.1', headers=headers) as client:
                project = checked(client.post('/api/projects', json={'name': 'Orbit', 'description': 'Real live-demo acceptance run'}))
                prefix = '/api/projects/' + project['id']
                analysis = inspect_repository(demo)
                checked(client.post(prefix + '/source-analysis', json={'analysis': analysis}))
                flow = checked(client.post(prefix + '/flows', json=plan))
                recorded = await_job(client, checked(client.post('/api/flows/' + flow['id'] + '/record')))
                asset = next(a for a in checked(client.get('/api/assets', params={'project_id': project['id']})) if a['id'] == recorded['asset_id'])
                save_asset(client, asset['id'], output / 'raw-walkthrough.mp4')
                body_duration = round(min(120.0, asset['duration'] - .4), 2)
                if body_duration < 1:
                    raise RuntimeError('The real recording is too short for the acceptance scene.')
                scenes = [
                    {'name': 'Opening', 'provider': 'preview', 'layout': 'title', 'headline': 'Meet Orbit.', 'caption': 'One workspace. A clearer launch.', 'duration': 2.5},
                    {'name': 'Complete launch workflow', 'provider': 'recording', 'video_asset_id': asset['id'], 'trim_start': .2,
                     'duration': body_duration, 'camera': 'static', 'zoom': 1, 'headline': 'From plan to progress.',
                     'caption': 'Create. Complete. Focus. Measure.', 'keep_audio': True},
                    {'name': 'Call to action', 'provider': 'preview', 'layout': 'title', 'headline': 'Make the next launch yours.',
                     'caption': 'Orbit / Frameva live demonstration', 'duration': 2.5},
                ]
                for scene in scenes:
                    scene.update(width=1280, height=720, fps=30, brand_color='#b8ff65')
                    checked(client.post(prefix + '/shots', json=scene))
                for job in checked(client.post(prefix + '/generate')):
                    await_job(client, job)
                music = output / 'original-demo-pad.wav'
                soundtrack(music, body_duration + 5)
                with music.open('rb') as file:
                    audio = checked(client.post('/api/assets', data={'project_id': project['id']}, files={'file': ('original-demo-pad.wav', file, 'audio/wav')}))
                exported = await_job(client, checked(client.post(prefix + '/export', json={
                    'width': 1280, 'height': 720, 'fps': 30, 'transition': 'crossfade', 'transition_duration': .35, 'audio_asset_id': audio['id']})))
                save_asset(client, exported['asset_id'], output / 'launch-film.mp4')
                coverage = checked(client.get(prefix + '/coverage'))
                report = asset['capture_report']
                if report['status'] != 'completed' or len(report['steps']) != len(plan['steps']):
                    raise AssertionError('Incomplete capture report')
                for name, value in [('source-analysis', analysis), ('recording-report', report), ('coverage', coverage)]:
                    (output / (name + '.json')).write_text(json.dumps(value, indent=2), encoding='utf-8')
                media = probe(output / 'launch-film.mp4')
                summary = {'status': 'passed', 'real_browser_recording': True, 'native_screen_capture_tested': False,
                    'step_count': len(report['steps']), 'duration': media['duration'], 'coverage': coverage['totals']}
                (output / 'run-report.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
                print(json.dumps(summary, indent=2))
                print(f'Film: {output / "launch-film.mp4"}')
        return 0
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__':
    sys.exit(main())
