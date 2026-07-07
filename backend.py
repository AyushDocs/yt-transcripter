import re
import os
import tempfile
from urllib.parse import urlparse, parse_qs

import yt_dlp
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


def extract_video_id(url: str) -> str | None:
    url = url.strip()
    patterns = [
        r'youtube\.com/watch\?v=([\w-]{11})',
        r'youtu\.be/([\w-]{11})',
        r'youtube\.com/embed/([\w-]{11})',
        r'youtube\.com/v/([\w-]{11})',
        r'youtube\.com/shorts/([\w-]{11})',
        r'm\.youtube\.com/watch\?v=([\w-]{11})',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    if re.match(r'^[\w-]{11}$', url):
        return url
    return None


def parse_vtt_to_text(vtt_content: str) -> str:
    lines = vtt_content.split('\n')
    output = []
    text_lines = []
    current_ts = ''
    for line in lines:
        stripped = line.strip()
        if stripped == '':
            if text_lines and current_ts:
                raw = ' '.join(text_lines)
                raw = re.sub(r'<[^>]+>', '', raw)
                raw = re.sub(r'\s+', ' ', raw).strip()
                if raw:
                    ts = current_ts.rstrip('0').rstrip('.')
                    if ts.startswith('00:'):
                        ts = ts[3:]
                    output.append(f'{ts}  {raw}')
                text_lines = []
                current_ts = ''
        elif '-->' in stripped:
            current_ts = stripped.split(' --> ')[0]
        elif stripped == 'WEBVTT':
            continue
        elif stripped.startswith('Kind:') or stripped.startswith('Language:'):
            continue
        else:
            text_lines.append(stripped)
    if text_lines and current_ts:
        raw = ' '.join(text_lines)
        raw = re.sub(r'<[^>]+>', '', raw)
        raw = re.sub(r'\s+', ' ', raw).strip()
        if raw:
            ts = current_ts.rstrip('0').rstrip('.')
            if ts.startswith('00:'):
                ts = ts[3:]
            output.append(f'{ts}  {raw}')
    return '\n'.join(output)


@app.route('/transcript', methods=['POST'])
def get_transcript():
    data = request.get_json(silent=True)
    if not data or 'url' not in data:
        return jsonify({'error': 'Missing "url" in request body'}), 400

    url = data['url']
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'error': 'Invalid YouTube URL or video ID'}), 400

    tmpdir = tempfile.mkdtemp()
    outtmpl = os.path.join(tmpdir, '%(id)s')

    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'subtitlesformat': 'vtt',
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        return jsonify({'error': f'Failed to fetch video: {str(e)}'}), 500

    title = info.get('title', 'Unknown')
    duration = info.get('duration', 0)

    sub_path = None
    rs = info.get('requested_subtitles', {})
    if 'en' in rs:
        sub_path = rs['en'].get('filepath')

    transcript = ''
    if sub_path and os.path.exists(sub_path):
        with open(sub_path, encoding='utf-8') as f:
            vtt = f.read()
        transcript = parse_vtt_to_text(vtt)
        os.unlink(sub_path)

    try:
        os.rmdir(tmpdir)
    except OSError:
        pass

    if not transcript:
        return jsonify({'error': 'No English transcript available for this video'}), 404

    return jsonify({
        'title': title,
        'duration': duration,
        'video_id': video_id,
        'transcript': transcript,
    })


@app.route('/')
def index():
    return app.send_static_file('index.html')


if __name__ == '__main__':
    import sys, os
    # Serve index.html from the directory containing this script
    app.static_folder = os.path.dirname(os.path.abspath(__file__))
    app.static_url_path = ''
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
