
# =====================
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY が設定されていません。GitHubに公開する場合は .env に記載してください。")

client = OpenAI(api_key=api_key)
client = OpenAI(api_key=api_key) if api_key else None


# =====================
# =====================
def analyze_json_with_ai(notes_json_path, score_json_path, intention="なし"):
    try:
        if client is None:
            return "OPENAI_API_KEY が設定されていません。Railway の Variables に OPENAI_API_KEY を追加してください。"

        with open(notes_json_path, "r", encoding="utf-8") as f:
            notes_data = json.load(f)

            return jsonify({"error": "MIDIファイルがありません"})

        intention = request.form.get("intention", "なし")
        genre = request.form.get("genre", "未指定")
        intention = f"{intention}\nジャンル: {genre}"
        os.makedirs("uploads", exist_ok=True)

        file_paths = []
# 起動
# =====================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
