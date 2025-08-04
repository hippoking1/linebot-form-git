from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import requests, base64, os
from io import BytesIO

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))

image_cache = {}

def upload_to_imgbb(image_bytes, api_key):
    img_base64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"key": api_key, "image": img_base64}
    res = requests.post("https://api.imgbb.com/1/upload", data=payload)
    res.raise_for_status()
    return res.json()["data"]["url"]

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400
    return "OK", 200

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_id = event.message.id
    content = line_bot_api.get_message_content(message_id)
    image_bytes = BytesIO(content.content).getvalue()
    try:
        img_url = upload_to_imgbb(image_bytes, os.environ.get("IMGBB_API_KEY"))
        image_cache[user_id] = img_url
        reply = (
            "✅ 圖片已上傳，請使用以下格式輸入：\n活動標題：XXX\n活動說明：YYY\n"
            "\n"
            "自訂預設題目：\n姓名：聯絡人姓名\n身份別：志工類型：社會大眾,環保志工,慈濟志工\n參加人數：停用\n"
            "\n"
            "自訂題目：\n簡答：手機號碼\n單選：參加場次：上午,下午\n多選：飲食偏好：蛋奶素,全素,皆可")
    except Exception as e:
        reply = f"❌ 圖片上傳失敗：{e}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text

    image_url = image_cache.get(user_id, "")

    if "活動標題：" in text and "活動說明：" in text:
        try:
            lines = text.split("\n")
            title = lines[0].replace("活動標題：", "").strip()

            # 取得活動說明段落
            description = ""
            start_idx = [i for i, line in enumerate(lines) if line.startswith("活動說明：")][0]
            description_lines = []
            for line in lines[start_idx:]:
                if line.startswith("自訂預設題目：") or line.startswith("自訂題目："):
                    break
                description_lines.append(line.strip())
            description = "\n".join(description_lines).replace("活動說明：", "").strip()

            default_questions = {}
            questions = []

            if "自訂預設題目：" in text:
                idx = lines.index("自訂預設題目：")
                for line in lines[idx+1:]:
                    if line == "自訂題目：":
                        break
                    if line.startswith("姓名："):
                        dq_title = line.replace("姓名：", "").strip()
                        if dq_title != "停用":
                            default_questions["姓名"] = {"title": dq_title}
                        else:
                            default_questions["姓名"] = {"enable": False}
                    elif line.startswith("身份別："):
                        q_part = line.replace("身份別：", "").strip()
                        if "：" in q_part:
                            dq_title, dq_choices = q_part.split("：", 1)
                            choices = [c.strip() for c in dq_choices.split(",")]
                            default_questions["身份別"] = {"title": dq_title.strip(), "choices": choices}
                        elif q_part == "停用":
                            default_questions["身份別"] = {"enable": False}
                    elif line.startswith("參加人數："):
                        dq_title = line.replace("參加人數：", "").strip()
                        if dq_title != "停用":
                            default_questions["參加人數"] = {"title": dq_title}
                        else:
                            default_questions["參加人數"] = {"enable": False}

            if "自訂題目：" in text:
                idx = lines.index("自訂題目：")
                for line in lines[idx+1:]:
                    if line.startswith("簡答："):
                        q_title = line.replace("簡答：", "").strip()
                        questions.append({"type": "簡答", "title": q_title})
                    elif line.startswith("單選："):
                        q_part = line.replace("單選：", "").strip()
                        if "：" in q_part:
                            q_title, q_choices = q_part.split("：", 1)
                            choices = [c.strip() for c in q_choices.split(",")]
                            questions.append({"type": "單選", "title": q_title.strip(), "choices": choices})
                    elif line.startswith("多選："):
                        q_part = line.replace("多選：", "").strip()
                        if "：" in q_part:
                            q_title, q_choices = q_part.split("：", 1)
                            choices = [c.strip() for c in q_choices.split(",")]
                            questions.append({"type": "多選", "title": q_title.strip(), "choices": choices})

            payload = {
                "title": title,
                "description": description,
                "imageUrl": image_url,
                "defaultQuestions": default_questions,
                "questions": questions
            }

            res = requests.post(os.environ.get("GOOGLE_SCRIPT_URL"), json=payload)
            res.raise_for_status()
            form_data = res.json()
            form_url = form_data.get("formUrl", "未取得表單連結")
            sheet_url = form_data.get("sheetUrl", "未取得回覆表單連結")
            reply_text = f"✅ 表單建立成功：\n{form_url}\n\n📊 回覆試算表：\n{sheet_url}"
        except Exception as e:
            reply_text = f"❌ 建立表單失敗：{e}"
    else:
        reply_text = (
            "請使用以下格式輸入：\n"
            "活動標題：XXX\n活動說明：YYY\n"
            "\n"
            "自訂預設題目：\n姓名：聯絡人姓名\n身份別：志工類型：社會大眾,環保志工,慈濟志工\n參加人數：停用\n"
            "\n"
            "自訂題目：\n簡答：手機號碼\n單選：參加場次：上午,下午\n多選：飲食偏好：蛋奶素,全素,皆可")

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
