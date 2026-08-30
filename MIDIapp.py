from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
import json
import math
import os
from collections import Counter

from music21 import chord, converter, key, meter, note, stream, tempo
from openai import OpenAI
from werkzeug.utils import secure_filename


def clamp(value, low=0, high=10):
    return max(low, min(high, value))


def score_round(value):
    return round(clamp(value), 1)


def part_notes(part):
    return [n for n in part.recurse().notes if n.isNote]


def chord_pitches(current_chord):
    return {p.pitchClass for p in current_chord.pitches}


def scale_pitch_classes(key_obj):
    return {p.pitchClass for p in key_obj.pitches}


def scale_names(key_obj):
    return [p.name for p in key_obj.pitches]


def get_time_signature(score):
    found = score.recurse().getElementsByClass(meter.TimeSignature).first()
    return found if found else meter.TimeSignature("4/4")


def get_measure_length(score):
    return float(get_time_signature(score).barDuration.quarterLength)


def get_measure_count(score):
    if not score.parts:
        return 1

    measured = score.parts[0].makeMeasures(inPlace=False)
    measures = list(measured.recurse().getElementsByClass(stream.Measure))
    non_empty = [m for m in measures if len(m.notesAndRests) > 0]
    return max(1, len(non_empty))


def get_chordified_chords(score):
    chords = []
    last_signature = None

    for current_chord in score.chordify().recurse().getElementsByClass(chord.Chord):
        if len(current_chord.pitches) < 2:
            continue

        signature = (
            round(float(current_chord.offset), 3),
            tuple(sorted(p.pitchClass for p in current_chord.pitches)),
        )
        if signature == last_signature:
            continue

        chords.append(current_chord)
        last_signature = signature

    return chords


def chord_label(current_chord):
    try:
        return current_chord.pitchedCommonName
    except Exception:
        return ".".join(str(p.pitchClass) for p in current_chord.pitches)


def detect_melody_part(score):
    best_part = None
    best_score = -1

    for part in score.parts:
        notes = part_notes(part)
        if len(notes) < 4:
            continue

        avg_pitch = sum(n.pitch.midi for n in notes) / len(notes)
        pitch_range = max(n.pitch.midi for n in notes) - min(n.pitch.midi for n in notes)
        chord_count = len(part.recurse().getElementsByClass(chord.Chord))
        score_value = avg_pitch * 0.45 + pitch_range * 0.25 - chord_count * 2

        if score_value > best_score:
            best_score = score_value
            best_part = part

    return best_part


def find_active_chord(chords, offset):
    active = None
    for current_chord in chords:
        if float(current_chord.offset) <= offset:
            active = current_chord
        else:
            break
    return active


def measure_position(offset, measure_length):
    if measure_length <= 0:
        return 0
    return float(offset) % measure_length


def is_near(value, targets, tolerance=0.08):
    return any(abs(value - target) <= tolerance for target in targets)


def rhythm_signature(measure):
    return tuple(
        (
            round(float(n.offset), 3),
            round(float(n.quarterLength), 3),
        )
        for n in measure.notes
    )


