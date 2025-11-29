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
TEMP_FOLDER = os.path.join(BASE_DIR, 'temp')

# हर रिक्वेस्ट पर फोल्डर रीसेट करो
def clean_and_create():
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, TEMP_FOLDER]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
        os.makedirs(folder, exist_ok=True)

clean_and_create()

def save_base64_file(data, prefix):
    """Base64 data (data:... ,xxxxx) को फाइल में सेव करके path लौटाएगा"""
    if not data or len(data) < 50:
        return None
    try:
        if "," in data:
            _, encoded = data.split(",", 1)
        else:
            encoded = data
        file_data = base64.b64decode(encoded)
        if len(file_data) == 0:
            return None
        # अनुमानित एक्सटेंशन
        ext = "jpg"
        low = data.lower()
        if low.startswith("data:audio"):
            ext = "mp3"
        elif low.startswith("data:image/png"):
            ext = "png"
        elif low.startswith("data:image/webp"):
            ext = "webp"
        elif low.startswith("data:image/"):
            ext = "jpg"
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
    return "News Video Server – V8 Ultra Stable (Images -> Video pipeline)"

def run_command(cmd, timeout=180):
    print("RUN:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result

@app.route('/render', methods=['POST'])
def render_video():
    clean_and_create()  # हर बार नया फोल्डर तैयार

    try:
        data = request.json or {}

        main_audio = save_base64_file(data.get('audioData', ''), "voice")
        bg_music = save_base64_file(data.get('bgmData', ''), "bgm")
        logo = save_base64_file(data.get('logoData', ''), "logo")
        clips = data.get('clips', [])

        if not main_audio:
            return jsonify({"error": "मुख्य ऑडियो (audioData) आवश्यक है"}), 400
        if not clips or len(clips) == 0:
            return jsonify({"error": "कृपया कम से कम 1 इमेज क्लिप भेजें"}), 400

        # हर इमेज से छोटे वीडियो बनाओ (default duration 5s अगर clips में duration नहीं है)
        image_videos = []
        for i, clip in enumerate(clips):
            img_path = save_base64_file(clip.get('imageData', ''), f"img_{i}")
            if not img_path:
                continue
            duration = clip.get('duration', 5)  # सेकंड
            # आउटपुट वीडियो पाथ
            img_vid = os.path.join(TEMP_FOLDER, f"imgvid_{i}.mp4")
            # scale + pad to 1280x720 (center) to keep uniform size
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", img_path,
                "-c:v", "libx264",
                "-t", str(duration),
                "-pix_fmt", "yuv420p",
                "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                "-r", "30",
                img_vid
            ]
            res = run_command(cmd)
            if res.returncode != 0:
                print("FFmpeg image->video error:", res.stderr[:800])
                return jsonify({"error": f"इमेज वीडियो बनाते समय त्रुटि (index {i})", "log": res.stderr}), 500
            image_videos.append(img_vid)

        if not image_videos:
            return jsonify({"error": "कोई वैध इमेज नहीं मिली"}), 400

        # concat list फाइल बनाओ
        concat_txt = os.path.join(TEMP_FOLDER, "concat_list.txt")
        with open(concat_txt, "w") as f:
            for vid in image_videos:
                f.write(f"file '{vid}'\n")

        # concat to single video
        concat_out = os.path.join(TEMP_FOLDER, "concat.mp4")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
            "-c", "copy", concat_out
        ]
        res = run_command(cmd)
        if res.returncode != 0:
            print("FFmpeg concat error:", res.stderr[:1000])
            return jsonify({"error": "वीडियो जोड़ने में दिक्कत", "log": res.stderr}), 500

        working_video = concat_out

        # लोगो ओवरले (अगर दिया हो)
        if logo:
            vid_logo_out = os.path.join(TEMP_FOLDER, "with_logo.mp4")
            # overlay को वीडियो के ऊपर 20,20 रखो
            cmd = [
                "ffmpeg", "-y",
                "-i", working_video,
                "-i", logo,
                "-filter_complex", "overlay=20:20",
                "-c:v", "libx264",
                "-c:a", "copy",
                vid_logo_out
            ]
            res = run_command(cmd)
            if res.returncode != 0:
                print("FFmpeg logo overlay error:", res.stderr[:800])
                return jsonify({"error": "लोगो ओवरले में त्रुटि", "log": res.stderr}), 500
            working_video = vid_logo_out

        # अब ऑडियो जोड़ें — main_audio (वॉइस) और optional bg_music
        final_out = os.path.join(OUTPUT_FOLDER, "final.mp4")
        if bg_music:
            # main_audio + bg_music को मिक्स करें (amix), और वीडियो के साथ मैप करें
            cmd = [
                "ffmpeg", "-y",
                "-i", working_video,
                "-i", main_audio,
                "-i", bg_music,
                "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                final_out
            ]
        else:
            # सिर्फ main_audio को वीडियो के साथ जोडो
            cmd = [
                "ffmpeg", "-y",
                "-i", working_video,
                "-i", main_audio,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                final_out
            ]
        res = run_command(cmd, timeout=300)
        if res.returncode != 0:
            print("FFmpeg final mux error:", res.stderr[:1200])
            return jsonify({"error": "ऑडियो/वीडियो मिक्स में दिक्कत", "log": res.stderr}), 500

        # सफल: फ़ाइल वापस भेजो
        return send_file(final_out, as_attachment=True, download_name="News_Video_HD.mp4")

    except subprocess.TimeoutExpired:
        return jsonify({"error": "FFmpeg command timeout"}), 500
    except Exception as e:
        print("Crash:", str(e))
        return jsonify({"error": "Server crash: " + str(e)}), 500

if __name__ == '__main__':
    # dev mode
    app.run(host='0.0.0.0', port=10000)
