def evaluate_rhythm(score):
    if not score.parts:
        return 0

    measured_part = score.parts[0].makeMeasures(inPlace=False)
    measures = list(measured_part.recurse().getElementsByClass(stream.Measure))
    counts = [len(m.notes) for m in measures if len(m.notes) > 0]

    if len(counts) < 2:
        return 0

    std = statistics.stdev(counts)
    density = max(0, 10 - std)

    most_common_count = Counter(counts).most_common(1)[0][1]
    groove = (most_common_count / len(counts)) * 10

    return round(density + groove, 1)


# =====================
# 総合評価
# =====================
def evaluate_music(score):
    key_obj = score.analyze("key")
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
        "total": round(total, 1),
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

    base_score = converter.parse(file_paths[0])
    for el in base_score.recurse():
        if isinstance(el, (tempo.MetronomeMark, meter.TimeSignature, key.Key)):
            merged_score.insert(0, el)

    for path in file_paths:
        parsed_score = converter.parse(path)
        for part in parsed_score.parts:
            merged_score.append(part.flatten())

    return merged_score


# =====================
# MusicXML + JSON 書き出し
# =====================
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
どの部分がどう違うかを詳しく教える

【改善案】
指摘したところの具体的な変更案をそれぞれにいくつか用意する
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "あなたは音楽理論に詳しい、優しく教える教師です。"},
                {"role": "user", "content": input_text},
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
