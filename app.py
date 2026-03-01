from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid
import threading
import time

app = Flask(__name__)

# Vercel has read-only filesystem EXCEPT /tmp
DOWNLOAD_DIR = "/tmp/yt_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def cleanup_file(path, delay=300):
    def _delete():
        time.sleep(delay)
        if os.path.exists(path):
            os.remove(path)
    threading.Thread(target=_delete, daemon=True).start()


@app.route("/")
def index():
    html_path = os.path.join(BASE_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html"}


@app.route("/info", methods=["POST"])
def get_info():
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        ydl_opts = {"quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        seen = set()
        for f in info.get("formats", []):
            if f.get("vcodec") != "none" and f.get("acodec") != "none":
                res = f.get("height")
                if res and res not in seen:
                    seen.add(res)
                    size = f.get("filesize") or f.get("filesize_approx")
                    formats.append({
                        "format_id": f["format_id"],
                        "resolution": f"{res}p",
                        "ext": f.get("ext", "mp4"),
                        "size": round(size / (1024 * 1024), 1) if size else None,
                        "fps": f.get("fps"),
                    })

        formats.append({
            "format_id": "bestaudio/best",
            "resolution": "Audio only (MP3)",
            "ext": "mp3",
            "size": None,
            "fps": None
        })

        formats.sort(
            key=lambda x: int(x["resolution"].replace("p", "")) if x["resolution"].endswith("p") else 0,
            reverse=True
        )

        return jsonify({
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "view_count": info.get("view_count"),
            "formats": formats
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download", methods=["POST"])
def download():
    data = request.json or {}
    url = data.get("url", "").strip()
    format_id = data.get("format_id", "bestvideo+bestaudio/best")
    is_audio = data.get("is_audio", False)

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    file_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    try:
        if is_audio:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "quiet": True,
            }
        else:
            fmt = format_id if "+" in format_id else f"{format_id}+bestaudio/best"
            ydl_opts = {
                "format": fmt,
                "outtmpl": output_template,
                "merge_output_format": "mp4",
                "quiet": True,
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        for fname in os.listdir(DOWNLOAD_DIR):
            if fname.startswith(file_id):
                fpath = os.path.join(DOWNLOAD_DIR, fname)
                ext = fname.rsplit(".", 1)[-1]
                safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
                cleanup_file(fpath)
                return send_file(fpath, as_attachment=True, download_name=f"{safe_title}.{ext}")

        return jsonify({"error": "File not found after download"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("YouTube Downloader running at http://localhost:5000")
    app.run(debug=True, port=5000)