def stdev_safe(values):
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def evaluate_harmony(score, key_obj):
    chords = get_chordified_chords(score)
    measure_count = get_measure_count(score)
    scale = scale_pitch_classes(key_obj)

    if not chords:
        items = {
            "キーとの調和": 0,
            "コード進行の自然さ": 0,
            "終止感・解決感": 0,
            "コードの変化とまとまり": 0,
        }
        return {"items": items, "total": 0}

    total_tones = 0
    in_key_tones = 0
    for current_chord in chords:
        for p in current_chord.pitches:
            total_tones += 1
            if p.pitchClass in scale:
                in_key_tones += 1

    key_fit = 10 if total_tones == 0 else 5 + (in_key_tones / total_tones) * 5

    transition_scores = []
    functional_pairs = {
        (1, 4), (1, 5), (1, 6),
        (2, 5), (4, 5), (4, 1),
        (5, 1), (5, 6), (6, 2), (6, 4),
    }

    for first, second in zip(chords, chords[1:]):
        first_root = first.root()
        second_root = second.root()
        if not first_root or not second_root:
            continue

        first_degree = key_obj.getScaleDegreeFromPitch(first_root)
        second_degree = key_obj.getScaleDegreeFromPitch(second_root)
        root_distance = abs((second_root.pitchClass - first_root.pitchClass) % 12)
        shared_tones = len(chord_pitches(first) & chord_pitches(second))

        value = 3
        if first_degree and second_degree:
            value += 1.5
        if (first_degree, second_degree) in functional_pairs:
            value += 3
        if root_distance in {5, 7}:
            value += 2
        if shared_tones > 0:
            value += min(1.5, shared_tones * 0.75)

        transition_scores.append(clamp(value))

    progression_naturalness = (
        sum(transition_scores) / len(transition_scores)
        if transition_scores else 5
    )

    cadence_resolution = 4
    last_root = chords[-1].root()
    last_degree = key_obj.getScaleDegreeFromPitch(last_root) if last_root else None

    if len(chords) >= 2:
        prev_root = chords[-2].root()
        prev_degree = key_obj.getScaleDegreeFromPitch(prev_root) if prev_root else None
        if prev_degree == 5 and last_degree == 1:
            cadence_resolution = 10
        elif prev_degree == 4 and last_degree == 1:
            cadence_resolution = 9
        elif prev_degree == 2 and last_degree == 5:
            cadence_resolution = 7
        elif last_degree == 1:
            cadence_resolution = 8
        elif last_degree == 6:
            cadence_resolution = 6
        elif last_degree == 5:
            cadence_resolution = 5
    elif last_degree == 1:
        cadence_resolution = 8

    if len(chords) >= 3:
        third_root = chords[-3].root()
        third_degree = key_obj.getScaleDegreeFromPitch(third_root) if third_root else None
        prev_root = chords[-2].root()
        prev_degree = key_obj.getScaleDegreeFromPitch(prev_root) if prev_root else None
        if third_degree == 2 and prev_degree == 5 and last_degree == 1:
            cadence_resolution = 10

    unique_labels = {chord_label(c) for c in chords}
    ideal_unique = max(2, math.sqrt(measure_count) * 1.4)
    variation_ratio = len(unique_labels) / ideal_unique
    variation_cohesion = 10 - abs(variation_ratio - 1) * 5

    items = {
        "キーとの調和": score_round(key_fit),
        "コード進行の自然さ": score_round(progression_naturalness),
        "終止感・解決感": score_round(cadence_resolution),
        "コードの変化とまとまり": score_round(variation_cohesion),
    }
    return {"items": items, "total": round(sum(items.values()), 1)}


