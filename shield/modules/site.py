from flask import Flask, request, render_template_string, redirect, session, jsonify
from datetime import datetime, timedelta
import requests
import random
import string
import base64
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import config
from shield import app as telegram_bot
from shield.database import db

app = Flask(__name__)
app.secret_key = os.urandom(24)

invite_requests = db['invite_requests']
channel_configs = db['channel_configs']

def generate_captcha():
    operations = ['+', '-', '*']
    operation = random.choice(operations)
    
    if operation == '+':
        num1 = random.randint(1, 20)
        num2 = random.randint(1, 20)
        answer = num1 + num2
    elif operation == '-':
        num1 = random.randint(10, 30)
        num2 = random.randint(1, 9)
        answer = num1 - num2
    else:
        num1 = random.randint(1, 10)
        num2 = random.randint(1, 10)
        answer = num1 * num2
    
    challenge = f"{num1} {operation} {num2} = ?"
    
    width, height = 220, 80
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except IOError:
        font = ImageFont.load_default()
    
    x_pos = 20
    for char in challenge:
        y_offset = random.randint(-5, 5)
        draw.text((x_pos, 30 + y_offset), char, font=font, fill=(255, 255, 255, 230))
        x_pos += random.randint(15, 25)
    
    for _ in range(300):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        draw.point((x, y), fill=(random.randint(100, 255), random.randint(100, 255), random.randint(100, 255)))
    
    for _ in range(8):
        x1 = random.randint(0, width - 1)
        y1 = random.randint(0, height - 1)
        x2 = random.randint(0, width - 1)
        y2 = random.randint(0, height - 1)
        draw.line([(x1, y1), (x2, y2)], fill=(random.randint(100, 255), random.randint(100, 255), random.randint(100, 255)), width=1)
    
    image = image.filter(ImageFilter.GaussianBlur(radius=0.5))
    
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    return {
        'challenge': challenge,
        'answer': str(answer),
        'image': img_str
    }

@app.route('/')
def landing_page():
    return render_template_string(LANDING_TEMPLATE)

@app.route('/verify')
def verify():
    uid = request.args.get('uid')
    entry = invite_requests.find_one({"uid": uid})
    if not entry or entry.get("used") or entry.get("expires_at") < datetime.utcnow():
        return render_template_string(ERROR_TEMPLATE, error_message="Link expired or invalid."), 400
    
    channel_id = entry.get("channel_id")
    
    captcha = generate_captcha()
    session['captcha_answer'] = captcha['answer']
    session['uid'] = uid
    session['channel_id'] = channel_id
    
    return render_template_string(VERIFY_TEMPLATE, 
                                 uid=uid, 
                                 captcha_image=captcha['image'])


@app.route('/check-ip-ban', methods=['POST'])
def check_ip_ban():
    ip_address = request.json.get('ip')
    channel_id = session.get('channel_id')
    
    if not ip_address or not channel_id:
        return jsonify({"error": "Missing data"}), 400
    
    cfg = channel_configs.find_one({"channel_id": channel_id})
    if cfg:
        banned_ips = cfg.get("banned_ips", [])
        if ip_address in banned_ips:
            return jsonify({"banned": True}), 200
    
    return jsonify({"banned": False}), 200


@app.route('/callback', methods=['POST'])
def callback():
    uid = session.get('uid')
    user_answer = request.form.get('captcha_answer')
    correct_answer = session.get('captcha_answer')
    ip_address = request.form.get('ip_address')
    
    if not uid or not user_answer or not correct_answer or not ip_address:
        return render_template_string(ERROR_TEMPLATE, error_message="Session expired or missing data. Please try again."), 400
    
    channel_id = session.get('channel_id')
    cfg = channel_configs.find_one({"channel_id": channel_id})
    if cfg:
        banned_ips = cfg.get("banned_ips", [])
        if ip_address in banned_ips:
            return render_template_string(BANNED_TEMPLATE, error_message="Your IP address has been banned from accessing this handle."), 403
    
    if user_answer != correct_answer:
        # Regenerate CAPTCHA for retry
        captcha = generate_captcha()
        session['captcha_answer'] = captcha['answer']
        return render_template_string(VERIFY_TEMPLATE, 
                                     uid=uid, 
                                     captcha_image=captcha['image'],
                                     error="Incorrect answer. Please try again."), 400
    
    entry = invite_requests.find_one({"uid": uid})
    if not entry or entry.get("used"):
        return render_template_string(ERROR_TEMPLATE, error_message="This invitation has already been used."), 400

    try:
        expiration_time = datetime.utcnow() + timedelta(hours=1)
        try:
            link = telegram_bot.create_chat_invite_link(
                entry["channel_id"],
                expire_date=expiration_time,
                member_limit=1
            ).invite_link
        except Exception:
            link = telegram_bot.create_chat_invite_link(
                entry["channel_id"],
                expire_date=int(expiration_time.timestamp()),
                member_limit=1
            ).invite_link

        invite_requests.update_one(
            {"uid": uid},
            {"$set": {"used": True, "invite_link": link}}
        )

        requester = entry["requester"]
        
        try:
            mirza = telegram_bot.get_user(requester)
            telegram_bot.send_message(
                entry["owner_id"],
                f"✅ Request `{uid}` VERIFIED\n"
                f"User: {mirza.mention}\n"
                f"IP: `{ip_address}`\n"
                f"Invite: `{link}`\n"
                f"Time: {datetime.utcnow().isoformat()}",
                parse_mode="markdown"
            )
        except Exception as e:
            print(f"Error sending notification: {e}")

        # Clear session
        session.pop('captcha_answer', None)
        session.pop('uid', None)
        session.pop('channel_id', None)
        
        return redirect(link, code=302)
    except Exception as e:
        return render_template_string(ERROR_TEMPLATE, error_message=f"An error occurred: {str(e)}"), 500

