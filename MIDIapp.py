from flask import Flask, request, render_template, jsonify
import os
import json
import statistics
from collections import Counter
from music21 import converter, tempo, meter, key, stream, note, chord
from openai import OpenAI

# =====================
# 環境変数
# =====================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY が設定されていません")

client = OpenAI(api_key=api_key)

app = Flask(__name__)

# =====================
# メロディ検出
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
# ハーモニー
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
# メロディ
# =====================
def evaluate_melody(part):
    if not part:
        return 0

    notes = [n for n in part.recurse().notes if n.isNote]
    if len(notes) < 2:
        return 0

    small = 0
    for i in range(len(notes)-1):
        diff = abs(notes[i+1].pitch.midi - notes[i].pitch.midi)
        if diff <= 2:
            small += 1

    smooth = (small / (len(notes)-1)) * 10

    pitches = [n.pitch.midi for n in notes]
    diff = max(pitches) - min(pitches)
    range_score = max(0, 10 - abs(diff - 15))

    return round(smooth + range_score, 1)

# =====================
# リズム
# =====================
def evaluate_rhythm(score):
    if not score.parts:
        return 0

    measured = score.parts[0].makeMeasures(inPlace=False)
    measures = list(measured.recurse().getElementsByClass(stream.Measure))
    counts = [len(m.notes) for m in measures if len(m.notes) > 0]

    if len(counts) < 2:
        return 0

    std = statistics.stdev(counts)
    density = max(0, 10 - std)

    most_common_count = Counter(counts).most_common(1)[0][1]
    groove = (most_common_count / len(counts)) * 10

    return round(density + groove, 1)

# =====================
# 総合
# =====================
def evaluate_music(score):
    key_obj = score.analyze("key")
    melody_part = detect_melody_part(score)

    harmony = evaluate_harmony(score, key_obj)
    melody = evaluate_melody(melody_part)
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
# MIDI統合
# =====================
def merge_midis(file_paths):
    merged = stream.Score()

    base = converter.parse(file_paths[0])
    for el in base.recurse():
        if isinstance(el, (tempo.MetronomeMark, meter.TimeSignature, key.Key)):
            merged.insert(0, el)

    for path in file_paths:
        score = converter.parse(path)
        for part in score.parts:
            merged.append(part.flatten())

    return merged

# =====================
# JSON出力
# =====================
def export_musicxml_and_json(score):
    os.makedirs("output", exist_ok=True)

    xml_path = "output/debug.musicxml"
    json_path = "output/notes.json"
    score_path = "output/score.json"

    score.write("musicxml", fp=xml_path)

    notes_data = []

    for el in score.recurse():
        if isinstance(el, note.Note):
            notes_data.append({
                "type": "note",
                "pitch": el.pitch.nameWithOctave,
                "midi": el.pitch.midi,
                "offset": float(el.offset),
                "duration": float(el.quarterLength),
                "velocity": el.volume.velocity if el.volume and el.volume.velocity else 64,
            })

        elif isinstance(el, chord.Chord):
            notes_data.append({
                "type": "chord",
                "pitches": [p.nameWithOctave for p in el.pitches],
                "midis": [p.midi for p in el.pitches],
                "offset": float(el.offset),
                "duration": float(el.quarterLength),
            })

    scores = evaluate_music(score)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(notes_data, f, ensure_ascii=False, indent=2)

    with open(score_path, "w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)

    return {
        "musicxml_path": xml_path,
        "json_path": json_path,
        "score_path": score_path,
        "event_count": len(notes_data),
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
【まとめ】 各項目の要約 

【スコア】 採点結果をそのまま載せる 

【良い点】 スコアの高いところを理論的にほめる 

【改善点】 どの部分がどう違うかを詳しく終える どの部分がどう違うかを詳しく教える 

【改善案】 指摘したところの具体的な変更案をそれぞれにいくつか用意する
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "音楽理論に詳しい教師として説明してください。"},
                {"role": "user", "content": input_text},
            ],
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"エラー: {str(e)}"

# =====================
# ルート
# =====================
@app.route("/", methods=["GET", "POST"])
def index():
    feedback = None

    if request.method == "POST":
        files = request.files.getlist("midi_file")

        if not files:
            return jsonify({"error": "ファイルなし"})

        intention = request.form.get("intention", "なし")
        os.makedirs("uploads", exist_ok=True)

        paths = []
        for f in files:
            if f.filename.endswith(".mid"):
                path = os.path.join("uploads", f.filename)
                f.save(path)
                paths.append(path)

        if not paths:
            return jsonify({"error": "MIDIなし"})

        score = merge_midis(paths)
        info = export_musicxml_and_json(score)

        feedback = analyze_json_with_ai(
            info["json_path"],
            info["score_path"],
            intention
        )

    return render_template("index.html", feedback=feedback)

# =====================
# Railway対応
# =====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
