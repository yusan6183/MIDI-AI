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
以下のABC記法で記述されたMIDIデータの解析結果を元に、メロディ、ハーモニー、リズムの特徴を分析してください。

【解析データ（ABC記法）】
{abc_text}

【ユーザーの意図】
{intention}

【指示】
解析データをもとに、以下の順でフィードバックを記述してください。各項目はーーーーーーーーーーーーーーーーーーーーー線で区切ってください。

・まとめ（改善点と改善案の要点）

【採点】
【ハーモニー】＊和音を使うトラックがあれば採点
　・キー適合性　点数＝（使われているキーのスケール内の音の総数/データ内の全音数）×10（10点満点、少数第一位で四捨五入）
　・始まりの安定感　点数＝（始まりのコードがI,IV,VI系のコード進行の総数/データ内の全コード進行の数）×10（10点満点、少数第一位で四捨五入）
　・終わりの安定感　点数＝（終わりのコードがI,V,VI系のコード進行の総数/データ内の全コード進行の数）×10（10点満点、少数第一位で四捨五入)
  ・コードのバリエーション　点数＝（使われたすべてのコードの種類（G、Am、Am7、Gsus4等をすべて１種類とする）/全小節数の平方根）×10（10点満点、少数第一位で四捨五入)
  ・コードチェンジの安定感　点数＝（隣あうコードの平均移動距離（半音でカウント））３．８＜平均値＜４．２で10点　以降平均値が0.1ズレるごとに1点減点
  ・総点数　得点/50点

【メロディ】＊ベーストラックを除く単音のトラックがあれば採点
　・メロディの滑らかさ　点数＝（隣り合う音の音程差が３以下の数/総移動回数）×10（10点満点、少数第一位で四捨五入)
　・音の高さの範囲　点数＝　１０ー（最高音と最低音の差（全音でカウント）ー１５の絶対値）　最低０点
　・リズムとの一致　点数＝　（1拍目または３拍目がメロディー音の開始地点になっている小節/全小節数）×10（10点満点、少数第一位で四捨五入）
　・繰り返しの有無　点数＝　（同じメロディーを繰り返している小節×３/全小節）　×10（10点満点、少数第一位で四捨五入）
　・コードとの相性　点数＝　（その瞬間のコード構成音と一致しているメロディー音の総数/全メロディー音数×0.6）×10（10点満点、少数第一位で四捨五入）
　・総点数　得点/50点

【リズム】＊ベースまたはドラムトラックがあれば採点
　・拍子の一致　点数＝１０－（拍子とリズムが不一致の小節/全小節）×10（10点満点、少数第一位で四捨五入）
　・ノリの均一感　点数＝（同一リズムの小節×４/全小節）×10（10点満点、少数第一位で四捨五入）
　・音の密度の均一感　点数＝（小節内の音符の標準偏差）　最大10点
　・リズムのバリエーション　点数＝異なるリズムの小節の種類　最大10点
　・総点数　得点/40点
　
満点でない項目は、関連する音楽理論を初心者向けに説明してください。

【詳細】＊コードに関するフィードバックを多めに
・使用したキー・コード：コード構成音、スケール構成音
・BPM・拍子：BPMの値、曲の拍子
・改善の余地がある理由（200字以上）
・具体的な改善方法（200字以上）
・意図に近づけるための工夫（200字以上）


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