LANDING_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TeleGuard - Advanced Telegram Channel Security</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --telegram-dark: #17212b;
            --telegram-darker: #0f1620;
            --telegram-blue: #2AABEE;
            --telegram-blue-dark: #229ED9;
            --telegram-blue-light: #5ac8ff;
            --telegram-purple: #8774e1;
            --telegram-purple-light: #a48df5;
            --telegram-green: #4fce5d;
            --text-light: #ffffff;
            --text-secondary: #d9d9d9;
            --glass-bg: rgba(23, 33, 43, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
            --glass-bg-darker: rgba(15, 22, 32, 0.8);
            --glass-bg-lighter: rgba(42, 48, 54, 0.6);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
        }
        
        body {
            background-color: var(--telegram-dark);
            color: var(--text-light);
            overflow-x: hidden;
            line-height: 1.6;
        }
        
        .background {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -1;
            background: 
                radial-gradient(circle at 10% 20%, rgba(42, 171, 238, 0.15) 0%, transparent 40%),
                radial-gradient(circle at 90% 30%, rgba(135, 116, 225, 0.15) 0%, transparent 40%),
                radial-gradient(circle at 50% 80%, rgba(79, 206, 93, 0.1) 0%, transparent 40%);
        }
        
        .background::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(45deg, rgba(42, 171, 238, 0.05), rgba(135, 116, 225, 0.05));
        }
        
        .navbar {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            padding: 1.5rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 100;
            background: var(--glass-bg-darker);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border-bottom: 1px solid var(--glass-border);
            transition: all 0.3s ease;
        }
        
        .navbar.scrolled {
            padding: 1rem 2rem;
            box-shadow: 0 5px 20px rgba(0, 0, 0, 0.2);
        }
        
        .logo {
            display: flex;
            align-items: center;
        }
        
        .logo-icon {
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, var(--telegram-blue), var(--telegram-purple));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 1rem;
            box-shadow: 0 0 20px rgba(42, 171, 238, 0.5);
            position: relative;
            overflow: hidden;
        }
        
        .logo-icon::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(
                to right,
                rgba(255, 255, 255, 0),
                rgba(255, 255, 255, 0.3),
                rgba(255, 255, 255, 0)
            );
            transform: rotate(30deg);
            animation: shine 6s infinite;
        }
        
        @keyframes shine {
            0% { transform: translateX(-100%) rotate(30deg); }
            20%, 100% { transform: translateX(100%) rotate(30deg); }
        }
        
        .logo-icon svg {
            width: 26px;
            height: 26px;
            fill: white;
            z-index: 1;
        }
        
        .logo-text {
            font-size: 1.6rem;
            font-weight: 800;
            color: var(--text-light);
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .nav-links {
            display: flex;
            gap: 2.5rem;
        }
        
        .nav-link {
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 1rem;
            font-weight: 500;
            transition: all 0.3s ease;
            position: relative;
        }
        
        .nav-link::after {
            content: '';
            position: absolute;
            bottom: -5px;
            left: 0;
            width: 0;
            height: 2px;
            background: linear-gradient(to right, var(--telegram-blue), var(--telegram-purple));
            transition: width 0.3s ease;
        }
        
        .nav-link:hover {
            color: var(--text-light);
        }
        
        .nav-link:hover::after {
            width: 100%;
        }
        
        .mobile-menu-btn {
            display: none;
            background: none;
            border: none;
            color: var(--text-light);
            font-size: 1.5rem;
            cursor: pointer;
        }
        
        .hero {
            min-height: 100vh;
            display: flex;
            align-items: center;
            padding: 8rem 2rem 6rem;
            position: relative;
            overflow: hidden;
        }
        
        .hero-content {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 4rem;
        }
        
        .hero-text {
            flex: 1;
        }
        
        .hero-badge {
            display: inline-block;
            background: linear-gradient(135deg, rgba(42, 171, 238, 0.1), rgba(135, 116, 225, 0.1));
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: 50px;
            padding: 0.5rem 1.2rem;
            margin-bottom: 1.5rem;
            border: 1px solid var(--glass-border);
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--telegram-blue-light);
            box-shadow: 0 5px 15px rgba(42, 171, 238, 0.1);
        }
        
        .hero-title {
            font-size: 3.8rem;
            font-weight: 800;
            margin-bottom: 1.5rem;
            line-height: 1.2;
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light), var(--telegram-purple-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: titleGradient 8s infinite;
        }
        
        @keyframes titleGradient {
            0%, 100% {
                background-position: 0% 50%;
            }
            50% {
                background-position: 100% 50%;
            }
        }
        
        .hero-subtitle {
            font-size: 1.3rem;
            color: var(--text-secondary);
            margin-bottom: 2.5rem;
            line-height: 1.6;
            max-width: 90%;
        }
        
        .hero-buttons {
            display: flex;
            gap: 1.2rem;
        }
        
        .btn {
            padding: 0.9rem 2.2rem;
            border-radius: 12px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            position: relative;
            overflow: hidden;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, var(--telegram-blue), var(--telegram-purple));
            color: white;
            border: none;
            box-shadow: 0 8px 20px rgba(42, 171, 238, 0.3);
        }
        
        .btn-primary::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(
                to right,
                rgba(255, 255, 255, 0),
                rgba(255, 255, 255, 0.2),
                rgba(255, 255, 255, 0)
            );
            transition: all 0.6s ease;
        }
        
        .btn-primary:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 25px rgba(42, 171, 238, 0.4);
        }
        
        .btn-primary:hover::before {
            left: 100%;
        }
        
        .btn-secondary {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-light);
            border: 1px solid var(--glass-border);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.1);
        }
        
        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.1);
            transform: translateY(-5px);
            box-shadow: 0 12px 25px rgba(0, 0, 0, 0.15);
        }
        
        .btn-icon {
            margin-right: 0.8rem;
            font-size: 1.2rem;
        }
        
        .hero-image {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            position: relative;
        }
        
        .hero-image-container {
            position: relative;
            width: 100%;
            max-width: 500px;
        }
        
        .hero-image-bg {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 100%;
            height: 100%;
            background: radial-gradient(circle, rgba(42, 171, 238, 0.2) 0%, rgba(135, 116, 225, 0.2) 50%, transparent 70%);
            filter: blur(40px);
            z-index: -1;
            animation: pulse 5s infinite alternate;
        }
        
        @keyframes pulse {
            0% {
                transform: translate(-50%, -50%) scale(0.8);
                opacity: 0.5;
            }
            100% {
                transform: translate(-50%, -50%) scale(1.2);
                opacity: 0.8;
            }
        }
        
        .hero-image-content {
            width: 100%;
            aspect-ratio: 1/1;
            background: var(--glass-bg);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border-radius: 24px;
            border: 1px solid var(--glass-border);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2.5rem;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.3);
            position: relative;
            overflow: hidden;
            transform: perspective(1000px) rotateY(-5deg) rotateX(5deg);
            transition: all 0.5s ease;
        }
        
        .hero-image-content:hover {
            transform: perspective(1000px) rotateY(0deg) rotateX(0deg);
        }
        
        .hero-image-content::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: conic-gradient(
                transparent, 
                rgba(42, 171, 238, 0.1), 
                rgba(135, 116, 225, 0.1), 
                transparent, 
                transparent
            );
            animation: rotate 15s linear infinite;
        }
        
        @keyframes rotate {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
        .hero-image-icon {
            width: 100px;
            height: 100px;
            background: linear-gradient(135deg, var(--telegram-blue), var(--telegram-purple));
            border-radius: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 2.5rem;
            box-shadow: 0 0 30px rgba(42, 171, 238, 0.5);
            z-index: 1;
            position: relative;
            overflow: hidden;
        }
        
        .hero-image-icon::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(
                to right,
                rgba(255, 255, 255, 0),
                rgba(255, 255, 255, 0.3),
                rgba(255, 255, 255, 0)
            );
            transform: rotate(30deg);
            animation: iconShine 6s infinite;
        }
        
        @keyframes iconShine {
            0% { transform: translateX(-100%) rotate(30deg); }
            20%, 100% { transform: translateX(100%) rotate(30deg); }
        }
        
        .hero-image-icon svg {
            width: 50px;
            height: 50px;
            fill: white;
            z-index: 1;
        }
        
        .hero-image-text {
            font-size: 1.8rem;
            font-weight: 700;
            margin-bottom: 1rem;
            text-align: center;
            z-index: 1;
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .hero-image-subtext {
            font-size: 1.1rem;
            color: var(--text-secondary);
            text-align: center;
            z-index: 1;
        }
        
        .hero-image-stats {
            display: flex;
            justify-content: space-between;
            width: 100%;
            margin-top: 2.5rem;
            z-index: 1;
        }
        
        .hero-stat {
            text-align: center;
        }
        
        .hero-stat-number {
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--telegram-blue-light);
            margin-bottom: 0.5rem;
        }
        
        .hero-stat-label {
            font-size: 0.9rem;
            color: var(--text-secondary);
        }
        
        .floating-shapes {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: -1;
        }
        
        .shape {
            position: absolute;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--telegram-blue), var(--telegram-purple));
            opacity: 0.1;
            filter: blur(20px);
        }
        
        .shape-1 {
            width: 300px;
            height: 300px;
            top: 10%;
            left: 5%;
            animation: float1 20s infinite alternate;
        }
        
        .shape-2 {
            width: 200px;
            height: 200px;
            top: 60%;
            right: 10%;
            animation: float2 15s infinite alternate;
        }
        
        .shape-3 {
            width: 150px;
            height: 150px;
            bottom: 10%;
            left: 30%;
            animation: float3 18s infinite alternate;
        }
        
        @keyframes float1 {
            0% { transform: translate(0, 0); }
            100% { transform: translate(50px, 50px); }
        }
        
        @keyframes float2 {
            0% { transform: translate(0, 0); }
            100% { transform: translate(-30px, 30px); }
        }
        
        @keyframes float3 {
            0% { transform: translate(0, 0); }
            100% { transform: translate(20px, -40px); }
        }
        
        .features {
            padding: 8rem 2rem;
            background-color: var(--telegram-darker);
            position: relative;
            overflow: hidden;
        }
        
        .features::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                radial-gradient(circle at 80% 20%, rgba(42, 171, 238, 0.05) 0%, transparent 50%),
                radial-gradient(circle at 20% 80%, rgba(135, 116, 225, 0.05) 0%, transparent 50%);
            z-index: 0;
        }
        
        .section-container {
            max-width: 1200px;
            margin: 0 auto;
            position: relative;
            z-index: 1;
        }
        
        .section-header {
            text-align: center;
            margin-bottom: 5rem;
        }
        
        .section-badge {
            display: inline-block;
            background: linear-gradient(135deg, rgba(42, 171, 238, 0.1), rgba(135, 116, 225, 0.1));
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: 50px;
            padding: 0.5rem 1.2rem;
            margin-bottom: 1.5rem;
            border: 1px solid var(--glass-border);
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--telegram-blue-light);
        }
        
        .section-title {
            font-size: 2.8rem;
            font-weight: 800;
            margin-bottom: 1.5rem;
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .section-subtitle {
            font-size: 1.2rem;
            color: var(--text-secondary);
            margin-bottom: 1rem;
            max-width: 700px;
            margin-left: auto;
            margin-right: auto;
        }
        
        .features-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 2.5rem;
        }
        
        .feature-card {
            background: var(--glass-bg);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border-radius: 20px;
            border: 1px solid var(--glass-border);
            padding: 2.5rem;
            transition: all 0.4s ease;
            position: relative;
            overflow: hidden;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
            display: flex;
            flex-direction: column;
        }
        
        .feature-card:hover {
            transform: translateY(-10px);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            border-color: rgba(42, 171, 238, 0.3);
        }
        
        .feature-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 5px;
            background: linear-gradient(to right, var(--telegram-blue), var(--telegram-purple));
            transform: scaleX(0);
            transform-origin: left;
            transition: transform 0.4s ease;
        }
        
        .feature-card:hover::before {
            transform: scaleX(1);
        }
        
        .feature-icon {
            width: 70px;
            height: 70px;
            background: linear-gradient(135deg, rgba(42, 171, 238, 0.1), rgba(135, 116, 225, 0.1));
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 1.8rem;
            position: relative;
            overflow: hidden;
        }
        
        .feature-icon::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(
                to right,
                rgba(255, 255, 255, 0),
                rgba(255, 255, 255, 0.2),
                rgba(255, 255, 255, 0)
            );
            transform: rotate(30deg);
            animation: featureIconShine 6s infinite;
            animation-delay: calc(var(--i) * 0.5s);
        }
        
        @keyframes featureIconShine {
            0% { transform: translateX(-100%) rotate(30deg); }
            20%, 100% { transform: translateX(100%) rotate(30deg); }
        }
        
        .feature-icon svg {
            width: 35px;
            height: 35px;
            fill: var(--telegram-blue);
            z-index: 1;
        }
        
        .feature-title {
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 1.2rem;
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .feature-description {
            font-size: 1.05rem;
            color: var(--text-secondary);
            line-height: 1.7;
            flex-grow: 1;
        }
        
        .feature-more {
            margin-top: 1.5rem;
            display: inline-flex;
            align-items: center;
            color: var(--telegram-blue);
            font-weight: 600;
            font-size: 0.95rem;
            text-decoration: none;
            transition: all 0.3s ease;
        }
        
        .feature-more:hover {
            color: var(--telegram-blue-light);
        }
        
        .feature-more svg {
            width: 18px;
            height: 18px;
            margin-left: 0.5rem;
            transition: transform 0.3s ease;
        }
        
        .feature-more:hover svg {
            transform: translateX(5px);
        }
        
        .how-it-works {
            padding: 8rem 2rem;
            background-color: var(--telegram-dark);
            position: relative;
            overflow: hidden;
        }
        
        .how-it-works::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                radial-gradient(circle at 20% 30%, rgba(42, 171, 238, 0.05) 0%, transparent 50%),
                radial-gradient(circle at 80% 70%, rgba(135, 116, 225, 0.05) 0%, transparent 50%);
            z-index: 0;
        }
        
        .steps {
            max-width: 900px;
            margin: 0 auto;
            position: relative;
        }
        
        .steps::before {
            content: '';
            position: absolute;
            top: 0;
            left: 40px;
            width: 2px;
            height: 100%;
            background: linear-gradient(to bottom, var(--telegram-blue), var(--telegram-purple));
            z-index: 0;
        }
        
        .step {
            display: flex;
            gap: 2.5rem;
            margin-bottom: 5rem;
            position: relative;
            z-index: 1;
        }
        
        .step:last-child {
            margin-bottom: 0;
        }
        
        .step-number {
            flex-shrink: 0;
            width: 80px;
            height: 80px;
            background: linear-gradient(135deg, var(--telegram-blue), var(--telegram-purple));
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.8rem;
            font-weight: 700;
            box-shadow: 0 0 25px rgba(42, 171, 238, 0.4);
            position: relative;
            z-index: 2;
        }
        
        .step-content {
            flex: 1;
            background: var(--glass-bg);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border-radius: 20px;
            border: 1px solid var(--glass-border);
            padding: 2.5rem;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
        }
        
        .step-content:hover {
            transform: translateY(-5px);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            border-color: rgba(42, 171, 238, 0.3);
        }
        
        .step-title {
            font-size: 1.6rem;
            font-weight: 700;
            margin-bottom: 1.2rem;
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .step-description {
            font-size: 1.05rem;
            color: var(--text-secondary);
            line-height: 1.7;
        }
        
        .security {
            padding: 8rem 2rem;
            background-color: var(--telegram-darker);
            position: relative;
            overflow: hidden;
        }
        
        .security::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                radial-gradient(circle at 70% 20%, rgba(42, 171, 238, 0.05) 0%, transparent 50%),
                radial-gradient(circle at 30% 70%, rgba(135, 116, 225, 0.05) 0%, transparent 50%);
            z-index: 0;
        }
        
        .security-content {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            gap: 5rem;
            position: relative;
            z-index: 1;
        }
        
        .security-image {
            flex: 1;
            display: flex;
            justify-content: center;
        }
        
        .security-image-container {
            width: 100%;
            max-width: 450px;
            aspect-ratio: 1/1;
            background: var(--glass-bg);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border-radius: 24px;
            border: 1px solid var(--glass-border);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.3);
            position: relative;
            overflow: hidden;
            transform: perspective(1000px) rotateY(5deg) rotateX(5deg);
            transition: all 0.5s ease;
        }
        
        .security-image-container:hover {
            transform: perspective(1000px) rotateY(0deg) rotateX(0deg);
        }
        
        .security-image-container::before {
            content: '';
            position: absolute;
            width: 150%;
            height: 150%;
            background: conic-gradient(
                transparent, 
                rgba(42, 171, 238, 0.1), 
                rgba(135, 116, 225, 0.1), 
                transparent, 
                transparent
            );
            animation: rotate 15s linear infinite;
        }
        
        .security-icon {
            width: 150px;
            height: 150px;
            z-index: 1;
            filter: drop-shadow(0 0 20px rgba(42, 171, 238, 0.5));
        }
        
        .security-text {
            flex: 1;
        }
        
        .security-title {
            font-size: 2.8rem;
            font-weight: 800;
            margin-bottom: 1.5rem;
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .security-description {
            font-size: 1.2rem;
            color: var(--text-secondary);
            margin-bottom: 2.5rem;
            line-height: 1.7;
        }
        
        .security-features {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
        }
        
        .security-feature {
            display: flex;
            align-items: flex-start;
            gap: 1.2rem;
            transition: all 0.3s ease;
        }
        
        .security-feature:hover {
            transform: translateX(5px);
        }
        
        .security-feature-icon {
            width: 28px;
            height: 28px;
            fill: var(--telegram-blue);
            flex-shrink: 0;
            margin-top: 0.2rem;
            transition: all 0.3s ease;
        }
        
        .security-feature:hover .security-feature-icon {
            fill: var(--telegram-blue-light);
            transform: scale(1.1);
        }
        
        .security-feature-text {
            font-size: 1.05rem;
            color: var(--text-secondary);
            line-height: 1.6;
        }
        
        .cta {
            padding: 8rem 2rem;
            background-color: var(--telegram-dark);
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        
        .cta::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                radial-gradient(circle at 50% 50%, rgba(42, 171, 238, 0.1) 0%, transparent 70%);
            z-index: 0;
        }
        
        .cta-container {
            max-width: 900px;
            margin: 0 auto;
            background: var(--glass-bg);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border-radius: 24px;
            border: 1px solid var(--glass-border);
            padding: 5rem 3rem;
            position: relative;
            overflow: hidden;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.3);
            z-index: 1;
        }
        
        .cta-container::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: conic-gradient(
                transparent, 
                rgba(42, 171, 238, 0.05), 
                rgba(135, 116, 225, 0.05), 
                transparent, 
                transparent
            );
            animation: rotate 20s linear infinite;
        }
        
        .cta-title {
            font-size: 3rem;
            font-weight: 800;
            margin-bottom: 1.5rem;
            position: relative;
            z-index: 1;
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light), var(--telegram-purple-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .cta-description {
            font-size: 1.2rem;
            color: var(--text-secondary);
            margin-bottom: 3rem;
            position: relative;
            z-index: 1;
            max-width: 700px;
            margin-left: auto;
            margin-right: auto;
        }
        
        .cta-buttons {
            display: flex;
            justify-content: center;
            gap: 1.5rem;
            position: relative;
            z-index: 1;
        }
        
        .footer {
            background-color: var(--telegram-darker);
            padding: 5rem 2rem 2rem;
            position: relative;
            overflow: hidden;
        }
        
        .footer::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                radial-gradient(circle at 20% 20%, rgba(42, 171, 238, 0.05) 0%, transparent 50%),
                radial-gradient(circle at 80% 80%, rgba(135, 116, 225, 0.05) 0%, transparent 50%);
            z-index: 0;
        }
        
        .footer-content {
            max-width: 1200px;
            margin: 0 auto;
            position: relative;
            z-index: 1;
        }
        
        .footer-top {
            display: flex;
            justify-content: space-between;
            margin-bottom: 4rem;
            flex-wrap: wrap;
            gap: 3rem;
        }
        
        .footer-logo {
            display: flex;
            align-items: center;
        }
        
        .footer-logo-icon {
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, var(--telegram-blue), var(--telegram-purple));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 1rem;
        }
        
        .footer-logo-icon svg {
            width: 26px;
            height: 26px;
            fill: white;
        }
        
        .footer-logo-text {
            font-size: 1.6rem;
            font-weight: 800;
            background: linear-gradient(to right, var(--text-light), var(--telegram-blue-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .footer-links {
            display: flex;
            gap: 5rem;
            flex-wrap: wrap;
        }
        
        .footer-links-column {
            min-width: 180px;
        }
        
        .footer-links-title {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 1.8rem;
            color: var(--text-light);
        }
        
        .footer-link {
            display: block;
            color: var(--text-secondary);
            text-decoration: none;
            margin-bottom: 1rem;
            transition: all 0.3s ease;
            font-size: 1.05rem;
        }
        
        .footer-link:hover {
            color: var(--telegram-blue-light);
            transform: translateX(5px);
        }
        
        .footer-bottom {
            padding-top: 2.5rem;
            border-top: 1px solid var(--glass-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1.5rem;
        }
        
        .footer-copyright {
            color: var(--text-secondary);
            font-size: 1rem;
        }
        
        .footer-social {
            display: flex;
            gap: 1.2rem;
        }
        
        .footer-social-link {
            width: 44px;
            height: 44px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s ease;
            border: 1px solid var(--glass-border);
        }
        
        .footer-social-link:hover {
            background: linear-gradient(135deg, var(--telegram-blue), var(--telegram-purple));
            transform: translateY(-5px);
            box-shadow: 0 10px 20px rgba(42, 171, 238, 0.3);
        }
        
        .footer-social-link svg {
            width: 22px;
            height: 22px;
            fill: white;
        }
        
        @media (max-width: 1200px) {
            .hero-title {
                font-size: 3.2rem;
            }
            
            .security-content {
                flex-direction: column;
            }
            
            .security-image {
                order: -1;
            }
            
            .features-grid {
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            }
        }
        
        @media (max-width: 992px) {
            .hero-content {
                flex-direction: column;
            }
            
            .hero-title {
                font-size: 2.8rem;
            }
            
            .hero-subtitle {
                font-size: 1.1rem;
                max-width: 100%;
            }
            
            .hero-image {
                margin-top: 3rem;
            }
            
            .section-title {
                font-size: 2.4rem;
            }
            
            .security-features {
                grid-template-columns: 1fr;
            }
            
            .cta-title {
                font-size: 2.5rem;
            }
            
            .cta-container {
                padding: 4rem 2rem;
            }
        }
        
        @media (max-width: 768px) {
            .nav-links {
                display: none;
            }
            
            .mobile-menu-btn {
                display: block;
            }
            
            .hero-title {
                font-size: 2.4rem;
            }
            
            .hero-buttons {
                flex-direction: column;
                width: 100%;
            }
            
            .btn {
                width: 100%;
            }
            
            .step {
                flex-direction: column;
                gap: 1.5rem;
                align-items: flex-start;
            }
            
            .steps::before {
                display: none;
            }
            
            .footer-top {
                flex-direction: column;
                gap: 3rem;
            }
            
            .footer-links {
                width: 100%;
                justify-content: space-between;
                gap: 2rem;
            }
            
            .footer-links-column {
                min-width: 140px;
            }
        }
        
        @media (max-width: 576px) {
            .hero-title {
                font-size: 2rem;
            }
            
            .hero-image-stats {
                flex-direction: column;
                gap: 1.5rem;
            }
            
            .features-grid {
                grid-template-columns: 1fr;
            }
            
            .section-title {
                font-size: 2rem;
            }
            
            .cta-title {
                font-size: 2rem;
            }
            
            .cta-buttons {
                flex-direction: column;
                width: 100%;
            }
            
            .cta-buttons .btn {
                width: 100%;
            }
            
            .footer-bottom {
                flex-direction: column;
                text-align: center;
            }
            
            .footer-links {
                flex-direction: column;
                gap: 2.5rem;
            }
        }
        
        .mobile-menu {
            position: fixed;
            top: 0;
            right: -100%;
            width: 80%;
            max-width: 400px;
            height: 100vh;
            background: var(--glass-bg-darker);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            z-index: 1000;
            padding: 2rem;
            transition: right 0.3s ease;
            display: flex;
            flex-direction: column;
            box-shadow: -5px 0 30px rgba(0, 0, 0, 0.3);
        }
        
        .mobile-menu.active {
            right: 0;
        }
        
        .mobile-menu-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--glass-border);
        }
        
        .mobile-menu-close {
            background: none;
            border: none;
            color: var(--text-light);
            font-size: 1.5rem;
            cursor: pointer;
        }
        
        .mobile-menu-links {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }
        
        .mobile-menu-link {
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 1.2rem;
            font-weight: 500;
            transition: all 0.3s ease;
            padding: 0.5rem 0;
        }
        
        .mobile-menu-link:hover {
            color: var(--telegram-blue-light);
            transform: translateX(5px);
        }
        
        .mobile-menu-footer {
            margin-top: auto;
            padding-top: 2rem;
            border-top: 1px solid var(--glass-border);
        }
        
        .mobile-menu-social {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
        }
        
        .mobile-menu-social-link {
            width: 40px;
            height: 40px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s ease;
        }
        
        .mobile-menu-social-link:hover {
            background: linear-gradient(135deg, var(--telegram-blue), var(--telegram-purple));
        }
        
        .mobile-menu-social-link svg {
            width: 20px;
            height: 20px;
            fill: white;
        }
        
        .overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(5px);
            -webkit-backdrop-filter: blur(5px);
            z-index: 999;
            opacity: 0;
            visibility: hidden;
            transition: all 0.3s ease;
        }
        
        .overlay.active {
            opacity: 1;
            visibility: visible;
        }
    </style>
</head>
<body>
    <div class="background"></div>
    <div class="floating-shapes">
        <div class="shape shape-1"></div>
        <div class="shape shape-2"></div>
        <div class="shape shape-3"></div>
    </div>
    
    <nav class="navbar" id="navbar">
        <div class="logo">
            <div class="logo-icon">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
                </svg>
            </div>
            <div class="logo-text">TeleGuard</div>
        </div>
        
        <div class="nav-links">
            <a href="#features" class="nav-link">Features</a>
            <a href="#how-it-works" class="nav-link">How It Works</a>
            <a href="#security" class="nav-link">Security</a>
            <a href="#contact" class="nav-link">Contact</a>
        </div>
        
        <button class="mobile-menu-btn" id="mobile-menu-btn">☰</button>
    </nav>
    
    <div class="mobile-menu" id="mobile-menu">
        <div class="mobile-menu-header">
            <div class="logo">
                <div class="logo-icon">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
                    </svg>
                </div>
                <div class="logo-text">TeleGuard</div>
            </div>
            <button class="mobile-menu-close" id="mobile-menu-close">✕</button>
        </div>
        
        <div class="mobile-menu-links">
            <a href="#features" class="mobile-menu-link">Features</a>
            <a href="#how-it-works" class="mobile-menu-link">How It Works</a>
            <a href="#security" class="mobile-menu-link">Security</a>
            <a href="#contact" class="mobile-menu-link">Contact</a>
        </div>
        
        <div class="mobile-menu-footer">
            <p style="color: var(--text-secondary);">Connect with us</p>
            <div class="mobile-menu-social">
                <a href="https://t.me/elitemirza" class="footer-social-link">
                    <svg viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg">
                        <path d="M120 0C53.73 0 0 53.73 0 120c0 66.27 53.73 120 120 120s120-53.73 120-120C240 53.73 186.27 0 120 0zm58.65 78.14l-19.26 90.91c-1.45 6.56-5.32 8.19-10.79 5.11l-29.83-22.01-14.38 13.86c-1.59 1.59-2.93 2.93-6 2.93l2.15-30.37 55.27-49.88c2.4-2.15-.52-3.34-3.72-1.19l-68.34 42.98-29.44-9.21c-6.41-2-6.56-6.41 1.34-9.48l114.87-44.28c5.34-2 10 1.34 8.3 9.34z"/>
                    </svg>
                </a>
            </div>
        </div>
    </div>
    
    <div class="overlay" id="overlay"></div>
    
    <section class="hero">
        <div class="hero-content">
            <div class="hero-text">
                <div class="hero-badge">Advanced Security Solution</div>
                <h1 class="hero-title">Security for Telegram Channels</h1>
                <p class="hero-subtitle">Protect your Telegram channels with advanced security automation. TeleGuard provides CAPTCHA verification, IP and Telegram ID banning, and stealth operations to keep your communities secure from unauthorized access.</p>
                <div class="hero-buttons">
                    <a href="https://t.me/teleguard_bot" class="btn btn-primary">
                        <span class="btn-icon">🚀</span>
                        Add to Telegram
                    </a>
                    <a href="#features" class="btn btn-secondary">
                        <span class="btn-icon">🔍</span>
                        Explore Features
                    </a>
                </div>
            </div>
            
            <div class="hero-image">
                <div class="hero-image-container">
                    <div class="hero-image-bg"></div>
                    <div class="hero-image-content">
                        <div class="hero-image-icon">
                            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
                            </svg>
                        </div>
                        <h3 class="hero-image-text">TeleGuard Security</h3>
                        <p class="hero-image-subtext">Covert. Reliable. Secure.</p>
                        
                        <div class="hero-image-stats">
                            <div class="hero-stat">
                                <div class="hero-stat-number">100%</div>
                                <div class="hero-stat-label">Protection</div>
                            </div>
                            <div class="hero-stat">
                                <div class="hero-stat-number">24/7</div>
                                <div class="hero-stat-label">Monitoring</div>
                            </div>
                            <div class="hero-stat">
                                <div class="hero-stat-number">0%</div>
                                <div class="hero-stat-label">Intrusion</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
    
    <section class="features" id="features">
        <div class="section-container">
            <div class="section-header">
                <div class="section-badge">Powerful Features</div>
                <h2 class="section-title">Comprehensive Security Suite</h2>
                <p class="section-subtitle">TeleGuard offers a complete set of security tools designed to protect your Telegram channels from unauthorized access and manipulation.</p>
            </div>
            
            <div class="features-grid">
                <div class="feature-card" style="--i: 0">
                    <div class="feature-icon">
                        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-1 6h2v2h-2V7zm0 4h2v6h-2v-6z"/>
                        </svg>
                    </div>
                    <h3 class="feature-title">CAPTCHA Verification</h3>
                    <p class="feature-description">Protect your channels with custom CAPTCHA challenges that prevent bots and automated scripts from gaining access. Our system uses dynamic math problems with visual noise to ensure only humans can pass.</p>
                    <a href="#" class="feature-more">
                        Learn more
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </a>
                </div>
                
                <div class="feature-card" style="--i: 1">
                    <div class="feature-icon">
                        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8 0-1.85.63-3.55 1.69-4.9L16.9 18.31C15.55 19.37 13.85 20 12 20zm6.31-3.1L7.1 5.69C8.45 4.63 10.15 4 12 4c4.42 0 8 3.58 8 8 0 1.85-.63 3.55-1.69 4.9z"/>
                        </svg>
                    </div>
                    <h3 class="feature-title">IP Banning System</h3>
                    <p class="feature-description">Maintain a dynamic IP banlist to automatically block unwanted users from accessing your channels, even if they create new accounts. Our system validates IP addresses and ensures proper formatting.</p>
                    <a href="#" class="feature-more">
                        Learn more
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </a>
                </div>
                
                <div class="feature-card" style="--i: 2">
                    <div class="feature-icon">
                        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 5.9c1.16 0 2.1.94 2.1 2.1s-.94 2.1-2.1 2.1S9.9 9.16 9.9 8s.94-2.1 2.1-2.1m0 9c2.97 0 6.1 1.46 6.1 2.1v1.1H5.9V17c0-.64 3.13-2.1 6.1-2.1M12 4C9.79 4 8 5.79 8 8s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm0 9c-2.67 0-8 1.34-8 4v3h16v-3c0-2.66-5.33-4-8-4z"/>
                        </svg>
                    </div>
                    <h3 class="feature-title">User ID Banning</h3>
                    <p class="feature-description">Block specific Telegram user IDs from joining your channels, providing an additional layer of security against persistent threats. The system validates all user IDs to ensure proper formatting.</p>
                    <a href="#" class="feature-more">
                        Learn more
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </a>
                </div>
                
                <div class="feature-card" style="--i: 3">
                    <div class="feature-icon">
                        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
                        </svg>
                    </div>
                    <h3 class="feature-title">Stealth Operations</h3>
                    <p class="feature-description">Operate covertly with no public announcements of bans or security actions, keeping banned users unaware of enforcement mechanisms. This prevents circumvention attempts and maintains security integrity.</p>
                    <a href="#" class="feature-more">
                        Learn more
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </a>
                </div>
                
                <div class="feature-card" style="--i: 4">
                    <div class="feature-icon">
                        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM19 18H6c-2.21 0-4-1.79-4-4 0-2.05 1.53-3.76 3.56-3.97l1.07-.11.5-.95C8.08 7.14 9.94 6 12 6c2.62 0 4.88 1.86 5.39 4.43l.3 1.5 1.53.11c1.56.1 2.78 1.41 2.78 2.96 0 1.65-1.35 3-3 3zm-9-3.82l-2.09-2.09L6.5 13.5 10 17l6.01-6.01-1.41-1.41z"/>
                        </svg>
                    </div>
                    <h3 class="feature-title">Dynamic Management</h3>
                    <p class="feature-description">Easily manage banlists by adding or appending entries manually, with automatic validation to ensure data integrity. The system rejects malformed inputs and shields channel operations from infiltration attempts.</p>
                    <a href="#" class="feature-more">
                        Learn more
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </a>
                </div>
                
                <div class="feature-card" style="--i: 5">
                    <div class="feature-icon">
                        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/>
                        </svg>
                    </div>
                    <h3 class="feature-title">Real-time Protection</h3>
                    <p class="feature-description">Get instant protection with real-time enforcement of security rules, ensuring immediate action against threats. The system operates with precision and speed to maintain the integrity of your channels.</p>
                    <a href="#" class="feature-more">
                        Learn more
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </a>
                </div>
            </div>
        </div>
    </section>
    
    <section class="how-it-works" id="how-it-works">
        <div class="section-container">
            <div class="section-header">
                <div class="section-badge">Simple Process</div>
                <h2 class="section-title">How TeleGuard Works</h2>
                <p class="section-subtitle">TeleGuard provides a seamless security experience for your Telegram channels with a simple setup process and powerful protection mechanisms.</p>
            </div>
            
            <div class="steps">
                <div class="step">
                    <div class="step-number">1</div>
                    <div class="step-content">
                        <h3 class="step-title">Add TeleGuard to Your Channel</h3>
                        <p class="step-description">Invite the TeleGuard bot to your Telegram channel and grant it administrator privileges to enable security features. The bot will automatically integrate with your channel's settings and prepare for security enforcement.</p>
                    </div>
                </div>
                
                <div class="step">
                    <div class="step-number">2</div>
                    <div class="step-content">
                        <h3 class="step-title">Configure Security Settings</h3>
                        <p class="step-description">Set up your security preferences, including CAPTCHA requirements, IP ban rules, and user ID restrictions through simple commands. TeleGuard offers flexible configuration options to meet your specific security needs.</p>
                    </div>
                </div>
                
                <div class="step">
                    <div class="step-number">3</div>
                    <div class="step-content">
                        <h3 class="step-title">Automatic Protection</h3>
                        <p class="step-description">TeleGuard automatically enforces your security policies, verifying new members and blocking banned IPs and users without manual intervention. The system operates silently in the background, maintaining a seamless user experience.</p>
                    </div>
                </div>
                
                <div class="step">
                    <div class="step-number">4</div>
                    <div class="step-content">
                        <h3 class="step-title">Manage and Monitor</h3>
                        <p class="step-description">Easily update your security settings and monitor protection activities through the bot's admin interface, with detailed logs and notifications. TeleGuard provides comprehensive insights into security events and enforcement actions.</p>
                    </div>
                </div>
            </div>
        </div>
    </section>
    
    <section class="security" id="security">
        <div class="section-container">
            <div class="security-content">
                <div class="security-text">
                    <div class="section-badge">Advanced Protection</div>
                    <h2 class="security-title">Military-Grade Security</h2>
                    <p class="security-description">TeleGuard employs advanced security techniques to ensure your Telegram channels remain protected from unauthorized access and malicious actors. Our system is designed for serious security needs, ensuring that communities and sensitive operations remain protected.</p>
                    
                    <div class="security-features">
                        <div class="security-feature">
                            <svg class="security-feature-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
                            </svg>
                            <p class="security-feature-text">Advanced CAPTCHA verification system that prevents automated bots from accessing your channels, with dynamic challenges that adapt to different threat levels.</p>
                        </div>
                        
                        <div class="security-feature">
                            <svg class="security-feature-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zM9 6c0-1.66 1.34-3 3-3s3 1.34 3 3v2H9V6zm9 14H6V10h12v10zm-6-3c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2z"/>
                            </svg>
                            <p class="security-feature-text">IP-based and User ID-based banlists to prevent banned users from rejoining your channels, with automatic validation to ensure data integrity.</p>
                        </div>
                        
                        <div class="security-feature">
                            <svg class="security-feature-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/>
                            </svg>
                            <p class="security-feature-text">Stealth operations that keep security measures hidden from users, preventing circumvention attempts and maintaining operational security.</p>
                        </div>
                        
                        <div class="security-feature">
                            <svg class="security-feature-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM19 18H6c-2.21 0-4-1.79-4-4 0-2.05 1.53-3.76 3.56-3.97l1.07-.11.5-.95C8.08 7.14 9.94 6 12 6c2.62 0 4.88 1.86 5.39 4.43l.3 1.5 1.53.11c1.56.1 2.78 1.41 2.78 2.96 0 1.65-1.35 3-3 3z"/>
                            </svg>
                            <p class="security-feature-text">Real-time protection that instantly enforces security rules as users attempt to join, with immediate action against potential threats.</p>
                        </div>
                    </div>
                </div>
                
                <div class="security-image">
                    <div class="security-image-container">
                        <svg class="security-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path fill="#2AABEE" d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-1 6h2v2h-2V7zm0 4h2v6h-2v-6z"/>
                        </svg>
                    </div>
                </div>
            </div>
        </div>
    </section>
    
    <section class="cta" id="contact">
        <div class="section-container">
            <div class="cta-container">
                <h2 class="cta-title">Ready to Secure Your Channels?</h2>
                <p class="cta-description">Start protecting your Telegram channels today with TeleGuard's advanced security features. Our system is designed to provide comprehensive protection against unauthorized access and manipulation.</p>
                <div class="cta-buttons">
                    <a href="https://t.me/teleguard_bot" class="btn btn-primary">
                        <span class="btn-icon">🚀</span>
                        Add to Telegram
                    </a>
                    <a href="https://t.me/teleguard_support" class="btn btn-secondary">
                        <span class="btn-icon">💬</span>
                        Contact Support
                    </a>
                </div>
            </div>
        </div>
    </section>
    
    <footer class="footer">
        <div class="footer-content">
            <div class="footer-top">
                <div class="footer-logo">
                    <div class="footer-logo-icon">
                        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
                        </svg>
                    </div>
                    <div class="footer-logo-text">TeleGuard</div>
                </div>
                
                <div class="footer-links">
                    <div class="footer-links-column">
                        <h4 class="footer-links-title">TeleGuard</h4>
                        <a href="#features" class="footer-link">Features</a>
                        <a href="#how-it-works" class="footer-link">How It Works</a>
                        <a href="#security" class="footer-link">Security</a>
                    </div>
                    
                    <div class="footer-links-column">
                        <h4 class="footer-links-title">Support</h4>
                        <a href="https://t.me/elitemirza" class="footer-link">Contact Us</a>
                    </div>
                    
                </div>
            </div>
            
            <div class="footer-bottom">
                <div class="footer-copyright">© 2025 TeleGuard. All rights reserved.</div>
            </div>
        </div>
    </footer>
    
    <script>
        // Mobile menu toggle
        const mobileMenuBtn = document.getElementById('mobile-menu-btn');
        const mobileMenu = document.getElementById('mobile-menu');
        const mobileMenuClose = document.getElementById('mobile-menu-close');
        const overlay = document.getElementById('overlay');
        
        mobileMenuBtn.addEventListener('click', function() {
            mobileMenu.classList.add('active');
            overlay.classList.add('active');
            document.body.style.overflow = 'hidden';
        });
        
        mobileMenuClose.addEventListener('click', function() {
            mobileMenu.classList.remove('active');
            overlay.classList.remove('active');
            document.body.style.overflow = '';
        });
        
        overlay.addEventListener('click', function() {
            mobileMenu.classList.remove('active');
            overlay.classList.remove('active');
            document.body.style.overflow = '';
        });
        
        // Smooth scrolling for anchor links
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function(e) {
                e.preventDefault();
                
                const targetId = this.getAttribute('href');
                if (targetId === '#') return;
                
                const targetElement = document.querySelector(targetId);
                if (targetElement) {
                    window.scrollTo({
                        top: targetElement.offsetTop - 80,
                        behavior: 'smooth'
                    });
                    
                    // Close mobile menu if open
                    mobileMenu.classList.remove('active');
                    overlay.classList.remove('active');
                    document.body.style.overflow = '';
                }
            });
        });
        
        // Navbar scroll effect
        window.addEventListener('scroll', function() {
            const navbar = document.getElementById('navbar');
            if (window.scrollY > 50) {
                navbar.classList.add('scrolled');
            } else {
                navbar.classList.remove('scrolled');
            }
        });
        
        // Animation on scroll
        const animateOnScroll = function() {
            const elements = document.querySelectorAll('.feature-card, .step, .security-feature');
            
            elements.forEach(element => {
                const elementPosition = element.getBoundingClientRect().top;
                const windowHeight = window.innerHeight;
                
                if (elementPosition < windowHeight - 100) {
                    element.style.opacity = '1';
                    element.style.transform = 'translateY(0)';
                }
            });
        };
        
        // Set initial styles for animation
        document.querySelectorAll('.feature-card, .step, .security-feature').forEach(element => {
            element.style.opacity = '0';
            element.style.transform = 'translateY(20px)';
            element.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
        });
        
        // Run animation on scroll
        window.addEventListener('scroll', animateOnScroll);
        
        // Run animation on load
        window.addEventListener('load', animateOnScroll);
    </script>
