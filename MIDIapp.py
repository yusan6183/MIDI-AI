from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
import os
from music21 import converter, tempo, meter, stream
from openai import OpenAI

# =====================
# Flask 基本設定
# =====================
app = Flask(__name__)
load_dotenv()

# =====================
# OpenAI API 設定
# =====================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("Warning: OPENAI_API_KEY is not set.")

client = OpenAI(api_key=api_key)

# =====================
# MIDI統合処理
# =====================
def merge_midis(file_paths):
    """
    複数MIDIを1つのScoreとして連結
    """
    merged_score = stream.Score()

    # 最初のMIDIからテンポ・拍子を取得
    base_score = converter.parse(file_paths[0])
    for el in base_score.recurse():
        if isinstance(el, (tempo.MetronomeMark, meter.TimeSignature)):
            merged_score.insert(0, el)

    # 順番に結合
    for path in file_paths:
        score = converter.parse(path)
        merged_score.append(score)

    return merged_score

# =====================
# ABC記法＋AI解析
# =====================
def analyze_score_with_abc(score, intention="なし"):
    try:
        os.makedirs("uploads", exist_ok=True)
        temp_abc_path = "uploads/temp_merged.abc"

        score.write("abc", fp=temp_abc_path)

        with open(temp_abc_path, "r", encoding="utf-8") as f:
            abc_text = f.read()

        if os.path.exists(temp_abc_path):
            os.remove(temp_abc_path)

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

・まとめ（改善点と改善案の要点）

【採点】
・キーとの適合性（20点）
・バリエーション（20点）
・終止の美しさ（10点）
・滑らかさ（20点）
・構成のまとまり（10点）
・方向性の一致（20点）
・総合スコア（100点満点）

満点でない項目は、関連する音楽理論を初心者向けに説明してください。

【詳細】
・使用したキー・コード（推定）：コード構成音、スケール構成音
・改善の余地がある理由
・具体的な改善方法
・意図に近づけるための工夫

専門用語はできるだけ避け、やさしく説明してください。
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "あなたは音楽理論に詳しい、優しく教える教師です。"},
                {"role": "user", "content": input_text}
            ],
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"解析エラーが発生しました: {str(e)}"

# =====================
# ルーティング
# =====================
@app.route("/", methods=["GET", "POST"])
def index():
    feedback = None

    if request.method == "POST":
        if "midi_file" not in request.files:
            return jsonify({"error": "MIDIファイルがありません"})

        files = request.files.getlist("midi_file")
        intention = request.form.get("intention", "なし")

        if not files or all(f.filename == "" for f in files):
            return jsonify({"error": "ファイルが選択されていません"})

        os.makedirs("uploads", exist_ok=True)

        file_paths = []

        for file in files:
            if not file.filename.lower().endswith(".mid"):
                continue

            path = os.path.join("uploads", file.filename)
            file.save(path)
            file_paths.append(path)

        if not file_paths:
            return jsonify({"error": "有効なMIDIファイルがありません"})

        # ★ 複数MIDIを1曲として統合
        merged_score = merge_midis(file_paths)

        # ★ 統合楽曲を解析
        feedback = analyze_score_with_abc(merged_score, intention)

    return render_template("index.html", feedback=feedback)

# =====================
# 起動
# =====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