def evaluate_melody(score, melody_part, key_obj):
    empty_items = {
        "旋律の滑らかさ": 0,
        "旋律の音域バランス": 0,
        "リズムとの噛み合い": 0,
        "コードとの関係": 0,
    }
    if melody_part is None:
        return {"items": empty_items, "total": 0}

    notes = part_notes(melody_part)
    if len(notes) < 2:
        return {"items": empty_items, "total": 0}

    interval_scores = []
    for i in range(len(notes) - 1):
        first_diff = notes[i + 1].pitch.midi - notes[i].pitch.midi
        abs_diff = abs(first_diff)

        if abs_diff <= 3:
            interval_scores.append(1)
        elif i + 2 < len(notes):
            next_diff = notes[i + 2].pitch.midi - notes[i + 1].pitch.midi
            if first_diff * next_diff < 0 and abs(next_diff) <= 5:
                interval_scores.append(0.75)
            else:
                interval_scores.append(0.35)
        else:
            interval_scores.append(0.45)

    smoothness = (sum(interval_scores) / len(interval_scores)) * 10

    pitches = [n.pitch.midi for n in notes]
    pitch_range = max(pitches) - min(pitches)
    if 12 <= pitch_range <= 19:
        range_control = 10
    elif pitch_range < 12:
        range_control = 10 - (12 - pitch_range) * 0.8
    else:
        range_control = 10 - (pitch_range - 19) * 0.6

    measure_length = get_measure_length(score)
    good_starts = 0
    for n in notes:
        position = measure_position(n.offset, measure_length)
        beat_grid = [i * 0.5 for i in range(int(measure_length * 2) + 1)]
        strong_beats = [0, 2] if measure_length >= 4 else [0]

        if is_near(position, strong_beats):
            good_starts += 1
        elif is_near(position, beat_grid):
            good_starts += 0.8
        elif float(n.quarterLength) <= 0.5:
            good_starts += 0.55

    rhythm_fit = (good_starts / len(notes)) * 10

    chords = get_chordified_chords(score)
    scale = scale_pitch_classes(key_obj)
    relation_scores = []
    for n in notes:
        active_chord = find_active_chord(chords, float(n.offset))
        if active_chord is None:
            relation_scores.append(0.6 if n.pitch.pitchClass in scale else 0.35)
        elif n.pitch.pitchClass in chord_pitches(active_chord):
            relation_scores.append(1)
        elif n.pitch.pitchClass in scale:
            relation_scores.append(0.7)
        elif float(n.quarterLength) <= 0.5:
            relation_scores.append(0.4)
        else:
            relation_scores.append(0.1)

    chord_relationship = (sum(relation_scores) / len(relation_scores)) * 10

    items = {
        "旋律の滑らかさ": score_round(smoothness),
        "旋律の音域バランス": score_round(range_control),
        "リズムとの噛み合い": score_round(rhythm_fit),
        "コードとの関係": score_round(chord_relationship),
    }
    return {"items": items, "total": round(sum(items.values()), 1)}


def evaluate_rhythm(score):
    empty_items = {
        "拍子との整合性": 0,
        "リズムパターンの一貫性": 0,
        "パターン数のバランス": 0,
        "音の密度と休符の使い方": 0,
    }
    if not score.parts:
        return {"items": empty_items, "total": 0}

    measure_length = get_measure_length(score)
    all_measures = []
    for part in score.parts:
        measured_part = part.makeMeasures(inPlace=False)
        all_measures.extend(measured_part.recurse().getElementsByClass(stream.Measure))

    measures = [m for m in all_measures if len(m.notes) > 0]
    if not measures:
        return {"items": empty_items, "total": 0}

    grid_scores = []
    for m in measures:
        starts = [float(n.offset) for n in m.notes]
        if not starts:
            continue

        good = 0
        grid = [i * 0.5 for i in range(int(measure_length * 2) + 1)]
        for start in starts:
            if is_near(start, grid):
                good += 1
        grid_scores.append(good / len(starts))

    meter_consistency = (
        sum(grid_scores) / len(grid_scores) * 10
        if grid_scores else 0
    )

    signatures = [rhythm_signature(m) for m in measures]
    signature_counts = Counter(signatures)
    most_common = signature_counts.most_common(1)[0][1]
    pattern_consistency = clamp((most_common / len(signatures)) * 14)

    unique_ratio = len(signature_counts) / len(signatures)
    variation_balance = 10 - abs(unique_ratio - 0.35) * 16

    note_counts = [len(m.notes) for m in measures]
    avg_density = sum(note_counts) / len(note_counts)
    density_std = stdev_safe(note_counts)
    density_score = 10 - abs(avg_density - 4) * 1.2 - density_std * 0.8

    rest_measures = sum(1 for m in measures if any(r.isRest for r in m.notesAndRests))
    rest_ratio = rest_measures / len(measures)
    space_bonus = 1.5 if 0.15 <= rest_ratio <= 0.75 else 0
    density_and_space = density_score + space_bonus

    items = {
        "拍子との整合性": score_round(meter_consistency),
        "リズムパターンの一貫性": score_round(pattern_consistency),
        "パターン数のバランス": score_round(variation_balance),
        "音の密度と休符の使い方": score_round(density_and_space),
    }
    return {"items": items, "total": round(sum(items.values()), 1)}