</body>
</html>"""

VERIFY_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Security Verification</title>
    <style>
        :root {
            --telegram-dark: #1e2429;
            --telegram-blue: #2AABEE;
            --telegram-blue-dark: #229ED9;
            --text-light: #ffffff;
            --text-secondary: #d9d9d9;
            --glass-bg: rgba(30, 36, 41, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
            --error-color: #ff5252;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
        }
        
        body {
            background-color: var(--telegram-dark);
            color: var(--text-light);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(42, 171, 238, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(42, 171, 238, 0.05) 0%, transparent 40%);
            position: relative;
            overflow: hidden;
        }
        
        body::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(45deg, rgba(42, 171, 238, 0.03), transparent);
            z-index: -1;
        }
        
        .container {
            width: 100%;
            max-width: 450px;
            padding: 2rem;
        }
        
        .card {
            background: var(--glass-bg);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: 16px;
            border: 1px solid var(--glass-border);
            padding: 2rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
        }
        
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
        }
        
        .header {
            display: flex;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--glass-border);
        }
        
        .logo {
            width: 40px;
            height: 40px;
            background-color: var(--telegram-blue);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 1rem;
            box-shadow: 0 0 15px rgba(42, 171, 238, 0.5);
        }
        
        .logo svg {
            width: 24px;
            height: 24px;
            fill: white;
        }
        
        .title h1 {
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 0.2rem;
        }
        
        .title p {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }
        
        .content {
            margin-bottom: 1.5rem;
        }
        
        .content p {
            font-size: 0.95rem;
            line-height: 1.5;
            margin-bottom: 1rem;
        }
        
        .captcha-container {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        
        .captcha-image {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
            display: flex;
            justify-content: center;
            align-items: center;
            width: 100%;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }
        
        .captcha-image img {
            max-width: 100%;
            height: auto;
        }
        
        .captcha-input {
            width: 100%;
            margin-top: 1rem;
        }
        
        .captcha-input input {
            width: 100%;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid var(--glass-border);
            border-radius: 6px;
            padding: 0.8rem;
            color: var(--text-light);
            font-size: 1rem;
            text-align: center;
            outline: none;
            transition: all 0.2s ease;
        }
        
        .captcha-input input:focus {
            border-color: var(--telegram-blue);
            box-shadow: 0 0 0 2px rgba(42, 171, 238, 0.2);
        }
        
        .error-message {
            color: var(--error-color);
            font-size: 0.85rem;
            margin-top: 0.5rem;
            text-align: center;
        }
        
        button {
            width: 100%;
            background-color: var(--telegram-blue);
            color: white;
            border: none;
            padding: 0.8rem;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 500;
            cursor: pointer;
            transition: background-color 0.2s ease;
            box-shadow: 0 4px 12px rgba(42, 171, 238, 0.3);
        }
        
        button:hover {
            background-color: var(--telegram-blue-dark);
        }
        
        .footer {
            text-align: center;
            margin-top: 1.5rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        
        .security-badge {
            display: flex;
            align-items: center;
            justify-content: center;
            margin-top: 1rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        
        .security-badge svg {
            width: 16px;
            height: 16px;
            margin-right: 0.5rem;
            fill: var(--text-secondary);
        }
        
        .refresh-captcha {
            background: none;
            border: none;
            color: var(--telegram-blue);
            font-size: 0.85rem;
            cursor: pointer;
            margin-top: 0.5rem;
            text-decoration: underline;
            box-shadow: none;
            width: auto;
            padding: 0;
        }
        
        .refresh-captcha:hover {
            color: var(--telegram-blue-dark);
            background: none;
        }
        
        .loading-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            backdrop-filter: blur(5px);
            -webkit-backdrop-filter: blur(5px);
            visibility: hidden;
            opacity: 0;
            transition: all 0.3s ease;
        }
        
        .loading-overlay.active {
            visibility: visible;
            opacity: 1;
        }
        
        .spinner {
            width: 50px;
            height: 50px;
            border: 5px solid rgba(255, 255, 255, 0.1);
            border-radius: 50%;
            border-top-color: var(--telegram-blue);
            animation: spin 1s ease-in-out infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        @media (max-width: 480px) {
            .container {
                padding: 1rem;
            }
            
            .card {
                padding: 1.5rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <div class="logo">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1.1 14.9l-4.2-4.2 1.4-1.4 2.8 2.8 6.8-6.8 1.4 1.4-8.2 8.2z"/>
                    </svg>
                </div>
                <div class="title">
                    <h1>Security Verification</h1>
                    <p>Telegram Handle Access</p>
                </div>
            </div>
            
            <div class="content">
                <p>Please solve the math problem below to verify you're human and access the Telegram channel.</p>
                
                <form action="/callback" method="post" id="verification-form">
                    <input type="hidden" name="uid" value="{{uid}}">
                    <input type="hidden" name="ip_address" id="ip-address">
                    
                    <div class="captcha-container">
                        <div class="captcha-image">
                            <img src="data:image/png;base64,{{captcha_image}}" alt="CAPTCHA Challenge">
                        </div>
                        
                        <div class="captcha-input">
                            <input type="text" name="captcha_answer" id="captcha-answer" placeholder="Enter the answer" required autocomplete="off">
                            {% if error %}
                            <div class="error-message">{{error}}</div>
                            {% endif %}
                        </div>
                    </div>
                    
                    <button type="submit" id="submit-btn">Verify and Continue</button>
                </form>
                
                <div style="text-align: center; margin-top: 1rem;">
                    <a href="/verify?uid={{uid}}" class="refresh-captcha">Can't read? Get a new challenge</a>
                </div>
            </div>
            
            <div class="security-badge">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
                </svg>
                <span>Secure verification powered by TeleGuard</span>
            </div>
        </div>
        
        <div class="footer">
            © 2025 Telegram. All rights reserved.
        </div>
    </div>
    
    <div class="loading-overlay" id="loading-overlay">
        <div class="spinner"></div>
    </div>
    
    <script>
        // Get user's IP address from ipify API
        async function getIPAddress() {
            try {
                const response = await fetch('https://api.ipify.org/?format=json');
                const data = await response.json();
                return data.ip;
            } catch (error) {
                console.error('Error fetching IP:', error);
                return null;
            }
        }
        
        // Check if IP is banned
        async function checkIPBan(ip) {
            try {
                const response = await fetch('/check-ip-ban', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ ip: ip })
                });
                
                const data = await response.json();
                return data.banned;
            } catch (error) {
                console.error('Error checking IP ban:', error);
                return false;
            }
        }
        
        // Initialize the page
        async function initPage() {
            const ipAddress = await getIPAddress();
            if (ipAddress) {
                document.getElementById('ip-address').value = ipAddress;
                
                // Check if IP is banned
                const isBanned = await checkIPBan(ipAddress);
                if (isBanned) {
                    window.location.href = '/banned';
                }
            }
        }
        
        // Show loading overlay when form is submitted
        document.getElementById('verification-form').addEventListener('submit', function() {
            document.getElementById('loading-overlay').classList.add('active');
        });
        
        // Initialize the page when DOM is loaded
        document.addEventListener('DOMContentLoaded', initPage);
    </script>
</body>
</html>
"""

