from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage, TextSendMessage
)

import requests
import base64
from io import BytesIO
import os

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))

# 暫存圖片網址（以 user_id 為 key）
image_cache = {}

# === 圖片上傳至 imgbb ===
def upload_to_imgbb(image_bytes, api_key):
    img_base64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"key": api_key, "image": img_base64}
    res = requests.post("https://api.imgbb.com/1/upload", data=payload)
    if res.status_code == 200:
        return res.json()["data"]["url"]
    else:
        raise Exception("❌ imgbb 上傳失敗：" + res.text)

# === Webhook 接收 ===
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400

    return "OK", 200

# === 圖片訊息處理 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_id = event.message.id
    content = line_bot_api.get_message_content(message_id)
    image_bytes = BytesIO(content.content).getvalue()

    try:
        img_url = upload_to_imgbb(image_bytes, os.environ.get("IMGBB_API_KEY"))
        image_cache[user_id] = img_url
        reply = "✅ 圖片已上傳，請輸入活動資訊：\n活動標題：XXX\n活動說明：YYY"
    except Exception as e:
        reply = f"❌ 圖片上傳失敗：{e}"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# === 文字訊息處理 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text

    # 👉 查詢活動報名者清單
    if text.startswith("查詢活動："):
        title = text.split("查詢活動：")[1].strip()
        try:
            query_url = os.environ.get("GOOGLE_QUERY_URL")
            res = requests.get(query_url, params={"title": title})
            res.raise_for_status()
            data = res.json()
            names = data.get("names", [])
            reply_text = f"📊 活動：{title}\n參加者（{len(names)}人）：\n- " + "\n- ".join(names)
        except Exception as e:
            reply_text = f"❌ 查詢失敗：{e}"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 👉 建立報名表單
    image_url = image_cache.get(user_id, "")
    if "活動標題：" in text and "活動說明：" in text:
        try:
            title = text.split("活動標題：")[1].split("\n")[0].strip()
            description = text.split("活動說明：")[1].strip()

            payload = {
                "title": title,
                "description": description,
                "imageUrl": image_url
            }

            res = requests.post(os.environ.get("GOOGLE_SCRIPT_URL"), json=payload)
            res.raise_for_status()
            form_data = res.json()
            form_url = form_data.get("formUrl", "未取得表單連結")
            summary_url = form_data.get("summaryUrl", "未取得統計連結")

            reply_text = (
                f"📋 表單建立成功：\n{form_url}\n\n"
                f"📊 回覆統計頁：\n{summary_url}"
            )
        except Exception as e:
            reply_text = f"❌ 建立表單失敗：{e}"
    else:
        reply_text = "請使用以下格式輸入：\n活動標題：XXX\n活動說明：YYY"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# === 啟動伺服器 ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
