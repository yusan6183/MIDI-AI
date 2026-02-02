from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
import os
import json
from music21 import converter, tempo, meter, key, stream, note, chord
from openai import OpenAI

# =====================
# 環境変数読み込み
# =====================
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY が設定されていません。GitHubに公開する場合は .env に記載してください。")

client = OpenAI(api_key=api_key)

# =====================
# Flask 基本設定
# =====================
app = Flask(__name__)

# =====================
# MIDI統合
# =====================
def merge_midis(file_paths):
    """複数MIDIを1つのScoreとして統合"""
    merged_score = stream.Score()

    # 最初のMIDIからテンポ・拍子・キーを取得
    base_score = converter.parse(file_paths[0])
    for el in base_score.recurse():
        if isinstance(el, (tempo.MetronomeMark, meter.TimeSignature, key.Key)):
            merged_score.insert(0, el)

    # 各MIDIのPartを追加
    for path in file_paths:
        score = converter.parse(path)
        for part in score.parts:
            merged_score.append(part.flat)

    return merged_score

# =====================
# MusicXML + JSON 書き出し
# =====================
def export_musicxml_and_json(score):
    os.makedirs("output", exist_ok=True)

    musicxml_path = "output/debug.musicxml"
    json_path = "output/notes.json"

    # MusicXML
    score.write("musicxml", fp=musicxml_path)

    # JSON
    notes_data = []
    for el in score.recurse():
        if isinstance(el, note.Note):
            notes_data.append({
                "type": "note",
                "pitch": el.pitch.nameWithOctave,
                "midi": el.pitch.midi,
                "offset": float(el.offset),
                "duration": float(el.quarterLength),
                "velocity": el.volume.velocity if el.volume and el.volume.velocity else 64
            })
        elif isinstance(el, chord.Chord):
            notes_data.append({
                "type": "chord",
                "pitches": [p.nameWithOctave for p in el.pitches],
                "midis": [p.midi for p in el.pitches],
                "offset": float(el.offset),
                "duration": float(el.quarterLength)
            })

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(notes_data, f, ensure_ascii=False, indent=2)

    return {
        "musicxml_path": musicxml_path,
        "json_path": json_path,
        "event_count": len(notes_data)
    }

# =====================
# AI解析
# =====================
def analyze_json_with_ai(notes_json_path, intention="なし"):
    try:
        with open(notes_json_path, "r", encoding="utf-8") as f:
            notes_data = json.load(f)

        if not notes_data:
            return "解析可能な音符データがありませんでした。"

        input_text = f"""
あなたは音楽理論に詳しい、初心者にも分かりやすく教える教師です。

以下はMIDIから抽出されたJSON形式の音楽データです。
各要素には音の高さ、長さ、位置、強さが含まれています。

【解析データ（JSON）】
{json.dumps(notes_data, ensure_ascii=False)}

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

【詳細】＊コードに関するフィードバックを多めにすること。スケール構成音の例：Cメジャーキー「ド、レ、ミ、ファ、ソ、ラ、シ」、コード構成音の例：C[ド、ミ、ソ]。スケールやコードをフィードバックで書くときは必ず構成音を記述すること。
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
        files = request.files.getlist("midi_file")
        if not files:
            return jsonify({"error": "MIDIファイルがありません"})

        intention = request.form.get("intention", "なし")
        os.makedirs("uploads", exist_ok=True)

        file_paths = []
        for file in files:
            if file.filename.lower().endswith(".mid"):
                path = os.path.join("uploads", file.filename)
                file.save(path)
                file_paths.append(path)

        if not file_paths:
            return jsonify({"error": "有効なMIDIファイルがありません"})

        merged_score = merge_midis(file_paths)
        export_info = export_musicxml_and_json(merged_score)
        feedback = analyze_json_with_ai(export_info["json_path"], intention)

    return render_template("index.html", feedback=feedback)

# =====================
# 起動
# =====================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