# Error template
ERROR_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verification Error</title>
    <style>
        :root {
            --telegram-dark: #1e2429;
            --telegram-blue: #2AABEE;
            --telegram-red: #E53935;
            --text-light: #ffffff;
            --text-secondary: #d9d9d9;
            --glass-bg: rgba(30, 36, 41, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
        }
        
        body {
            background-color: var(--telegram-dark);
            color: var(--text-light);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(229, 57, 53, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(229, 57, 53, 0.05) 0%, transparent 40%);
            position: relative;
            overflow: hidden;
        }
        
        body::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(45deg, rgba(229, 57, 53, 0.03), transparent);
            z-index: -1;
        }
        
        .container {
            width: 100%;
            max-width: 450px;
            padding: 2rem;
        }
        
        .card {
            background: var(--glass-bg);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: 16px;
            border: 1px solid var(--glass-border);
            padding: 2rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        }
        
        .header {
            display: flex;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--glass-border);
        }
        
        .logo {
            width: 40px;
            height: 40px;
            background-color: var(--telegram-red);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 1rem;
            box-shadow: 0 0 15px rgba(229, 57, 53, 0.5);
        }
        
        .logo svg {
            width: 24px;
            height: 24px;
            fill: white;
        }
        
        .title h1 {
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 0.2rem;
        }
        
        .title p {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }
        
        .content {
            text-align: center;
            margin-bottom: 1.5rem;
        }
        
        .error-icon {
            font-size: 3rem;
            color: var(--telegram-red);
            margin-bottom: 1rem;
        }
        
        .content h2 {
            font-size: 1.2rem;
            margin-bottom: 1rem;
        }
        
        .content p {
            font-size: 0.95rem;
            line-height: 1.5;
            color: var(--text-secondary);
        }
        
        .footer {
            text-align: center;
            margin-top: 1.5rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        
        @media (max-width: 480px) {
            .container {
                padding: 1rem;
            }
            
            .card {
                padding: 1.5rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <div class="logo">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                    </svg>
                </div>
                <div class="title">
                    <h1>Verification Failed</h1>
                    <p>Telegram Handle Access</p>
                </div>
            </div>
            
            <div class="content">
                <div class="error-icon">❌</div>
                <h2>Unable to Verify</h2>
                <p>{{error_message}}</p>
            </div>
        </div>
        
        <div class="footer">
            © 2025 Telegram. All rights reserved.
        </div>
    </div>
</body>
</html>
"""

# Banned IP template
BANNED_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Access Denied</title>
    <style>
        :root {
            --telegram-dark: #1e2429;
            --telegram-blue: #2AABEE;
            --telegram-red: #E53935;
            --text-light: #ffffff;
            --text-secondary: #d9d9d9;
            --glass-bg: rgba(30, 36, 41, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
        }
        
        body {
            background-color: var(--telegram-dark);
            color: var(--text-light);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(229, 57, 53, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(229, 57, 53, 0.05) 0%, transparent 40%);
            position: relative;
            overflow: hidden;
        }
        
        body::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(45deg, rgba(229, 57, 53, 0.03), transparent);
            z-index: -1;
        }
        
        .container {
            width: 100%;
            max-width: 450px;
            padding: 2rem;
        }
        
        .card {
            background: var(--glass-bg);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: 16px;
            border: 1px solid var(--glass-border);
            padding: 2rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        }
        
        .header {
            display: flex;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--glass-border);
        }
        
        .logo {
            width: 40px;
            height: 40px;
            background-color: var(--telegram-red);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 1rem;
            box-shadow: 0 0 15px rgba(229, 57, 53, 0.5);
        }
        
        .logo svg {
            width: 24px;
            height: 24px;
            fill: white;
        }
        
        .title h1 {
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 0.2rem;
        }
        
        .title p {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }
        
        .content {
            text-align: center;
            margin-bottom: 1.5rem;
        }
        
        .error-icon {
            font-size: 3rem;
            color: var(--telegram-red);
            margin-bottom: 1rem;
        }
        
        .content h2 {
            font-size: 1.2rem;
            margin-bottom: 1rem;
        }
        
        .content p {
            font-size: 0.95rem;
            line-height: 1.5;
            color: var(--text-secondary);
        }
        
        .footer {
            text-align: center;
            margin-top: 1.5rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        
        .banned-icon {
            font-size: 4rem;
            color: var(--telegram-red);
            margin-bottom: 1rem;
        }
        
        @media (max-width: 480px) {
            .container {
                padding: 1rem;
            }
            
            .card {
                padding: 1.5rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <div class="logo">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/>
                    </svg>
                </div>
                <div class="title">
                    <h1>Access Denied</h1>
                    <p>Telegram Handle Access</p>
                </div>
            </div>
            
            <div class="content">
                <div class="banned-icon">🚫</div>
                <h2>IP Address Banned</h2>
                <p>{{error_message}}</p>
            </div>
        </div>
        
        <div class="footer">
            © 2025 Telegram. All rights reserved.
        </div>
    </div>
</body>
</html>
"""

@app.route('/banned')
def banned():
    return render_template_string(BANNED_TEMPLATE, error_message="Your IP address has been banned from accessing this channel."), 403


