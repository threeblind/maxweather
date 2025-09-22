import json
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

app = Flask(__name__)

# --- 環境変数に基づいた設定 ---
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

SUBSCRIPTIONS_FILE = 'subscriptions.json'

def load_subscriptions():
    """購読情報をファイルから読み込みます。"""
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return []
    try:
        with open(SUBSCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_subscriptions(subscriptions):
    """購読情報をファイルに保存します。"""
    with open(SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(subscriptions, f, indent=2, ensure_ascii=False)

@app.route('/api/save-subscription', methods=['POST'])
def save_subscription():
    """フロントエンドからPOSTされた購読情報を受け取り、保存します。"""
    subscription = request.json
    if not subscription or 'endpoint' not in subscription:
        return jsonify({'error': 'Invalid subscription data'}), 400

    subscriptions = load_subscriptions()
    # 既に同じエンドポイントが登録されていないか確認し、重複を避ける
    if not any(s['endpoint'] == subscription['endpoint'] for s in subscriptions):
        subscriptions.append(subscription)
        save_subscriptions(subscriptions)
        print(f"New subscription added: {subscription['endpoint']}")

    return jsonify({'message': 'Subscription saved successfully.'}), 201

if __name__ == '__main__':
    # FLASK_ENVが'development'の場合のみデバッグモードを有効にする
    is_debug_mode = (FLASK_ENV == 'development')
    app.run(port=5000, debug=is_debug_mode)
