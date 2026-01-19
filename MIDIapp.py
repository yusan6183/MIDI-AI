from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
import os
from music21 import converter, note, chord, tempo, meter
from openai import OpenAI

app = Flask(__name__)

load_dotenv()

# APIキーの確認（エラーハンドリング用）
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("Warning: OPENAI_API_KEY is not set.")

client = OpenAI(api_key=api_key)

from music21 import converter, abcFormat

def analyze_midi_with_abc(file_path, intention="なし"):
    try:
        # 1. MIDIファイルの読み込み
        score = converter.parse(file_path)
        
        # 2. ABC記法への変換
        # music21の内部機能を使って、StreamオブジェクトをABC形式の文字列に変換します
        abc_converter = abcFormat.translate.abcFileFromStream(score)
        abc_text = str(abc_converter)

        # 3. プロンプトの作成
        # 冗長なリストではなく、コンパクトなABC記法を「解析データ」として渡します
        input_text = f"""
あなたは音楽理論の教師です。
以下のABC記法で記述されたMIDIデータの解析結果を元に、楽曲の構造、コード進行、メロディの特徴を分析してください。

【解析データ（ABC記法）】
{abc_text}

【ユーザーの意図とキー】
{intention}

【指示】
解析データからコード進行を推測し、以下の項目について学習者向けに優しくフィードバックしてください。
フィードバックでコードを提示する際、Cm[C、Eb、G]のように構成音も必ず記述してください。

以下の順でフィードバックを記述してください。各項目はーーーーーーーーーーーーーーーーーーーーー線で区切ってください。

・まとめ（改善点と改善案の要点をまとめてください）

以下の項目で採点を行ってください：
・キーとの適合性（20点満点）
・バリエーション（20点満点）
・終止の美しさ（10点満点）
・滑らかさ（20点満点）
・構成のまとまり（10点）
・方向性の一致（20点満点）
・総合スコア：スコア/100点での表示

採点項目で満点でない部分は、その項目に関連する音楽理論を教えてください。

以下は詳細に記述してください：
・使用したキー・コード（推定）：コードの構成音、スケールの構成音
・なぜこの進行が改善の余地があるのか
・どう改善すればよいか
・意図に近づけるにはどうすればよいか

できるだけ音楽理論用語の多用は避け、初心者にわかりやすく解説してください。
最後に「詳しい背景があれば～」などの定型文はつけないでください。
"""

        # OpenAI API呼び出し
        response = client.chat.completions.create(
            model="gpt-4o-mini", # 最新の軽量モデルを指定（適宜変更してください）
            messages=[
                {"role": "system", "content": "あなたは音楽理論に詳しい、優しく教える教師です。"},
                {"role": "user", "content": input_text}
            ],
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"Error details: {e}") # デバッグ用にコンソール出力
        return f"解析エラーが発生しました: {str(e)}"

@app.route("/", methods=["GET", "POST"])
def index():
    feedback = None
    if request.method == "POST":
        if "midi_file" not in request.files:
            return jsonify({"error": "MIDIファイルがありません"})

        file = request.files["midi_file"]
        intention = request.form.get("intention", "なし")

        if file.filename == '':
             return jsonify({"error": "ファイルが選択されていません"})

        os.makedirs("uploads", exist_ok=True)
        file_path = os.path.join("uploads", file.filename)
        file.save(file_path)

        feedback = analyze_midi(file_path, intention)
        
        # 必要であれば保存したファイルを削除
        # os.remove(file_path)

    return render_template("index.html", feedback=feedback)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

