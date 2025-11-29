import os
import base64
import subprocess
import uuid
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow requests from your website

UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def save_base64_file(data, prefix):
    if not data: return None
    try:
        if "," in data:
            header, encoded = data.split(",", 1)
        else:
            encoded = data
            
        ext = "jpg" # default
        if "audio" in header if "," in data else "": ext = "mp3"
        if "video" in header if "," in data else "": ext = "mp4"
        
        file_data = base64.b64decode(encoded)
        filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        with open(filepath, "wb") as f:
            f.write(file_data)
        return filepath
    except Exception as e:
        print(f"File Save Error: {e}")
        return None

@app.route('/', methods=['GET'])
def home():
    return "News Video Server is Running! Use /render endpoint."

@app.route('/render', methods=['POST'])
def render_video():
    try:
        data = request.json
        print("Starting Render Job...")

        # 1. Save Files
        audio_path = save_base64_file(data.get('audioData'), "audio")
        logo_path = save_base64_file(data.get('logoData'), "logo")
        bgm_path = save_base64_file(data.get('bgmData'), "bgm")
        ticker_text = data.get('tickerText', '')
        
        clips = data.get('clips', [])
        if not audio_path or not clips:
            return jsonify({"error": "Audio and Images required"}), 400

        # 2. Build FFmpeg Input
        inputs = []
        filter_complex = []
        
        # Input 0: Audio
        inputs.extend(['-i', audio_path])
        
        # Inputs 1 to N: Images
        clip_streams = []
        current_idx = 1
        
        for i, clip in enumerate(clips):
            img_path = save_base64_file(clip.get('imageData'), f"img_{i}")
            duration = clip.get('duration', 5)
            
            inputs.extend(['-loop', '1', '-t', str(duration), '-i', img_path])
            
            # Scale to HD (1280x720)
            filter_complex.append(f"[{current_idx}:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];")
            clip_streams.append(f"[v{i}]")
            current_idx += 1
            
        # Concat Images
        concat_str = "".join(clip_streams)
        filter_complex.append(f"{concat_str}concat=n={len(clip_streams)}:v=1:a=0[base];")
        last_stream = "[base]"

        # Add Logo
        if logo_path:
            inputs.extend(['-i', logo_path])
            filter_complex.append(f"[{current_idx}:v]scale=150:-1[logo];")
            filter_complex.append(f"{last_stream}[logo]overlay=20:20[vid_logo];")
            last_stream = "[vid_logo]"
            current_idx += 1

        # Add Ticker (Simplified)
        if ticker_text:
            # Note: Requires font, using default might fail on minimal docker without font packages
            # We will try basic drawtext, if it fails, try without
            pass 

        # Add BGM
        audio_map = "[0:a]"
        if bgm_path:
            inputs.extend(['-i', bgm_path])
            filter_complex.append(f"[{current_idx}:a]volume=0.1[bgm];[0:a][bgm]amix=inputs=2:duration=first[a_out];")
            audio_map = "[a_out]"
            current_idx += 1

        # Output File
        output_filename = f"video_{uuid.uuid4().hex}.mp4"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)

        cmd = [
            'ffmpeg', '-y',
            *inputs,
            '-filter_complex', "".join(filter_complex),
            '-map', last_stream,
            '-map', audio_map,
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-shortest',
            output_path
        ]
        
        print("Running FFmpeg...")
        subprocess.run(cmd, check=True)

        return send_file(output_path, as_attachment=True, download_name="news_video.mp4")

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