def evaluate_music(score):
    key_obj = score.analyze("key")
    melody_part = detect_melody_part(score)
    harmony = evaluate_harmony(score, key_obj)
    melody = evaluate_melody(score, melody_part, key_obj)
    rhythm = evaluate_rhythm(score)
    total = harmony["total"] + melody["total"] + rhythm["total"]

    return {
        "key": str(key_obj),
        "scale_notes": scale_names(key_obj),
        "harmony": harmony,
        "melody": melody,
        "rhythm": rhythm,
        "total": round(total, 1),
        "max_total": 120,
    }


load_dotenv(".env", override=True)
load_dotenv(".env.txt", override=True)

api_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip('"').strip("'")
client = OpenAI(api_key=api_key, timeout=45) if api_key else None
app = Flask(__name__)


def merge_midis(file_paths):
    merged_score = stream.Score()
    base_score = converter.parse(file_paths[0])

    for el in base_score.recurse():
        if isinstance(el, (tempo.MetronomeMark, meter.TimeSignature, key.Key)):
            merged_score.insert(0, el)

    for path in file_paths:
        parsed_score = converter.parse(path)
        for part in parsed_score.parts:
            merged_score.append(part.flatten())

    return merged_score


def export_musicxml_and_json(score):
    os.makedirs("output", exist_ok=True)
    musicxml_path = "output/debug.musicxml"
    json_path = "output/notes.json"
    score_path = "output/score.json"

    score.write("musicxml", fp=musicxml_path)

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
        "musicxml_path": musicxml_path,
        "json_path": json_path,
        "score_path": score_path,
        "event_count": len(notes_data),
    }


def analyze_json_with_ai(notes_json_path, score_json_path, intention="none"):
    try:
        if client is None:
            return "OPENAI_API_KEY が設定されていません。.env または .env.txt に OPENAI_API_KEY を設定してください。"

        with open(notes_json_path, "r", encoding="utf-8") as f:
            notes_data = json.load(f)

        with open(score_json_path, "r", encoding="utf-8") as f:
            scores = json.load(f)

        if not notes_data:
            return "No analyzable note data was found."

        input_text = f"""
あなたは音楽理論に詳しい、初心者にもわかりやすく教える教師です。

以下はMIDIから抽出されたMusicXML形式の解析データ、それに基づいた採点結果、そしてユーザーの意図です。

[解析データ]
{json.dumps(notes_data, ensure_ascii=False)}

[採点結果]
{json.dumps(scores, ensure_ascii=False)}

[ユーザーの意図]
{intention}

これらもとに、以下のテンプレートを使いフィードバックを作成してください。:

[まとめ]
良かった点、改善点と改善策を簡潔にまとめてください。

[点数]
採点結果をそのまま提示して下さい。

[良かった点]
評価点が高かった項目について、なぜ良かったのか音楽理論に基づいてできるだけ詳しく説明してください。

[改善点]
評価点が低かった項目について、なぜ低かったのかを音楽理論に基づいてできる限り詳しく説明してください。

[改善策]
先ほど挙げた改善点に対してそれぞれにいくつか具体的な改善案を提示し、改善の例なども挙げてください。
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a kind music theory teacher. Reply in Japanese."},
                {"role": "user", "content": input_text},
            ],
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"AI解析エラー: {str(e)}"


@app.route("/", methods=["GET", "POST"])
def index():
    feedback = None

    if request.method == "POST":
        files = request.files.getlist("midi_file")
        if not files:
            return jsonify({"error": "No MIDI file was uploaded."})

        intention = request.form.get("intention", "none")
        genre = request.form.get("genre", "unspecified")
        intention = f"{intention}\nGenre: {genre}"
        os.makedirs("uploads", exist_ok=True)

        file_paths = []
        for file in files:
            filename = secure_filename(file.filename)
            if filename.lower().endswith((".mid", ".midi")):
                path = os.path.join("uploads", filename)
                file.save(path)
                file_paths.append(path)

        if not file_paths:
            return jsonify({"error": "No valid MIDI file was uploaded."})

        merged_score = merge_midis(file_paths)
        export_info = export_musicxml_and_json(merged_score)
        feedback = analyze_json_with_ai(
            export_info["json_path"],
            export_info["score_path"],
            intention,
        )

    return render_template("index.html", feedback=feedback)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
