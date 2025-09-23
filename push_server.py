import json
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException
from supabase import create_client, Client


# .envファイルから環境変数を読み込む
load_dotenv()

app = Flask(__name__)

# --- 環境変数に基づいた設定 ---
# Supabaseクライアントの初期化
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key) if url and key else None

# VAPIDキーはRenderの環境変数から読み込む
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {
    "sub": f"mailto:{os.getenv('VAPID_MAILTO', 'default-email@example.com')}"
}

if not VAPID_PRIVATE_KEY:
    print("警告: 環境変数 VAPID_PRIVATE_KEY が設定されていません。プッシュ通知は送信できません。")


FLASK_ENV = os.getenv('FLASK_ENV', 'production')  # デフォルトは安全のため 'production'

# 環境に応じてCORSのオリジンを選択
if FLASK_ENV == 'development':
    allowed_origin = os.getenv('DEV_CORS_ORIGIN')
else:
    allowed_origin = os.getenv('PROD_CORS_ORIGIN')

if allowed_origin:
    CORS(app, resources={r"/api/*": {"origins": allowed_origin}})
    print(f"CORS is enabled for origin: {allowed_origin} (mode: {FLASK_ENV})")
else:
    print(f"警告: CORSオリジンが設定されていません (mode: {FLASK_ENV})。APIへのアクセスがブロックされる可能性があります。")

badge_counter = 0  # グローバル変数で管理
def get_and_increment_badge_count():
    global badge_counter
    badge_counter += 1
    return badge_counter

def reset_badge_count():
    global badge_counter
    badge_counter = 0

@app.route('/api/config', methods=['GET'])
def get_config():
    """フロントエンドが必要とする設定情報を返します。"""
    vapid_public_key = os.getenv('VAPID_PUBLIC_KEY')
    if not vapid_public_key:
        return jsonify({'error': 'VAPID public key is not configured on the server.'}), 500

    return jsonify({
        'vapidPublicKey': vapid_public_key
    })

@app.route('/api/save-subscription', methods=['POST'])
def save_subscription():
    """フロントエンドからPOSTされた購読情報を受け取り、保存します。"""
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 500

    subscription = request.json
    if not subscription or 'endpoint' not in subscription:
        return jsonify({'error': 'Invalid subscription data'}), 400

    # 購読情報を整形
    sub_data = {
        "endpoint": subscription.get("endpoint"),
        "p256dh": subscription.get("keys", {}).get("p256dh"),
        "auth": subscription.get("keys", {}).get("auth")
    }

    try:
        # 存在確認と挿入を一度に行う (upsert)
        # on_conflict='endpoint' は、endpointカラムが重複した場合に何もしない(無視する)という設定
        data, count = supabase.table('subscriptions').upsert(sub_data, on_conflict='endpoint').execute()
        print(f"Subscription saved/updated for endpoint: {sub_data['endpoint']}")
    except Exception as e:
        print(f"Error saving subscription: {e}")
        return jsonify({'error': 'Failed to save subscription'}), 500

    return jsonify({'message': 'Subscription saved successfully.'}), 201

@app.route('/api/send-notification', methods=['POST'])
def send_notification():
    if request.headers.get('X-API-Secret') != os.getenv('API_SECRET_KEY'):
        return jsonify({'error': 'Unauthorized'}), 401

    if not VAPID_PRIVATE_KEY:
        return jsonify({'error': 'VAPID key not configured on server'}), 500

    data = request.json
    title = data.get('title', '通知')
    body = data.get('body', '')

    # バッジカウントを常に含める
    payload_data = {
        "notification": {
            "title": title,
            "body": body,
            "icon": "images/icon-192x192.png",
            "badge": "images/icon-192x192.png"
        },
        "badge_count": badge_counter  # ←サーバーのグローバルカウンタ
    }
    notification_payload = json.dumps(payload_data)

    try:
        response = supabase.table('subscriptions').select("endpoint, p256dh, auth").execute()
        db_subscriptions = response.data
    except Exception as e:
        print(f"Error loading subscriptions: {e}")
        return jsonify({'error': 'Failed to load subscriptions'}), 500

    subscriptions = [
        {"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}
        for s in db_subscriptions
    ]

    if not subscriptions:
        return jsonify({'message': 'No subscribers to notify.'}), 200

    print(f"Sending notification to {len(subscriptions)} subscribers...")

    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=notification_payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS.copy(),
            )
        except WebPushException as ex:
            print(f"Notification failed for {sub.get('endpoint', 'N/A')}: {ex}")

    return jsonify({'message': f'Notification sent to {len(subscriptions)} subscribers.'}), 200


if __name__ == '__main__':
    # FLASK_ENVが'development'の場合のみデバッグモードを有効にする
    is_debug_mode = (FLASK_ENV == 'development')
    app.run(port=5000, debug=is_debug_mode)
