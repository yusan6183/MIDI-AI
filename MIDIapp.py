from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
import os
import json
from music21 import converter, tempo, meter, key, stream, note, chord
from openai import OpenAI

# =====================
# 追加：メロディ検出
# =====================
def detect_melody_part(score):
    best_part = None
    best_score = -1

    for part in score.parts:
        notes = [n for n in part.recurse().notes if n.isNote]
        if len(notes) < 10:
            continue

        avg_pitch = sum(n.pitch.midi for n in notes) / len(notes)
        pitch_range = max(n.pitch.midi for n in notes) - min(n.pitch.midi for n in notes)
        chord_count = len([c for c in part.recurse().getElementsByClass(chord.Chord)])

        score_val = avg_pitch * 0.5 + pitch_range * 0.3 - chord_count * 2

        if score_val > best_score:
            best_score = score_val
            best_part = part

    return best_part


# =====================
# ハーモニー採点
# =====================
def evaluate_harmony(score, key_obj):
    chords = list(score.chordify().recurse().getElementsByClass(chord.Chord))

    if not chords:
        return 0

    scale = [p.name for p in key_obj.pitches]

    total = 0
    inside = 0

    for c in chords:
        for p in c.pitches:
            total += 1
            if p.name in scale:
                inside += 1

    diatonic_score = (inside / total) * 10

    # 終止
    last = chords[-1]
    deg = key_obj.getScaleDegreeFromPitch(last.root())

    if deg == 1:
        cadence = 10
    elif deg == 5:
        cadence = 8
    else:
        cadence = 5

    return round(diatonic_score + cadence, 1)


# =====================
# メロディ採点
# =====================
def evaluate_melody(part):
    notes = [n for n in part.recurse().notes if n.isNote]

    if len(notes) < 2:
        return 0

    # 滑らかさ
    small = 0
    for i in range(len(notes)-1):
        diff = abs(notes[i+1].pitch.midi - notes[i].pitch.midi)
        if diff <= 2:
            small += 1

    smooth = (small / (len(notes)-1)) * 10

    # 音域
    pitches = [n.pitch.midi for n in notes]
    diff = max(pitches) - min(pitches)
    range_score = max(0, 10 - abs(diff - 15))

    return round(smooth + range_score, 1)


# =====================
# リズム採点
# =====================
import statistics

def evaluate_rhythm(score):
    measures = score.parts[0].getElementsByClass('Measure')

    counts = [len(m.notes) for m in measures if len(m.notes) > 0]

    if len(counts) < 2:
        return 0

    std = statistics.stdev(counts)
    density = max(0, 10 - std)

    from collections import Counter
    most = Counter(counts).most_common(1)[0][1]
    groove = (most / len(counts)) * 10

    return round(density + groove, 1)


# =====================
# 総合評価
# =====================
def evaluate_music(score):
    key_obj = score.analyze('key')

    melody_part = detect_melody_part(score)

    harmony = evaluate_harmony(score, key_obj)
    melody = evaluate_melody(melody_part) if melody_part else 0
    rhythm = evaluate_rhythm(score)

    total = harmony + melody + rhythm

    return {
        "key": str(key_obj),
        "harmony": harmony,
        "melody": melody,
        "rhythm": rhythm,
        "total": round(total, 1)
    }

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

    scores = evaluate_music(score)

    score_path = "output/score.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(notes_data, f, ensure_ascii=False, indent=2)

    return {
        "musicxml_path": musicxml_path,
        "json_path": json_path,
        "score_path": score_path, 
        "event_count": len(notes_data)
    }

# =====================
# AI解析
# =====================
def analyze_json_with_ai(notes_json_path, score_json_path, intention="なし"):
    try:
        with open(notes_json_path, "r", encoding="utf-8") as f:
            notes_data = json.load(f)

        with open(score_json_path, "r", encoding="utf-8") as f:
            scores = json.load(f)

        if not notes_data:
            return "解析可能な音符データがありませんでした。"

        input_text = f"""
あなたは音楽理論に詳しい、初心者にも分かりやすく教える教師です。

以下はMIDIから抽出されたJSON形式の音楽データとそれの採点結果、ユーザーの意図です。
音楽データの各要素には音の高さ、長さ、位置、強さが含まれています。

【採点結果】
{json.dumps(scores, ensure_ascii=False)}

【音楽データ】
{json.dumps(notes_data, ensure_ascii=False)}

【ユーザーの意図】
{intention}

このスコアをもとに以下のテンプレートを使って解説を作成してください。

【まとめ】
各項目の要約

【スコア】
採点結果をそのまま載せる

【良い点】
スコアの高いところを理論的にほめる

【改善点】
どの部分がどう違うかを詳しく終える

【改善案】
指摘したところの具体的な変更案をそれぞれにいくつか用意する

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
        feedback = analyze_json_with_ai(
            export_info["json_path"],
            export_info["score_path"],   
            intention
        )
        
    return render_template("index.html", feedback=feedback)

# =====================
# 起動
# =====================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
