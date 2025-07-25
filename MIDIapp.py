from flask import Flask, request, render_template
import requests
import os
import tempfile
from music21 import converter

app = Flask(__name__)

OLLAMA_API_URL = "http://localhost:11434/api/generate"  # OllamaのAPIエンドポイント

def call_mistral_api(prompt):
    response = requests.post(
        OLLAMA_API_URL,
        json={
            "model": "mistral",
            "prompt": prompt,
            "stream": False, 
            "max_tokens": 512,  
            "temperature": 0.7,
            "stop": ["###"]     
        },
    )
    if response.status_code == 200:
        return response.json().get("response", "").strip()
    else:
        return f"Error: {response.status_code} {response.text}"

@app.route("/", methods=["GET", "POST"])
def index():
    feedback = ""
    if request.method == "POST":
        midi_file = request.files.get("midi_file")
        intention = request.form.get("intention", "").strip()

        if midi_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mid") as tmp_file:
                midi_file.save(tmp_file.name)
                tmp_path = tmp_file.name

            try:
                score = converter.parse(tmp_path)
                estimated_key = score.analyze("key")
                chords = score.chordify()
                chord_list = [
                    c.commonName for c in chords.recurse().getElementsByClass("Chord") if c.isChord
                ]
                prompt = f"""
ユーザーの意図：{intention}
推定キー：{estimated_key.tonic.name} {estimated_key.mode}
コード進行：{', '.join(chord_list)}

上記を踏まえて学習者向けに
・なぜこの進行が改善の余地があるのか
・どう改善すればよいか
・意図に近づけるにはどうすればよいか
を優しくフィードバックしてください。特に、初歩的なミスや指摘がある場合は音楽理論の用語についても説明を加えて下さい。
"""
                feedback = call_mistral_api(prompt)
            except Exception as e:
                feedback = f"解析エラー: {str(e)}"
            finally:
                os.remove(tmp_path)

    return render_template("index.html", feedback=feedback)

if __name__ == "__main__":
    app.run(debug=True)
