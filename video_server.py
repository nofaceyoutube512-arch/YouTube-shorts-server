from flask import Flask, request, jsonify, send_file
import subprocess
import os
import tempfile
import uuid
import requests

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/create-short', methods=['POST'])
def create_short():
    try:
        data = request.get_json()
        
        audio_url = data.get('audio_url')
        title = data.get('title', 'Hidden AI Feature')
        hook = data.get('hook', '')
        
        if not audio_url:
            return jsonify({"error": "audio_url is required"}), 400

        job_id = str(uuid.uuid4())
        temp_dir = tempfile.mkdtemp()
        
        audio_path = os.path.join(temp_dir, f'{job_id}.mp3')
        output_path = os.path.join(temp_dir, f'{job_id}.mp4')

        # Download audio file
        audio_response = requests.get(audio_url, timeout=30)
        with open(audio_path, 'wb') as f:
            f.write(audio_response.content)

        # Clean text for FFmpeg drawtext
        def clean_text(text):
            return text.replace("'", "").replace('"', '').replace(':', ' ').replace('\\', '').replace('%', 'percent')[:60]

        clean_title = clean_text(title)
        clean_hook = clean_text(hook)

        # Build FFmpeg command
        # Creates 1080x1920 vertical video (YouTube Shorts format)
        # Black background + bold white title + green hook text + audio
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi',
            '-i', f'color=black:size=1080x1920:rate=30',
            '-i', audio_path,
            '-filter_complex',
            (
                f"[0:v]drawtext=text='{clean_title}':"
                f"fontsize=80:fontcolor=white:x=(w-text_w)/2:y=(h/2)-200:"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"box=1:boxcolor=black@0.5:boxborderw=20,"
                f"drawtext=text='{clean_hook}':"
                f"fontsize=50:fontcolor=#00ff88:x=(w-text_w)/2:y=(h/2)+50:"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
                f"box=1:boxcolor=black@0.5:boxborderw=10[v]"
            ),
            '-map', '[v]',
            '-map', '1:a',
            '-shortest',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]

        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            return jsonify({
                "error": "FFmpeg failed",
                "details": result.stderr[-500:]
            }), 500

        return send_file(
            output_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=f'short_{job_id}.mp4'
        )

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to download audio: {str(e)}"}), 400
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Video generation timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
