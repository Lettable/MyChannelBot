from flask import Flask, request, render_template_string, redirect, session
from datetime import datetime, timedelta
import requests
import random
import string
import base64
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import config
from shield import app as nigger
from shield.database import db

app = Flask(__name__)
app.secret_key = os.urandom(24)

invite_requests = db['invite_requests']

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
        font = ImageFont.truetype("arial.ttf", 32)
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


@app.route('/verify')
def verify():
    uid = request.args.get('uid')
    entry = invite_requests.find_one({"uid": uid})
    if not entry or entry.get("used") or entry.get("expires_at") < datetime.utcnow():
        return render_template_string(ERROR_TEMPLATE, error_message="Link expired or invalid."), 400
    
    captcha = generate_captcha()
    session['captcha_answer'] = captcha['answer']
    session['uid'] = uid
    
    return render_template_string(VERIFY_TEMPLATE, 
                                 uid=uid, 
                                 captcha_image=captcha['image'])


@app.route('/verify_callback', methods=['POST'])
def verify_callback():
    uid = session.get('uid')
    user_answer = request.form.get('captcha_answer')
    correct_answer = session.get('captcha_answer')
    
    if not uid or not user_answer or not correct_answer:
        return render_template_string(ERROR_TEMPLATE, error_message="Session expired. Please try again."), 400
    
    if user_answer != correct_answer:
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
        link = nigger.create_chat_invite_link(
            entry["channel_id"],
            expire_date=expiration_time,
            member_limit=1
        ).invite_link

        invite_requests.update_one(
            {"uid": uid},
            {"$set": {"used": True, "invite_link": link}}
        )

        requester = entry["requester"]
        ip = request.remote_addr
        
        try:
            mirza = nigger.get_users(requester)
            nigger.send_message(
                entry["owner_id"],
                f"✅ Request `{uid}` VERIFIED\n"
                f"User: {mirza.mention}\n"
                f"IP: `{ip}`\n"
                f"Invite: `{link}`\n"
                f"Time: {datetime.utcnow().isoformat()}"
            )
        except Exception as e:
            print(f"Error sending notification: {e}")

        session.pop('captcha_answer', None)
        session.pop('uid', None)
        
        return redirect(link, code=302)
    except Exception as e:
        return render_template_string(ERROR_TEMPLATE, error_message=f"An error occurred: {str(e)}"), 500


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
                    <p>Telegram Channel Access</p>
                </div>
            </div>
            
            <div class="content">
                <p>Please solve the math problem below to verify you're human and access the Telegram channel.</p>
                
                <form action="/verify_callback" method="post" id="verification-form">
                    <input type="hidden" name="uid" value="{{uid}}">
                    
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
                    
                    <button type="submit">Verify and Continue</button>
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
</body>
</html>
"""

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
                    <p>Telegram Channel Access</p>
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
