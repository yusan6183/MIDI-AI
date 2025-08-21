from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
import os
import tempfile
from music21 import converter, analysis, chord
from openai import OpenAI

app = Flask(__name__)

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_midi(file_path):

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

あなたは音楽理論の教師です。
上記の結果を踏まえて学習者向けに
・なぜこの進行が改善の余地があるのか
・どう改善すればよいか
・意図に近づけるにはどうすればよいか
を優しくフィードバックしてください。特に、初歩的なミスや指摘がある場合は音楽理論の用語についても説明を加えて下さい。
"""

        response = client.chat.completions.create(
        model="gpt-5 mini",  
        messages=[
            {"role": "system", "content": "あなたは音楽理論に詳しい教師です。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if "midi_file" not in request.files:
            return jsonify({"error": "MIDIファイルがありません"})
        file = request.files["midi_file"]
        file_path = os.path.join("uploads", file.filename)
        os.makedirs("uploads", exist_ok=True)
        file.save(file_path)

        analysis_result = analyze_midi(file_path)
        feedback = generate_feedback(analysis_result)

        return render_template("index.html", feedback=feedback, analysis=analysis_result)

    return render_template("index.html", feedback=None, analysis=None)

if __name__ == "__main__":
    app.run(debug=True)

