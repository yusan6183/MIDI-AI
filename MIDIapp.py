from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
import os
from music21 import converter
from openai import OpenAI

app = Flask(__name__)

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_midi(file_path, intention="なし"):

    try:
        score = converter.parse(file_path)
        chords = score.chordify()

        chord_list = []
        for c in chords.recurse().getElementsByClass("Chord"):
            if c.isChord:
                notes = [p.nameWithOctave for p in c.pitches]
                chord_repr = f"[{', '.join(notes)}]"
                chord_list.append(chord_repr)

        input_text = f"""ユーザーの意図とキー：{intention}
コード進行：{' → '.join(chord_list)}
コードは連続しているコードを一つとして最大八つまでで、それ以上のコードがあったらリストから無視してください。
例：[F3 A3 C4] → [G3 B3 D4] → [A3 C4 E4] → [G3 B3 D4] → [F3 A3 C4] → [A3 C4 E4] → [G3 B3 D4] → [G3 B3 D4]　　これは七つになります

あなたは音楽理論の教師です。
まとめの前に以下の項目で採点を行ってください
・キーとの適合性、そのキーで使用されるコードがあるごとに5点、最大20点
・バリエーション、使われているコード1つにつき5点、最大20点　コードの数え方は上記を参照
・終止の美しさ、コード進行の最初がI、IV、VIで始まると5点、最後がIかVIで終わると5点　最大10点
・滑らかさ、コードの間が完全4度以内の移動であれば5点、全部完全4度以内の移動ならさらに5点　最大20点
・創造性、音楽理論の知識を応用したり工夫したりしていれば加点　最大30点
・総合スコア　スコア/100点での表示

また、上記のリスト結果を踏まえて学習者向けに
・使用したキー・コード
・なぜこの進行が改善の余地があるのか
・どう改善すればよいか
・意図に近づけるにはどうすればよいか
を優しくフィードバックしてください。
各項目をーーーーーーーーーーーーーーーーーーーー線で区切ってフィードバックを生成してください。
できるだけ音楽理論用語の多用は避け、出てきた用語は初心者にもわかりやすく説明してください。
最初にまとめを提示してから詳しいフィードバックをしてください。

最後に「もしもう少し詳しい背景や意図があれば、さらに具体的なアドバイスができますのでいつでも教えてくださいね！」などといったコメントはつけないように。

上記のデータはMIDIデータをmusic21で解析したものです。
"""
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "あなたは音楽理論に詳しい教師です。"},
                {"role": "user", "content": input_text}
            ],
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"解析エラー: {str(e)}"

        response = client.chat.completions.create(
            model="gpt-4.1-mini",  
            messages=[
                {"role": "system", "content": "あなたは音楽理論に詳しい教師です。"},
                {"role": "user", "content": input_text}
            ],
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"解析エラー: {str(e)}"


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if "midi_file" not in request.files:
            return jsonify({"error": "MIDIファイルがありません"})

        file = request.files["midi_file"]

        intention = request.form.get("intention", "なし")

        os.makedirs("uploads", exist_ok=True)
        file_path = os.path.join("uploads", file.filename)
        file.save(file_path)

        feedback = analyze_midi(file_path, intention)

        return render_template("index.html", feedback=feedback)

    return render_template("index.html", feedback=None)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


