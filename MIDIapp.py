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
ルート音の変化がなく音が追加されている場合はアルペジオと判断し、１つのコードとしてください
1. Gメジャーコード（G1, G2, G4） → 構成音：G, B, D  
2. GメジャーコードにB4追加（G1, G2, G4, B4） → 構成音同じ（Bが重複）  
3. GメジャーコードにD5追加（G1, G2, G4, B4, D5）  
4. GメジャーコードにA5追加（G1, G2, G4, B4, D5, A5）
ループしているコード進行は一つのコード進行としてください。

あなたは音楽理論の教師です。
上記の結果を踏まえて学習者向けに
・使用したキー・コード、コードの構成音は上記の結果をそのまま表示、スケールの構成音も記述すること
・なぜこの進行が改善の余地があるのか
・どう改善すればよいか
・意図に近づけるにはどうすればよいか
を優しくフィードバックしてください。
各項目をーーーーーーーーーーーーーーーーーーーーー線で区切って、ユーザーの意図とキーに使われた言語に合わせてフィードバックを生成してください。
できるだけ音楽理論用語の多用は避け、出てきた用語は初心者にもわかりやすく説明してください。
最初にまとめを提示してから詳しいフィードバックをしてください。
また、フィードバックでコードを提示する際、Cm[C、E-、G]のように構成音も必ず記述してください。

まとめの前に以下の項目で採点をミスがないように行ってください
・キーとの適合性、ダイアトニック内のコード数/使われた全コード数*20 最大20点
・バリエーション、使われたコードの種類/使われた全コード数*20　最大20点
・終止の美しさ、コード進行の最初がトニックかサブドミナントで始まると＋5点、最後の2コードがドミナント→トニックの場合は+5点　最大10点
・滑らかさ、コードの間が５半音以内の移動であれば5点、全部５半音以内の移動ならさらに5点　最大20点
・構成のまとまり、同じコード進行が繰り返されていれば+10点　
・方向性の一致、ユーザーの意図とキーに合致しているか　キーは+5点　意図は+15点　最大20点
・総合スコア　スコア/100点での表示

採点項目で満点でない部分は、その項目に関連する音楽理論を教えてください。また、採点項目ごとに満点をこえないようにしてください。

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











