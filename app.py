import os
import base64
import subprocess
import uuid
import shutil
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = '/tmp'
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')

# हर रिक्वेस्ट पर फोल्डर रीसेट करो
def clean_and_create():
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
        os.makedirs(folder, exist_ok=True)

clean_and_create()

def save_base64_file(data, prefix):
    if not data or len(data) < 100:
        return None
    try:
        if "," in data:
            header, encoded = data.split(",", 1)
        else:
            encoded = data
        file_data = base64.b64decode(encoded)
        if len(file_data) == 0:
            return None
        ext = "jpg"
        if data.startswith("data:audio"): ext = "mp3"
        elif data.startswith("data:image/png"): ext = "png"
        filename = f"{prefix}_{uuid.uuid4().hex[:10]}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        with open(filepath, "wb") as f:
            f.write(file_data)
        return filepath
    except Exception as e:
        print("Save error:", str(e))
        return None

@app.route('/', methods=['GET'])
def home():
    return "News Video Server – V8 Ultra Stable (10 Images Tak Tested)"

@app.route('/render', methods=['POST'])
def render_video():
    clean_and_create()  # हर बार नया फोल्डर

    try:
        data = request.json

        main_audio = save_base64_file(data.get('audioData'), "voice")
        bg_music = save_base64_file(data.get('bgmData'), "bgm")
        logo = save_base64_file(data.get('logoData'), "logo")
        clips = data.get('clips', [])

        if not main_audio or len(clips) == 0:
            return jsonify({"error": "ऑडियो या इमेज नहीं मिली"}), 400

        inputs = ['-i', main_audio]
        filters = []
        image_inputs = []

        # इमेजेस को सीधे -i में डालो, -loop और -t बाद में
        for i, clip in enumerate(clips):
            img_path = save_base64_file(clip.get('imageData'), f"img_{i}")
            if img_path:
                inputs += ['-i', img_path]
                image_inputs.append(f"[{i+1}:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,format=yuv420p[v{i}];")

        if not image_inputs:
            return jsonify({"error": "कोई वैलिड इमेज नहीं मिली"}), 400)

        # सभी इमेज को कनकैट करो
        concat_list = "".join(f"[v{i}]" for i in range(len(image_inputs)))
        filters.extend(image_inputs)
        filters.append(f"{concat_list}concat=n={len(image_inputs)}:v=1:a=0[vid];")

        # लोगो
        if logo:
            inputs += ['-i', logo]
            filters.append("[vid][{len(inputs)-1}:v]overlay=20:20[vidlogo];".format(len= len(inputs)))
            final_vid = "[vidlogo]"
        else:
            final_vid = "[vid]"

        # ऑडियो मिक्स
        if bg_music:
            inputs += ['-i', bg_music]
            filters.append("[0:a][{len(inputs)-1}:a]amix=inputs=2:duration=first:dropout_transition=2,volume=1.0[aud];".format(len=len(inputs)))
            final_aud = "[aud]"
        else:
            final_aud = "[0:a]"

        filter_complex = "".join(filters)

        output_path = os.path.join(OUTPUT_FOLDER, "final.mp4")

        cmd = [
            'ffmpeg', '-y'
        ] + inputs + [
            '-filter_complex', filter_complex,
            '-map', final_vid,
            '-map', final_aud,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-r', '30',
            '-shortest',
            output_path
        ]

        print("FFmpeg CMD:", " ".join(cmd[:20]) + " ...")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

        if result.returncode != 0:
            print("FFmpeg Error:", result.stderr[:500])
            return jsonify({"error": "वीडियो बनाने में दिक्कत", "log": result.stderr[:1000]}), 500

        return send_file(output_path, as_attachment=True, download_name="News_Video_HD.mp4")

    except Exception as e:
        print("Crash:", str(e))
        return jsonify({"error": "Server crash: " + str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
