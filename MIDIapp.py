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

def analyze_midi(file_path, intention="なし"):
    try:
        # MIDIファイルの読み込み
        score = converter.parse(file_path)
        
        # --- メタデータの取得 (テンポ・拍子) ---
        # テンポ取得（見つからない場合はデフォルト120）
        metronome_marks = score.flatten().getElementsByClass(tempo.MetronomeMark)
        bpm = metronome_marks[0].number if metronome_marks else 120
        
        # 拍子取得（見つからない場合はデフォルト4/4）
        time_signatures = score.flatten().getElementsByClass(meter.TimeSignature)
        time_sig = f"{time_signatures[0].numerator}/{time_signatures[0].denominator}" if time_signatures else "4/4"

        # 解析データのテキスト構築開始
        midi_data_text = f'"tempo_bpm": {bpm},\n"time_signature": "{time_sig}",\n\n'

        # --- トラックごとの解析 ---
        for part in score.parts:
            track_name = part.partName or "Unknown Track"
            midi_data_text += f"Track_name={track_name}\nNotes: [\n"

            # 小節ごとに処理
            for measure in part.getElementsByClass('Measure'):
                measure_number = measure.number
                
                # 小節内の音符・コードを取得
                for element in measure.notes:
                    offset = element.offset # 小節内の位置
                    
                    # 音の長さ、MIDI番号、音名のリストを作成
                    durations = []
                    midi_pitches = []
                    note_names = []

                    if element.isChord:
                        # コードの場合
                        durations = [element.duration.quarterLength] * len(element.pitches) # 便宜上コード全体の長さを適用
                        midi_pitches = [p.midi for p in element.pitches]
                        note_names = [p.nameWithOctave for p in element.pitches]
                    elif element.isNote:
                        # 単音の場合
                        durations = [element.duration.quarterLength]
                        midi_pitches = [element.pitch.midi]
                        note_names = [element.pitch.nameWithOctave]
                    
                    # 指定されたフォーマットで文字列に追加
                    midi_data_text += "{\n"
                    midi_data_text += f"　小節{measure_number}\n"
                    midi_data_text += f"　小節内の位置{offset}\n"
                    midi_data_text += f"　音の長さ{durations}\n"
                    midi_data_text += f"　音の高さ{midi_pitches}\n"
                    midi_data_text += f"　音の高さ{note_names}\n"
                    midi_data_text += "}\n"
            
            midi_data_text += "]\n\n"

        # --- プロンプトの作成 ---
        # システムプロンプトと解析データを結合
        input_text = f"""
以下はMIDIデータを解析した詳細データです。
このデータを元に、楽曲の構造、コード進行、メロディの特徴を分析してください。

【解析データ】
{midi_data_text}

【ユーザーの意図とキー】
{intention}

【指示】
あなたは音楽理論の教師です。
解析データからコード進行を推測し、以下の項目について学習者向けに優しくフィードバックしてください。
解析データが複雑な場合でも、主要な和音やメロディラインを読み取ってください。
フィードバックでコードを提示する際、Cm[C、E-、G]のように構成音も必ず記述してください。

以下の順でフィードバックを記述してください。各項目はーーーーーーーーーーーーーーーーーーーーー線で区切ってください。

・まとめ（改善点と改善案の要点をまとめてください）

以下の項目で採点をミスがないように行ってください
・キーとの適合性（20点満点）：ダイアトニック内のコード数/使われた全コード数。適合していないコードの解説も含めてください
・バリエーション（20点満点）：使われたコードの種類/使われた全コード数
・終止の美しさ（10点満点）：コード進行の最初がトニック（Iかviｍ）かサブドミナント（IVかiiｍ）で始まると＋5点、最後の2コードがドミナント（iiiｍかV）→トニック（Iかviｍ）の場合は+5点
・滑らかさ（20点満点）：コード構成音の移動幅などから滑らかさを判断
・構成のまとまり（10点）：同じコード進行の繰り返しやリズムの統一感があれば加点
・方向性の一致（20点満点）：ユーザーの意図とキーに合致しているか（キー+5点、意図+15点）
・総合スコア：スコア/100点での表示

計算結果が正しいかの見直しを行ってください。
採点項目で満点でない部分は、その項目に関連する音楽理論を教えてください。

以下は詳細に記述してください
・使用したキー・コード（推定）：コードの構成音、スケールの構成音
・なぜこの進行が改善の余地があるのか
・どう改善すればよいか
・意図に近づけるにはどうすればよいか

できるだけ音楽理論用語の多用は避け、出てきた用語は初心者にもわかりやすく説明してください。
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
