
# Add this at the very top of app.py
import os
import sys

# Vercel compatibility - handle serverless environment
if os.environ.get('VERCEL'):
    print("🚀 Running on Vercel (serverless mode)")
    
    # Disable background threads in serverless
    _auto_thread = None
    _auto_stop = None
    
    def start_auto_pilot():
        return {"success": False, "error": "Auto-pilot disabled in serverless environment"}
    
    def stop_auto_pilot():
        return {"success": False, "error": "Auto-pilot disabled in serverless environment"}
    
    def _auto_loop():
        pass




"""
Bluesky AI Vault → Bluesky
AI chat on top of Bluesky fetch → vault → schedule / post-now (AT Protocol)
Source: Bluesky · Destination: Bluesky
"""

from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from atproto import Client
import json
import os
import requests
from datetime import datetime, timedelta
import traceback
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import psycopg2
from psycopg2.extras import Json, RealDictCursor
import uuid
import re
import random
import time
import base64
import pytz
import threading
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='static')
CORS(app)




# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://neondb_owner:npg_dolLeIK7NH1y@ep-patient-scene-axu5gxqm-pooler.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
)

SCHEDULE_TIMEZONE = "Africa/Nairobi"
TIMEZONE = "Africa/Nairobi"
LOCAL_TIMEZONE = pytz.timezone(TIMEZONE)

# ============================================================
# GEMINI CONFIG - Models with fallback
# ============================================================

# Google Gemini API — Load from environment variables only
_env_keys = os.environ.get('GEMINI_API_KEYS', '') or os.environ.get('GEMINI_API_KEY', '')
if _env_keys:
    GEMINI_API_KEYS = [k.strip() for k in _env_keys.split(',') if k.strip()]
    print(f"✅ Loaded {len(GEMINI_API_KEYS)} Gemini keys from environment")
else:
    GEMINI_API_KEYS = []
    print("⚠️  No GEMINI_API_KEYS environment variable set!")

# Models in order of preference (highest quality first)

# Models in order of preference (highest quality first)
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",   
    "gemini-2.5-flash-lite",   
    "gemini-3.6-flash",    
    "gemini-3.7-flash",        
    
]

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# ============================================================
# GEMINI STATE VARIABLES
# ============================================================

_gemini_model_index = 0
_gemini_key_index = 0
_gemini_key_cooldown = {}
_gemini_model_cooldown = {}

# ============================================================
# GEMINI HELPER FUNCTIONS
# ============================================================

def next_gemini_key():
    """Get next available Gemini API key (skip cooldown keys)"""
    global _gemini_key_index
    if not GEMINI_API_KEYS:
        return None
    
    # Try to find a working key
    for _ in range(len(GEMINI_API_KEYS) * 2):
        key_index = _gemini_key_index % len(GEMINI_API_KEYS)
        key = GEMINI_API_KEYS[key_index]
        
        # Check if key is on cooldown
        if key in _gemini_key_cooldown:
            cooldown_until = _gemini_key_cooldown[key]
            if datetime.now() < cooldown_until:
                _gemini_key_index += 1
                continue
        
        _gemini_key_index += 1
        return key
    
    # All keys on cooldown
    print("⚠️ All API keys on cooldown")
    return GEMINI_API_KEYS[0] if GEMINI_API_KEYS else None

def next_gemini_model():
    """Get next model in round-robin fashion"""
    global _gemini_model_index
    if not GEMINI_MODELS:
        return "gemini-2.5-flash-lite"
    
    model = GEMINI_MODELS[_gemini_model_index % len(GEMINI_MODELS)]
    _gemini_model_index += 1
    return model

def handle_model_rate_limit(model):
    """Put a model on cooldown if it's rate-limited"""
    _gemini_model_cooldown[model] = datetime.now() + timedelta(seconds=60)
    print(f"⏳ Model {model} on cooldown for 60 seconds")
    
    
    
    
    
    
    
    
    
    
    
    

sessions = {}  # in-memory session cache
MASTER_SESSION_ID = None  # Global master session ID








# ============================================================
# PERSISTENT SESSION MANAGEMENT
# ============================================================

def ensure_session_active(session_id=None, handle=None):
    """Ensure a session is active. If not in memory, try to restore from database."""
    if session_id and session_id in sessions:
        try:
            client = sessions[session_id]['client']
            client.me  # Verify session is still valid
            return session_id, sessions[session_id]
        except Exception:
            del sessions[session_id]
            session_id = None
    
    if session_id:
        result = tool_restore_session(session_id)
        if result.get('success'):
            return result.get('session_id'), sessions.get(result.get('session_id'))
    
    if handle:
        result = tool_restore_session(handle)
        if result.get('success'):
            return result.get('session_id'), sessions.get(result.get('session_id'))
    
    master_handle = load_master_handle()
    if master_handle:
        result = tool_restore_session(master_handle)
        if result.get('success'):
            return result.get('session_id'), sessions.get(result.get('session_id'))
    
    return None, None

def refresh_sessions_from_db():
    """Refresh all sessions from database."""
    try:
        conn = get_db_connection()
        if not conn:
            return 0
        
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, session_string, handle, display_name 
            FROM sessions 
            WHERE expires_at > CURRENT_TIMESTAMP 
            ORDER BY last_used_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        restored_count = 0
        for row in rows:
            session_id, session_string, handle, display_name = row
            try:
                if session_id in sessions:
                    continue
                client = Client()
                client.login(session_string=session_string)
                sessions[session_id] = {
                    'client': client,
                    'handle': handle,
                    'session_string': session_string,
                    'display_name': display_name or handle,
                }
                restored_count += 1
            except Exception as e:
                print(f"⚠️ Could not restore session for @{handle}: {e}")
        
        return restored_count
    except Exception as e:
        print(f"⚠️ Session refresh error: {e}")
        return 0














def get_now():
    return datetime.now(LOCAL_TIMEZONE)


# ============================================================
# DATABASE
# ============================================================

def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"❌ DB connection error: {e}")
        return None


def init_db():
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()

        cur.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                session_id TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL,
                handle TEXT NOT NULL,
                display_name TEXT,
                avatar TEXT,
                session_string TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        ''')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_sessions_handle ON sessions(handle)')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS handlers (
                id SERIAL PRIMARY KEY,
                handle TEXT UNIQUE NOT NULL,
                display_name TEXT,
                avatar TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                selected BOOLEAN DEFAULT TRUE,
                is_default BOOLEAN DEFAULT FALSE
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS vault (
                id SERIAL PRIMARY KEY,
                uri TEXT UNIQUE NOT NULL,
                author TEXT NOT NULL,
                display_name TEXT,
                text TEXT,
                images JSONB,
                video JSONB,
                likes INTEGER DEFAULT 0,
                reposts INTEGER DEFAULT 0,
                replies INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                handler_handle TEXT,
                notes TEXT
            )
        ''')
        try:
            cur.execute("ALTER TABLE vault ADD COLUMN IF NOT EXISTS video JSONB")
            cur.execute("ALTER TABLE vault ADD COLUMN IF NOT EXISTS notes TEXT")
        except Exception:
            pass

        cur.execute('''
            CREATE TABLE IF NOT EXISTS deleted_posts (
                id SERIAL PRIMARY KEY,
                uri TEXT UNIQUE NOT NULL,
                handler_handle TEXT,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS posted_posts (
                id SERIAL PRIMARY KEY,
                vault_id INTEGER REFERENCES vault(id),
                uri TEXT NOT NULL,
                platform VARCHAR(50) NOT NULL,
                platform_post_id VARCHAR(200),
                status VARCHAR(50) DEFAULT 'pending',
                posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                error_message TEXT,
                metadata JSONB,
                UNIQUE(uri, platform)
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                session_key TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS auto_config (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL DEFAULT 'default',
                enabled BOOLEAN DEFAULT FALSE,
                source_handle TEXT,
                target_handle TEXT,
                content_type TEXT DEFAULT 'feed',
                poll_interval_sec INTEGER DEFAULT 300,
                media_only BOOLEAN DEFAULT TRUE,
                include_reposts BOOLEAN DEFAULT FALSE,
                max_posts_per_run INTEGER DEFAULT 2,
                bluesky_handle TEXT,
                bluesky_app_password TEXT,
                last_run_at TIMESTAMP,
                last_error TEXT,
                last_result TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS auto_seen (
                id SERIAL PRIMARY KEY,
                config_name TEXT NOT NULL DEFAULT 'default',
                uri TEXT NOT NULL,
                posted BOOLEAN DEFAULT FALSE,
                seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(config_name, uri)
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS bluesky_accounts (
                id SERIAL PRIMARY KEY,
                handle TEXT UNIQUE NOT NULL,
                display_name TEXT,
                avatar TEXT,
                session_string TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ✅ NEW: App config table for master account persistence
        cur.execute('''
            CREATE TABLE IF NOT EXISTS app_config (
                id SERIAL PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database initialized (Bluesky-only)")
    except Exception as e:
        print(f"❌ DB init error: {e}")
        traceback.print_exc()


init_db()


# ============================================================
# MASTER ACCOUNT PERSISTENCE
# ============================================================

def save_master_handle(handle):
    """Save the master account handle to database."""
    try:
        conn = get_db_connection()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO app_config (key, value, updated_at)
            VALUES ('master_handle', %s, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP
        """, (handle,))
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Master handle saved: {handle}")
        return True
    except Exception as e:
        print(f"❌ save_master_handle error: {e}")
        return False


def load_master_handle():
    """Load the saved master account handle."""
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_config WHERE key = 'master_handle'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return row[0]
        return None
    except Exception as e:
        print(f"❌ load_master_handle error: {e}")
        return None


def clear_master_handle():
    """Clear the saved master account handle."""
    try:
        conn = get_db_connection()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute("DELETE FROM app_config WHERE key = 'master_handle'")
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ clear_master_handle error: {e}")
        return False


# ============================================================
# BLUESKY POSTING (AT Protocol)
# ============================================================

def upload_blob_to_bluesky(client, image_bytes, alt_text=""):
    """Upload an image to Bluesky PDS and return blob reference."""
    try:
        image_bytes.seek(0)
        # Resize/compress for Bluesky
        img = Image.open(image_bytes)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Bluesky max ~1MB, resize if needed
        max_size = 2048
        w, h = img.size
        if max(w, h) > max_size:
            scale = max_size / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        
        out = BytesIO()
        img.save(out, format='JPEG', quality=85, optimize=True)
        out.seek(0)
        
        # Upload to Bluesky using the client's upload_blob method
        response = client.upload_blob(out.read())
        
        # Return the blob directly (the BlobRef object)
        if hasattr(response, 'blob'):
            return response.blob
        return response
    except Exception as e:
        print(f"Error uploading blob: {e}")
        traceback.print_exc()
        return None


def create_bluesky_post(client, text, image_blobs=None, embed_uri=None, embed_cid=None, 
                        scheduled_for=None, reply_to=None):
    """
    Create a Bluesky post via AT Protocol.
    """
    try:
        text = (text or "").strip()[:300]
        
        embed = None
        if image_blobs and len(image_blobs) > 0:
            images = []
            for blob in image_blobs[:4]:
                if blob:
                    images.append({
                        "image": blob,
                        "alt": ""
                    })
            if images:
                embed = {
                    "$type": "app.bsky.embed.images",
                    "images": images
                }
        
        response = client.send_post(
            text=text,
            embed=embed,
            reply_to=reply_to
        )
        
        post_uri = getattr(response, 'uri', None)
        post_cid = getattr(response, 'cid', None)
        
        return {
            "success": True,
            "post_id": post_uri,
            "uri": post_uri,
            "cid": post_cid,
            "status": "posted",
            "url": f"https://bsky.app/profile/{client.me.handle}/post/{post_uri.split('/')[-1]}" if post_uri else None
        }
    except Exception as e:
        print(f"Error creating Bluesky post: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def post_to_bluesky(client, image_bytes=None, caption="", target_handle=None, scheduled_time=None, reply_to=None):
    """Post to Bluesky via AT Protocol."""
    try:
        image_blobs = []
        if image_bytes:
            blob = upload_blob_to_bluesky(client, image_bytes)
            if blob:
                image_blobs.append(blob)
        
        result = create_bluesky_post(
            client=client,
            text=caption or "",
            image_blobs=image_blobs if image_blobs else None,
            reply_to=reply_to
        )
        
        if result.get('success'):
            result['message'] = "✅ Posted to Bluesky!"
            result['platform'] = 'bluesky'
            result['caption'] = caption or ""
        return result
        
    except Exception as e:
        print(f"Error posting to Bluesky: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ============================================================
# IMAGE HELPERS
# ============================================================

def data_url_to_jpeg_bytes(image_data: str):
    try:
        raw = image_data
        if ',' in raw and str(raw).strip().lower().startswith('data:'):
            raw = raw.split(',', 1)[1]
        binary = base64.b64decode(raw)
        img = Image.open(BytesIO(binary))
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        out = BytesIO()
        img.save(out, format='JPEG', quality=92, optimize=True)
        out.seek(0)
        return out, None
    except Exception as e:
        traceback.print_exc()
        return None, f"Invalid image data: {e}"


# ============================================================
# SESSION MANAGEMENT
# ============================================================

def get_sessions_by_handles(handles):
    """Get session IDs for a list of handles."""
    found_sessions = []
    not_found = []
    
    for handle in handles:
        handle = handle.lstrip('@').strip()
        found = False
        
        for sid, s in sessions.items():
            if s.get('handle', '').lower() == handle.lower():
                found_sessions.append(sid)
                found = True
                break
        
        if not found:
            not_found.append(handle)
    
    if not_found:
        print(f"⚠️ No sessions found for handles: {', '.join(not_found)}")
    
    return found_sessions


def get_all_session_ids():
    """Get all active session IDs."""
    return list(sessions.keys())


def get_all_session_handles():
    """Get all active session handles."""
    return [s.get('handle') for s in sessions.values() if s.get('handle')]


def get_session_by_handle(handle):
    """Get a session by handle."""
    handle = handle.lstrip('@').strip()
    for sid, s in sessions.items():
        if s.get('handle', '').lower() == handle.lower():
            return sid, s
    return None, None


def set_master_account(session_id_or_handle):
    """
    Set which account is the master account (used for fetching).
    """
    global MASTER_SESSION_ID
    
    # If it's a handle, find the session
    if isinstance(session_id_or_handle, str) and ('@' in session_id_or_handle or '.' in session_id_or_handle):
        handle = session_id_or_handle.lstrip('@')
        for sid, s in sessions.items():
            if s.get('handle', '').lower() == handle.lower():
                MASTER_SESSION_ID = sid
                save_master_handle(handle)
                return {
                    "success": True,
                    "message": f"✅ Master account set to @{handle}",
                    "master_handle": handle,
                    "session_id": sid
                }
        return {"success": False, "error": f"No session found for handle: {handle}"}
    
    # If it's a session ID
    if session_id_or_handle in sessions:
        MASTER_SESSION_ID = session_id_or_handle
        handle = sessions[session_id_or_handle].get('handle')
        save_master_handle(handle)
        return {
            "success": True,
            "message": f"✅ Master account set to @{handle}",
            "master_handle": handle,
            "session_id": session_id_or_handle
        }
    
    return {"success": False, "error": "Invalid session ID or handle"}


def get_master_session():
    """Get the master account session, auto-restoring if needed."""
    global MASTER_SESSION_ID
    
    if MASTER_SESSION_ID and MASTER_SESSION_ID in sessions:
        return MASTER_SESSION_ID, sessions[MASTER_SESSION_ID]
    
    saved_master = load_master_handle()
    if saved_master:
        sid, session = ensure_session_active(handle=saved_master)
        if sid:
            MASTER_SESSION_ID = sid
            return sid, session
    
    sid, session = ensure_session_active()
    if sid:
        MASTER_SESSION_ID = sid
        return sid, session
    
    return None, None


def logout_session(session_id_or_handle):
    """
    Logout a session by session_id or handle.
    Removes from memory and invalidates in database.
    """
    global MASTER_SESSION_ID
    try:
        # Check if it's a session ID
        if session_id_or_handle in sessions:
            sid = session_id_or_handle
            handle = sessions[sid].get('handle')
            
            # If this is the master, clear it
            if sid == MASTER_SESSION_ID:
                MASTER_SESSION_ID = None
                clear_master_handle()
            
            # Remove from memory
            del sessions[sid]
            
            # Update database
            conn = get_db_connection()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception as e:
                    print(f"⚠️ Failed to remove session from DB: {e}")
            
            return {"success": True, "message": f"✅ Logged out @{handle}"}
        
        # Check if it's a handle
        handle = session_id_or_handle.lstrip('@').strip()
        for sid, s in list(sessions.items()):
            if s.get('handle', '').lower() == handle.lower():
                # If this is the master, clear it
                if sid == MASTER_SESSION_ID:
                    MASTER_SESSION_ID = None
                    clear_master_handle()
                
                # Remove from memory
                del sessions[sid]
                
                # Update database
                conn = get_db_connection()
                if conn:
                    try:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM sessions WHERE handle = %s", (handle,))
                        conn.commit()
                        cur.close()
                        conn.close()
                    except Exception as e:
                        print(f"⚠️ Failed to remove session from DB: {e}")
                
                return {"success": True, "message": f"✅ Logged out @{handle}"}
        
        return {"success": False, "error": f"No session found for: {session_id_or_handle}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def logout_all_sessions():
    """Logout all sessions."""
    global MASTER_SESSION_ID
    try:
        handles = list(get_all_session_handles())
        
        # Clear memory
        sessions.clear()
        MASTER_SESSION_ID = None
        clear_master_handle()
        
        # Clear database
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM sessions")
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"⚠️ Failed to clear sessions from DB: {e}")
        
        return {
            "success": True, 
            "message": f"✅ Logged out all {len(handles)} sessions",
            "logged_out": handles
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# BLUESKY TOOLS
# ============================================================

def tool_login(username, password):
    """
    Login to Bluesky with handle and app password.
    Reuses existing session if already logged in.
    """
    try:
        username = username.strip()
        password = password.strip()
        handle = username.lstrip('@')
        
        # Check if we already have a session for this handle
        for sid, s in sessions.items():
            if s.get('handle', '').lower() == handle.lower():
                try:
                    client = s['client']
                    profile = client.me
                    return {
                        "success": True,
                        "session_id": sid,
                        "handle": s['handle'],
                        "display_name": s.get('display_name', s['handle']),
                        "message": f"✅ Reusing existing session for @{s['handle']}",
                        "reused": True
                    }
                except Exception as e:
                    print(f"⚠️ Session for @{handle} is invalid: {e}")
                    try:
                        del sessions[sid]
                    except KeyError:
                        pass
                    break
        
        # Create new session
        client = Client()
        client.login(username, password)
        profile = client.me
        handle = profile.handle
        session_id = str(uuid.uuid4())
        session_string = client.export_session_string()
        expires = datetime.utcnow() + timedelta(days=30)
        
        display_name = getattr(profile, 'display_name', None) or handle
        
        sessions[session_id] = {
            'client': client,
            'handle': handle,
            'display_name': display_name,
            'session_string': session_string,
            'avatar': getattr(profile, 'avatar', None),
            'created_at': datetime.utcnow().isoformat()
        }
        
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT session_id FROM sessions WHERE handle = %s AND expires_at > CURRENT_TIMESTAMP", (handle,))
                existing = cur.fetchone()
                
                if existing:
                    old_sid = existing[0]
                    cur.execute("""
                        UPDATE sessions 
                        SET session_string = %s, 
                            display_name = %s,
                            last_used_at = CURRENT_TIMESTAMP,
                            expires_at = %s
                        WHERE handle = %s
                    """, (session_string, display_name, expires, handle))
                    if old_sid in sessions and old_sid != session_id:
                        try:
                            del sessions[old_sid]
                        except KeyError:
                            pass
                else:
                    cur.execute("""
                        INSERT INTO sessions (session_id, username, handle, display_name, session_string, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (session_id, username, handle, display_name, session_string, expires))
                
                conn.commit()
                cur.close()
                conn.close()
                print(f"✅ Session saved to database for @{handle}")
            except Exception as e:
                print(f"⚠️ Session save error: {e}")
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
        
        return {
            "success": True,
            "session_id": session_id,
            "handle": handle,
            "display_name": display_name,
            "message": f"✅ Logged in as @{handle}",
            "reused": False,
            "active_sessions": len(sessions)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_restore_session(handle_or_sid):
    try:
        conn = get_db_connection()
        if not conn:
            return {"success": False, "error": "DB unavailable"}
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, session_string, handle FROM sessions
            WHERE (handle = %s OR session_id = %s) AND expires_at > CURRENT_TIMESTAMP
            ORDER BY last_used_at DESC LIMIT 1
        """, (handle_or_sid.lstrip('@'), handle_or_sid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return {"success": False, "error": f"No valid session for {handle_or_sid}"}
        client = Client()
        client.login(session_string=row[1])
        sid = row[0]
        sessions[sid] = {
            'client': client,
            'handle': row[2],
            'session_string': row[1]
        }
        return {
            "success": True,
            "session_id": sid,
            "handle": row[2],
            "message": f"Restored session for @{row[2]}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_fetch_posts(session_id, actor, limit=15, include_reposts=False, media_only=True):
    """
    Fetch posts from a Bluesky handle using the master account session.
    """
    if session_id not in sessions:
        return {"success": False, "error": "Not logged in / invalid session"}
    client = sessions[session_id]['client']
    
    master_handle = sessions[session_id].get('handle')
    print(f"🔍 Fetching posts from @{actor} using master account @{master_handle}")
    
    try:
        if not actor.endswith('.bsky.social') and '.' not in actor:
            actor = actor + '.bsky.social'
        actor = actor.lstrip('@')

        feed = client.get_author_feed(actor=actor, limit=min(limit * 2, 50))
        posts = []
        for item in feed.feed:
            post = item.post
            if hasattr(item, 'reason') and item.reason and not include_reposts:
                continue
            record = post.record
            text = getattr(record, 'text', '') or ''
            images = []
            video = None
            
            embed = getattr(record, 'embed', None)
            if embed:
                if hasattr(embed, 'images') and embed.images:
                    for im in embed.images:
                        images.append({
                            "url": getattr(im, 'fullsize', None) or "",
                            "thumb": getattr(im, 'thumb', None) or "",
                            "alt": getattr(im, 'alt', '') or ''
                        })
                if hasattr(embed, 'media') and embed.media and hasattr(embed.media, 'images'):
                    for im in embed.media.images:
                        images.append({
                            "url": getattr(im, 'fullsize', None) or "",
                            "thumb": getattr(im, 'thumb', None) or "",
                            "alt": getattr(im, 'alt', '') or ''
                        })

            view_embed = getattr(post, 'embed', None)
            if view_embed:
                if hasattr(view_embed, 'images') and view_embed.images:
                    images = []
                    for im in view_embed.images:
                        images.append({
                            "url": getattr(im, 'fullsize', None) or "",
                            "thumb": getattr(im, 'thumb', None) or "",
                            "alt": getattr(im, 'alt', '') or ''
                        })

            if media_only and not images and not video:
                continue

            author = post.author
            posts.append({
                "uri": post.uri,
                "cid": post.cid,
                "author": author.handle,
                "display_name": getattr(author, 'display_name', None) or author.handle,
                "text": text,
                "images": images,
                "video": video,
                "likes": getattr(post, 'like_count', 0) or 0,
                "reposts": getattr(post, 'repost_count', 0) or 0,
                "replies": getattr(post, 'reply_count', 0) or 0,
                "created_at": getattr(record, 'created_at', None),
                "fetched_by": master_handle
            })
            if len(posts) >= limit:
                break

        return {"success": True, "posts": posts, "count": len(posts), "actor": actor, "fetched_by": master_handle}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def tool_add_to_vault(posts, handler_handle=None):
    if not posts:
        return {"success": False, "error": "No posts to save"}
    conn = get_db_connection()
    if not conn:
        return {"success": False, "error": "DB unavailable"}
    saved = 0
    try:
        cur = conn.cursor()
        for p in posts:
            uri = p.get('uri')
            if not uri:
                continue
            try:
                cur.execute("""
                    INSERT INTO vault (uri, author, display_name, text, images, video, likes, reposts, replies, created_at, handler_handle)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (uri) DO NOTHING
                """, (
                    uri,
                    p.get('author') or '',
                    p.get('display_name'),
                    p.get('text'),
                    Json(p.get('images') or []),
                    Json(p.get('video')) if p.get('video') else None,
                    p.get('likes') or 0,
                    p.get('reposts') or 0,
                    p.get('replies') or 0,
                    p.get('created_at'),
                    handler_handle or p.get('author'),
                ))
                if cur.rowcount > 0:
                    saved += 1
            except Exception as e:
                print(f"vault insert {uri}: {e}")
        conn.commit()
        cur.close()
        conn.close()
        return {
            "success": True,
            "saved": saved,
            "message": f"Saved {saved} post(s) to vault"
        }
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def tool_list_vault(limit=20, offset=0):
    conn = get_db_connection()
    if not conn:
        return {"success": False, "error": "DB unavailable"}
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, uri, author, display_name, text, images, video, likes, reposts, replies,
                   created_at, saved_at, handler_handle, notes
            FROM vault
            ORDER BY saved_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM vault")
        total = cur.fetchone()['count']
        cur.close()
        conn.close()
        vault = []
        for r in rows:
            vault.append({
                "id": r['id'],
                "uri": r['uri'],
                "author": r['author'],
                "display_name": r['display_name'],
                "text": r['text'],
                "images": r['images'] or [],
                "video": r['video'],
                "likes": r['likes'],
                "reposts": r['reposts'],
                "replies": r['replies'],
                "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                "saved_at": r['saved_at'].isoformat() if r['saved_at'] else None,
                "handler_handle": r['handler_handle'],
                "notes": r['notes'],
            })
        return {"success": True, "vault": vault, "count": total}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_list_vault_by_status(status=None, limit=50, offset=0):
    """List vault items filtered by post status."""
    conn = get_db_connection()
    if not conn:
        return {"success": False, "error": "DB unavailable"}
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if status == 'unposted':
            cur.execute("""
                SELECT v.id, v.uri, v.author, v.display_name, v.text, v.images, v.video, 
                       v.likes, v.reposts, v.replies, v.created_at, v.saved_at, 
                       v.handler_handle, v.notes,
                       NULL as post_status, NULL as posted_at, NULL as platform_post_id
                FROM vault v
                WHERE NOT EXISTS (
                    SELECT 1 FROM posted_posts p 
                    WHERE p.uri = v.uri AND p.status IN ('completed', 'posted') AND p.platform = 'bluesky'
                )
                ORDER BY v.saved_at DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
        elif status in ('posted', 'completed'):
            cur.execute("""
                SELECT v.id, v.uri, v.author, v.display_name, v.text, v.images, v.video, 
                       v.likes, v.reposts, v.replies, v.created_at, v.saved_at, 
                       v.handler_handle, v.notes,
                       p.status as post_status, p.posted_at, p.platform_post_id
                FROM vault v
                INNER JOIN posted_posts p ON p.uri = v.uri AND p.platform = 'bluesky'
                WHERE p.status IN ('completed', 'posted')
                ORDER BY p.posted_at DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
        elif status == 'scheduled':
            cur.execute("""
                SELECT v.id, v.uri, v.author, v.display_name, v.text, v.images, v.video, 
                       v.likes, v.reposts, v.replies, v.created_at, v.saved_at, 
                       v.handler_handle, v.notes,
                       p.status as post_status, p.posted_at, p.platform_post_id
                FROM vault v
                INNER JOIN posted_posts p ON p.uri = v.uri AND p.platform = 'bluesky'
                WHERE p.status = 'scheduled'
                ORDER BY p.posted_at DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
        else:
            cur.execute("""
                SELECT v.id, v.uri, v.author, v.display_name, v.text, v.images, v.video, 
                       v.likes, v.reposts, v.replies, v.created_at, v.saved_at, 
                       v.handler_handle, v.notes,
                       COALESCE(p.status, 'unposted') as post_status, 
                       p.posted_at, p.platform_post_id
                FROM vault v
                LEFT JOIN posted_posts p ON p.uri = v.uri AND p.platform = 'bluesky'
                ORDER BY v.saved_at DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
        
        rows = cur.fetchall()
        
        # Get total count for the filtered query
        if status == 'unposted':
            cur.execute("""
                SELECT COUNT(*) FROM vault v
                WHERE NOT EXISTS (
                    SELECT 1 FROM posted_posts p 
                    WHERE p.uri = v.uri AND p.status IN ('completed', 'posted') AND p.platform = 'bluesky'
                )
            """)
        elif status in ('posted', 'completed'):
            cur.execute("""
                SELECT COUNT(*) FROM vault v
                INNER JOIN posted_posts p ON p.uri = v.uri AND p.platform = 'bluesky'
                WHERE p.status IN ('completed', 'posted')
            """)
        elif status == 'scheduled':
            cur.execute("""
                SELECT COUNT(*) FROM vault v
                INNER JOIN posted_posts p ON p.uri = v.uri AND p.platform = 'bluesky'
                WHERE p.status = 'scheduled'
            """)
        else:
            cur.execute("SELECT COUNT(*) FROM vault")
        
        total = cur.fetchone()['count']
        cur.close()
        conn.close()
        
        vault = []
        for r in rows:
            vault.append({
                "id": r['id'],
                "uri": r['uri'],
                "author": r['author'],
                "display_name": r['display_name'],
                "text": r['text'],
                "images": r['images'] or [],
                "video": r['video'],
                "likes": r['likes'],
                "reposts": r['reposts'],
                "replies": r['replies'],
                "created_at": r['created_at'].isoformat() if r['created_at'] else None,
                "saved_at": r['saved_at'].isoformat() if r['saved_at'] else None,
                "handler_handle": r['handler_handle'],
                "notes": r['notes'],
                "post_status": r.get('post_status') or 'unposted',
                "posted_at": r['posted_at'].isoformat() if r.get('posted_at') else None,
                "platform_post_id": r.get('platform_post_id'),
            })
        return {"success": True, "vault": vault, "count": total, "status_filter": status or 'all'}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_delete_vault_items(ids=None, status=None, all=False):
    """Delete vault items by ID, by status, or all."""
    try:
        conn = get_db_connection()
        if not conn:
            return {"success": False, "error": "Database unavailable"}
        
        cur = conn.cursor()
        deleted_count = 0
        deleted_uris = []
        
        if ids and isinstance(ids, list):
            placeholders = ','.join(['%s'] * len(ids))
            cur.execute(f"SELECT id, uri FROM vault WHERE id IN ({placeholders})", ids)
            items = cur.fetchall()
        elif status == 'unposted':
            cur.execute("""
                SELECT id, uri FROM vault v
                WHERE NOT EXISTS (
                    SELECT 1 FROM posted_posts p 
                    WHERE p.uri = v.uri AND p.status IN ('completed', 'posted') AND p.platform = 'bluesky'
                )
            """)
            items = cur.fetchall()
        elif status in ('posted', 'completed'):
            cur.execute("""
                SELECT v.id, v.uri FROM vault v
                INNER JOIN posted_posts p ON p.uri = v.uri AND p.platform = 'bluesky'
                WHERE p.status IN ('completed', 'posted')
            """)
            items = cur.fetchall()
        elif status == 'scheduled':
            cur.execute("""
                SELECT v.id, v.uri FROM vault v
                INNER JOIN posted_posts p ON p.uri = v.uri AND p.platform = 'bluesky'
                WHERE p.status = 'scheduled'
            """)
            items = cur.fetchall()
        elif all:
            cur.execute("SELECT id, uri FROM vault")
            items = cur.fetchall()
        else:
            return {"success": False, "error": "Specify ids, status, or all=True"}
        
        if not items:
            cur.close()
            conn.close()
            return {"success": True, "deleted_count": 0, "message": "No items to delete"}
        
        for item in items:
            item_id, uri = item
            cur.execute("DELETE FROM posted_posts WHERE uri = %s AND platform = 'bluesky'", (uri,))
            cur.execute("DELETE FROM vault WHERE id = %s", (item_id,))
            deleted_count += 1
            deleted_uris.append(uri)
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "deleted_uris": deleted_uris,
            "message": f"🗑️ Permanently deleted {deleted_count} item(s) from vault"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_post_unposted(session_id=None, target_handle=None, limit=10):
    """Post all unposted vault items to Bluesky."""
    result = tool_list_vault_by_status(status='unposted', limit=limit)
    if not result.get('success'):
        return result
    
    items = result.get('vault', [])
    if not items:
        return {"success": True, "posted_count": 0, "message": "No unposted items to post"}
    
    posted = 0
    errors = []
    results = []
    
    for item in items:
        res = tool_post_now(
            session_id=session_id,
            vault_id=item.get('id'),
            target_handle=target_handle
        )
        results.append(res)
        if res.get('success'):
            posted += 1
        else:
            errors.append(res.get('error', 'Unknown error'))
        time.sleep(1.5)
    
    return {
        "success": posted > 0,
        "posted_count": posted,
        "total": len(items),
        "results": results,
        "errors": errors,
        "message": f"Posted {posted}/{len(items)} unposted items to Bluesky"
    }
def _get_vault_item(vault_id=None, uri=None):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if vault_id is not None:
            cur.execute("SELECT * FROM vault WHERE id = %s", (int(vault_id),))
        elif uri:
            cur.execute("SELECT * FROM vault WHERE uri = %s", (uri,))
        else:
            cur.close()
            conn.close()
            return None
        row = cur.fetchone()
        cur.close()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"_get_vault_item: {e}")
        return None


def _download_image_to_bytes(url):
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            return BytesIO(r.content)
    except Exception as e:
        print(f"download image: {e}")
    return None


def tool_post_now(session_id=None, uri=None, vault_id=None, caption=None, target_handle=None, session_ids=None, posting_accounts=None):
    """
    Post a vault item to one or multiple Bluesky accounts.
    """
    posting_sessions = []
    
    if posting_accounts and isinstance(posting_accounts, list):
        for handle in posting_accounts:
            handle = handle.lstrip('@').strip()
            found = False
            for sid, s in sessions.items():
                if s.get('handle', '').lower() == handle.lower():
                    posting_sessions.append({
                        'session_id': sid,
                        'client': s['client'],
                        'handle': s['handle']
                    })
                    found = True
                    break
            if not found:
                print(f"⚠️ No session found for posting account: {handle}")
        if not posting_sessions:
            return {"success": False, "error": "No valid posting sessions found"}
    elif session_ids and isinstance(session_ids, list):
        for sid in session_ids:
            if sid in sessions:
                posting_sessions.append({
                    'session_id': sid,
                    'client': sessions[sid]['client'],
                    'handle': sessions[sid]['handle']
                })
        if not posting_sessions:
            return {"success": False, "error": "No valid sessions found"}
    elif session_id and session_id in sessions:
        posting_sessions.append({
            'session_id': session_id,
            'client': sessions[session_id]['client'],
            'handle': sessions[session_id]['handle']
        })
    elif target_handle:
        target_handle = target_handle.lstrip('@')
        for sid, s in sessions.items():
            if s.get('handle', '').lower() == target_handle.lower():
                posting_sessions.append({
                    'session_id': sid,
                    'client': s['client'],
                    'handle': s['handle']
                })
                break
        if not posting_sessions:
            return {"success": False, "error": f"No session found for handle: {target_handle}"}
    else:
        for sid, s in sessions.items():
            posting_sessions.append({
                'session_id': sid,
                'client': s['client'],
                'handle': s['handle']
            })
        if not posting_sessions:
            return {"success": False, "error": "Not logged in / no valid session"}
    
    item = _get_vault_item(vault_id=vault_id, uri=uri)
    if not item:
        return {"success": False, "error": "Vault item not found"}

    images = item.get('images') or []
    image_url = None
    image_bytes = None
    
    if images:
        first = images[0]
        if isinstance(first, str):
            image_url = first
        else:
            image_url = first.get('url') or first.get('fullsize') or first.get('thumb')

    text = (caption if caption is not None and str(caption).strip() != '' else (item.get('text') or ''))[:300]
    original_author = item.get('author', 'unknown')
    fetched_by = item.get('fetched_by', 'unknown')

    if image_url and image_url.startswith(('http://', 'https://')):
        image_bytes = _download_image_to_bytes(image_url)
    elif images and isinstance(images[0], dict) and images[0].get('url', '').startswith('data:'):
        try:
            data_url = images[0].get('url')
            if ',' in data_url:
                base64_data = data_url.split(',', 1)[1]
                binary = base64.b64decode(base64_data)
                img = Image.open(BytesIO(binary))
                out = BytesIO()
                img.save(out, format='JPEG', quality=85, optimize=True)
                out.seek(0)
                image_bytes = out
        except Exception as e:
            print(f"Error processing data URL: {e}")

    all_results = []
    success_count = 0
    
    for session_info in posting_sessions:
        client = session_info['client']
        handle = session_info['handle']
        sid = session_info['session_id']
        
        img_copy = None
        if image_bytes:
            image_bytes.seek(0)
            img_copy = BytesIO(image_bytes.read())
        
        image_blobs = []
        if img_copy:
            blob = upload_blob_to_bluesky(client, img_copy)
            if blob:
                image_blobs.append(blob)
        
        if image_blobs:
            result = create_bluesky_post(
                client=client,
                text=text,
                image_blobs=image_blobs
            )
        else:
            result = create_bluesky_post(
                client=client,
                text=text
            )
        
        if result.get('success'):
            success_count += 1
            result['handle'] = handle
            result['session_id'] = sid
            result['vault_id'] = item.get('id')
            result['original_author'] = original_author
            result['fetched_by'] = fetched_by
            
            try:
                conn = get_db_connection()
                if conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id FROM posted_posts 
                        WHERE uri = %s AND platform = 'bluesky' AND metadata->>'handle' = %s
                    """, (item.get('uri'), handle))
                    existing = cur.fetchone()
                    
                    if not existing:
                        cur.execute("""
                            INSERT INTO posted_posts (vault_id, uri, platform, platform_post_id, status, metadata)
                            VALUES (%s, %s, 'bluesky', %s, 'posted', %s)
                        """, (
                            item.get('id'),
                            item.get('uri'),
                            result.get('post_id') or result.get('uri'),
                            Json({
                                "handle": handle, 
                                "session_id": sid,
                                "original_author": original_author,
                                "fetched_by": fetched_by
                            })
                        ))
                    else:
                        cur.execute("""
                            UPDATE posted_posts 
                            SET platform_post_id = %s, status = 'posted', posted_at = CURRENT_TIMESTAMP
                            WHERE uri = %s AND platform = 'bluesky' AND metadata->>'handle' = %s
                        """, (
                            result.get('post_id') or result.get('uri'),
                            item.get('uri'),
                            handle
                        ))
                    conn.commit()
                    cur.close()
                    conn.close()
            except Exception as e:
                print(f"posted_posts: {e}")
        else:
            result['handle'] = handle
            result['session_id'] = sid
            result['error'] = result.get('error', 'Unknown error')
        
        all_results.append(result)
        time.sleep(1)

    if len(posting_sessions) == 1:
        single_result = all_results[0] if all_results else {"success": False, "error": "No results"}
        if single_result.get('success'):
            single_result['message'] = f"✅ Posted to @{single_result.get('handle')} (original: @{original_author})"
            if image_bytes:
                single_result['has_image'] = True
        return single_result
    else:
        handles = [r.get('handle') for r in all_results if r.get('success')]
        failed = [r.get('handle') for r in all_results if not r.get('success')]
        
        msg = f"✅ Posted to {success_count}/{len(posting_sessions)} accounts"
        if handles:
            msg += f": @{', @'.join(handles)}"
        if failed:
            msg += f" ❌ Failed: @{', @'.join(failed)}"
        msg += f" (original post by @{original_author})"
        
        return {
            "success": success_count > 0,
            "posted_count": success_count,
            "total": len(posting_sessions),
            "results": all_results,
            "vault_id": item.get('id'),
            "has_image": bool(image_bytes),
            "successful_handles": handles,
            "failed_handles": failed,
            "original_author": original_author,
            "fetched_by": fetched_by,
            "message": msg
        }


def tool_post_vault_batch(session_id, count=3, target_handle=None):
    if session_id not in sessions:
        return {"success": False, "error": "Not logged in / invalid session"}
    
    r = tool_list_vault(limit=max(count * 2, 10))
    items = r.get('vault') or []
    posted_uris = set()
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT uri FROM posted_posts WHERE platform = 'bluesky' AND status = 'posted'")
            posted_uris = {row[0] for row in cur.fetchall()}
            cur.close()
            conn.close()
    except Exception:
        pass

    chosen = []
    for it in items:
        if it.get('uri') in posted_uris:
            continue
        chosen.append(it)
        if len(chosen) >= count:
            break

    results = []
    posted = 0
    for it in chosen:
        res = tool_post_now(
            session_id=session_id,
            vault_id=it.get('id'),
            target_handle=target_handle
        )
        results.append(res)
        if res.get('success'):
            posted += 1
        time.sleep(1.5)

    return {
        "success": posted > 0,
        "posted_count": posted,
        "results": results,
        "message": f"Posted {posted}/{len(chosen)} items to Bluesky"
    }


def tool_list_accounts(platform='bluesky'):
    """List Bluesky accounts."""
    accounts = []
    master_sid, _ = get_master_session()
    for sid, s in sessions.items():
        if s.get('handle'):
            accounts.append({
                "account_id": sid,
                "label": s.get('handle'),
                "username": s.get('handle'),
                "display_name": s.get('display_name', s.get('handle')),
                "platform": "bluesky",
                "profile_picture": None,
                "is_master": sid == master_sid
            })
    
    return {
        "success": True,
        "accounts": accounts,
        "count": len(accounts),
        "master_session_id": master_sid,
        "message": f"Bluesky accounts ({len(accounts)}):\n" + "\n".join(f"• @{a['label']}" + (" 👑 MASTER" if a['is_master'] else "") for a in accounts) if accounts else "No Bluesky sessions active. Login first.",
        "destination": "bluesky",
    }


def tool_get_status(session_id=None):
    vault_count = scheduled_count = posted_count = accounts_count = 0
    active_handle = None
    is_master = False
    master_handle = None
    
    # Auto-refresh sessions if none exist
    if not sessions:
        refresh_sessions_from_db()
    
    if session_id and session_id not in sessions:
        sid, session = ensure_session_active(session_id)
        if sid:
            session_id = sid
            active_handle = session.get('handle')
    
    if session_id and session_id in sessions:
        active_handle = sessions[session_id].get('handle')
    
    master_sid, master_session = get_master_session()
    
    if master_sid and session_id == master_sid:
        is_master = True
    if master_session:
        master_handle = master_session.get('handle')
    
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM vault")
            vault_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM posted_posts WHERE platform = 'bluesky'")
            posted_count = cur.fetchone()[0]
            cur.close()
            conn.close()
    except Exception as e:
        print(f"status: {e}")

    posting_count = 0
    for sid, s in sessions.items():
        if sid != master_sid:
            posting_count += 1

    return {
        "success": True,
        "vault_count": vault_count,
        "scheduled_count": scheduled_count,
        "posted_count": posted_count,
        "accounts_count": posting_count,
        "total_sessions": len(sessions),
        "active_handle": active_handle,
        "is_master": is_master,
        "master_handle": master_handle,
        "master_session_id": master_sid,
        "platform": "bluesky",
        "destination": "bluesky",
        "message": (
            f"Destination: Bluesky · Vault: {vault_count} · "
            f"Posted (Bluesky): {posted_count} · Posting accounts: {posting_count}"
            + (f" · 👑 Master: @{master_handle}" if master_handle else " · No master set")
            + (f" · Active: @{active_handle}" if active_handle else "")
        )
    }


def tool_list_scheduled():
    try:
        conn = get_db_connection()
        if not conn:
            return {"success": True, "scheduled": [], "count": 0}
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, v.text, p.platform_post_id, p.status, p.posted_at
            FROM posted_posts p
            LEFT JOIN vault v ON p.vault_id = v.id
            WHERE p.platform = 'bluesky' AND p.status = 'pending'
            ORDER BY p.posted_at DESC
            LIMIT 50
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        items = []
        for row in rows:
            items.append({
                "id": row[0],
                "text": (row[1] or '')[:120],
                "post_id": row[2],
                "status": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
            })
        return {"success": True, "scheduled": items, "count": len(items)}
    except Exception as e:
        return {"success": False, "error": str(e), "scheduled": [], "count": 0}


# ============================================================
# AUTO PILOT (Bluesky → Bluesky)
# ============================================================

_auto_thread = None
_auto_stop = threading.Event()


def _load_auto_config(name='default'):
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cur = conn.cursor()
        cur.execute("SELECT * FROM auto_config WHERE name = %s", (name,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return None
        cols = [d[0] for d in cur.description]
        cur.close()
        conn.close()
        return dict(zip(cols, row))
    except Exception as e:
        print(f"load auto_config: {e}")
        return None


def _list_auto_configs():
    try:
        conn = get_db_connection()
        if not conn:
            return []
        cur = conn.cursor()
        cur.execute("SELECT * FROM auto_config ORDER BY name")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        cur.close()
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        print(f"list auto_configs: {e}")
        return []


def _save_auto_config(cfg: dict):
    try:
        conn = get_db_connection()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO auto_config (
                name, enabled, source_handle, target_handle,
                content_type, poll_interval_sec, media_only, include_reposts,
                max_posts_per_run, bluesky_handle, bluesky_app_password,
                last_run_at, last_error, last_result, updated_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP
            )
            ON CONFLICT (name) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                source_handle = COALESCE(EXCLUDED.source_handle, auto_config.source_handle),
                target_handle = COALESCE(EXCLUDED.target_handle, auto_config.target_handle),
                content_type = COALESCE(EXCLUDED.content_type, auto_config.content_type),
                poll_interval_sec = COALESCE(EXCLUDED.poll_interval_sec, auto_config.poll_interval_sec),
                media_only = COALESCE(EXCLUDED.media_only, auto_config.media_only),
                include_reposts = COALESCE(EXCLUDED.include_reposts, auto_config.include_reposts),
                max_posts_per_run = COALESCE(EXCLUDED.max_posts_per_run, auto_config.max_posts_per_run),
                bluesky_handle = COALESCE(EXCLUDED.bluesky_handle, auto_config.bluesky_handle),
                bluesky_app_password = COALESCE(EXCLUDED.bluesky_app_password, auto_config.bluesky_app_password),
                last_run_at = COALESCE(EXCLUDED.last_run_at, auto_config.last_run_at),
                last_error = EXCLUDED.last_error,
                last_result = EXCLUDED.last_result,
                updated_at = CURRENT_TIMESTAMP
        ''', (
            cfg.get('name', 'default'),
            bool(cfg.get('enabled', False)),
            cfg.get('source_handle'),
            cfg.get('target_handle'),
            cfg.get('content_type', 'feed'),
            int(cfg.get('poll_interval_sec') or 300),
            bool(cfg.get('media_only', True)),
            bool(cfg.get('include_reposts', False)),
            int(cfg.get('max_posts_per_run') or 2),
            cfg.get('bluesky_handle'),
            cfg.get('bluesky_app_password'),
            cfg.get('last_run_at'),
            cfg.get('last_error'),
            cfg.get('last_result'),
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"save auto_config: {e}")
        traceback.print_exc()
        return False


def _auto_seen(uri, config_name='default'):
    try:
        conn = get_db_connection()
        if not conn:
            return True
        cur = conn.cursor()
        cur.execute("SELECT id FROM auto_seen WHERE config_name=%s AND uri=%s", (config_name, uri))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return exists
    except Exception:
        return True


def _auto_mark_seen(uri, posted=False, config_name='default'):
    try:
        conn = get_db_connection()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO auto_seen (config_name, uri, posted)
            VALUES (%s, %s, %s)
            ON CONFLICT (config_name, uri) DO UPDATE SET posted = EXCLUDED.posted
        ''', (config_name, uri, posted))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"auto_mark_seen: {e}")


def _get_bluesky_client_for_auto(cfg):
    for sid, s in sessions.items():
        if s.get('client'):
            return s['client'], sid

    login_handle = cfg.get('bluesky_handle')
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            row = None
            if login_handle:
                cur.execute('''
                    SELECT session_id, session_string, handle FROM sessions
                    WHERE handle = %s AND expires_at > CURRENT_TIMESTAMP
                    ORDER BY last_used_at DESC LIMIT 1
                ''', (login_handle,))
                row = cur.fetchone()
            if not row:
                cur.execute('''
                    SELECT session_id, session_string, handle FROM sessions
                    WHERE expires_at > CURRENT_TIMESTAMP
                    ORDER BY last_used_at DESC LIMIT 1
                ''')
                row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                client = Client()
                client.login(session_string=row[1])
                sid = row[0]
                sessions[sid] = {
                    'client': client,
                    'handle': row[2],
                    'session_string': row[1]
                }
                print(f"✅ Auto restored Bluesky session for @{row[2]}")
                return client, sid
    except Exception as e:
        print(f"auto restore session: {e}")

    bsky_user = cfg.get('bluesky_handle')
    bsky_pass = cfg.get('bluesky_app_password')
    if bsky_user and bsky_pass:
        result = tool_login(bsky_user, bsky_pass)
        if result.get('success'):
            sid = result['session_id']
            return sessions[sid]['client'], sid

    return None, None


def run_auto_once(name='default'):
    """One cycle: fetch Bluesky → vault → post to Bluesky."""
    cfg = _load_auto_config(name)
    if not cfg:
        return {"success": False, "error": "No auto config. Set it up first."}
    if not cfg.get('enabled'):
        return {"success": False, "error": "Auto pilot is disabled", "skipped": True}

    source = cfg.get('source_handle')
    if not source:
        return {"success": False, "error": "source_handle not set"}

    client, session_id = _get_bluesky_client_for_auto(cfg)
    if not client or not session_id:
        msg = "No Bluesky session. Login once in chat, or set bluesky_handle + app password in auto config."
        _save_auto_config({**cfg, 'last_error': msg, 'last_run_at': datetime.now()})
        return {"success": False, "error": msg}

    try:
        fetch = tool_fetch_posts(
            session_id=session_id,
            actor=source,
            limit=max(5, int(cfg.get('max_posts_per_run') or 2) * 3),
            include_reposts=bool(cfg.get('include_reposts')),
            media_only=bool(cfg.get('media_only', True))
        )
        if not fetch.get('success'):
            _save_auto_config({**cfg, 'last_error': fetch.get('error'), 'last_run_at': datetime.now()})
            return fetch

        posts = fetch.get('posts') or []
        new_posts = []
        for p in posts:
            uri = p.get('uri')
            if not uri or _auto_seen(uri, name):
                continue
            new_posts.append(p)
            if len(new_posts) >= int(cfg.get('max_posts_per_run') or 2):
                break

        if not new_posts:
            result_msg = f"No new posts from @{source}"
            _save_auto_config({**cfg, 'last_error': None, 'last_result': result_msg, 'last_run_at': datetime.now()})
            return {"success": True, "posted_count": 0, "message": result_msg}

        tool_add_to_vault(new_posts, handler_handle=source)

        posted = 0
        errors = []
        for p in new_posts:
            r = tool_post_now(
                session_id=session_id,
                uri=p.get('uri')
            )
            _auto_mark_seen(p.get('uri'), posted=bool(r.get('success')), config_name=name)
            if r.get('success'):
                posted += 1
            else:
                errors.append(r.get('error') or r.get('message') or 'failed')
            time.sleep(2)

        result_msg = f"Posted {posted}/{len(new_posts)} to Bluesky from @{source}"
        if errors:
            result_msg += f" · errors: {'; '.join(errors[:3])}"
        _save_auto_config({
            **cfg,
            'last_error': None if posted else (errors[0] if errors else None),
            'last_result': result_msg,
            'last_run_at': datetime.now()
        })
        return {"success": True, "posted_count": posted, "message": result_msg, "errors": errors}

    except Exception as e:
        traceback.print_exc()
        _save_auto_config({**cfg, 'last_error': str(e), 'last_run_at': datetime.now()})
        return {"success": False, "error": str(e)}


def _auto_loop():
    print("🤖 Auto pilot loop started (Bluesky destination)")
    while not _auto_stop.is_set():
        try:
            configs = [c for c in _list_auto_configs() if c.get('enabled')]
            for cfg in configs:
                name = cfg.get('name') or 'default'
                interval = int(cfg.get('poll_interval_sec') or 300)
                last = cfg.get('last_run_at')
                should_run = True
                if last:
                    try:
                        if isinstance(last, str):
                            last_dt = datetime.fromisoformat(last)
                        else:
                            last_dt = last
                        if last_dt.tzinfo is None:
                            delta = (datetime.now() - last_dt).total_seconds()
                        else:
                            delta = (datetime.now(last_dt.tzinfo) - last_dt).total_seconds()
                        should_run = delta >= interval
                    except Exception:
                        should_run = True
                if should_run:
                    print(f"🤖 Auto run: {name}")
                    run_auto_once(name)
        except Exception as e:
            print(f"auto loop: {e}")
        _auto_stop.wait(30)


def start_auto_pilot():
    global _auto_thread
    if _auto_thread and _auto_thread.is_alive():
        return {"success": True, "message": "Auto pilot already running", "running": True}
    _auto_stop.clear()
    _auto_thread = threading.Thread(target=_auto_loop, daemon=True)
    _auto_thread.start()
    return {"success": True, "message": "Auto pilot started (→ Bluesky)", "running": True}


def stop_auto_pilot():
    _auto_stop.set()
    return {"success": True, "message": "Auto pilot stop signal sent", "running": False}


def tool_auto_status():
    configs = _list_auto_configs()
    running = _auto_thread is not None and _auto_thread.is_alive() and not _auto_stop.is_set()
    pipelines = []
    for c in configs:
        pipelines.append({
            "name": c.get('name'),
            "enabled": c.get('enabled'),
            "source_handle": c.get('source_handle'),
            "target_handle": c.get('target_handle'),
            "poll_interval_sec": c.get('poll_interval_sec'),
            "max_posts_per_run": c.get('max_posts_per_run'),
            "last_run_at": str(c.get('last_run_at')) if c.get('last_run_at') else None,
            "last_error": c.get('last_error'),
            "last_result": c.get('last_result'),
        })
    return {
        "success": True,
        "running": running,
        "pipelines": pipelines,
        "destination": "bluesky",
        "message": f"Auto {'ON' if running else 'OFF'} · {len([p for p in pipelines if p['enabled']])} enabled · destination=Bluesky"
    }


def tool_auto_start():
    configs = _list_auto_configs()
    for c in configs:
        if c.get('source_handle') and c.get('target_handle'):
            _save_auto_config({**c, 'enabled': True})
    return start_auto_pilot()


def tool_auto_stop():
    configs = _list_auto_configs()
    for c in configs:
        _save_auto_config({**c, 'enabled': False})
    return stop_auto_pilot()


def tool_auto_run_now(name='default'):
    return run_auto_once(name)


def tool_auto_setup(name, source_handle, target_handle=None,
                    poll_interval_sec=300, max_posts_per_run=2, media_only=True,
                    bluesky_handle=None, bluesky_app_password=None):
    cfg = {
        'name': name or 'default',
        'enabled': True,
        'source_handle': source_handle.lstrip('@') if source_handle else None,
        'target_handle': target_handle.lstrip('@') if target_handle else None,
        'poll_interval_sec': int(poll_interval_sec or 300),
        'max_posts_per_run': int(max_posts_per_run or 2),
        'media_only': bool(media_only),
        'content_type': 'feed',
        'bluesky_handle': bluesky_handle,
        'bluesky_app_password': bluesky_app_password,
    }
    ok = _save_auto_config(cfg)
    if ok:
        start_auto_pilot()
        return {
            "success": True,
            "message": f"Pipeline '{cfg['name']}' set: @{cfg['source_handle']} → @{cfg['target_handle'] or 'same account'} every {cfg['poll_interval_sec']}s"
        }
    return {"success": False, "error": "Failed to save config"}


def tool_auto_remove(name):
    try:
        conn = get_db_connection()
        if not conn:
            return {"success": False, "error": "DB unavailable"}
        cur = conn.cursor()
        cur.execute("DELETE FROM auto_config WHERE name = %s", (name,))
        cur.execute("DELETE FROM auto_seen WHERE config_name = %s", (name,))
        conn.commit()
        cur.close()
        conn.close()
        return {"success": True, "message": f"Removed pipeline {name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}












# ============================================================
# GEMINI + CHAT
# ============================================================

def call_gemini(messages, tools=None, model=None):
    """Call Gemini API with automatic model fallback on errors"""
    
    # If no model specified, get next model
    if model is None:
        model = next_gemini_model()
    
    # Check if model is on cooldown
    if model in _gemini_model_cooldown:
        cooldown_until = _gemini_model_cooldown[model]
        if datetime.now() < cooldown_until:
            print(f"⏳ Model {model} on cooldown, trying next model...")
            next_model = next_gemini_model()
            if next_model != model:
                return call_gemini(messages, tools, next_model)
            return None, f"All models on cooldown"
    
    # Get API key
    key = next_gemini_key()
    if not key:
        return None, "No Gemini API keys"
    
    print(f"🔑 Using Gemini key: {key[:12]}... with model: {model}")
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        print(f"📥 Gemini response status: {r.status_code} (model: {model})")
        
        # Handle rate limit - try next model
        if r.status_code == 429:
            print(f"⚠️ Rate limit hit for model {model}")
            handle_model_rate_limit(model)
            
            # Try next model
            next_model = next_gemini_model()
            if next_model != model:
                print(f"🔄 Switching to next model: {next_model}")
                return call_gemini(messages, tools, next_model)
            return None, f"Rate limit exceeded - all models exhausted"
        
        # Handle other errors - try next model
        if r.status_code != 200:
            print(f"❌ Gemini error with model {model}: {r.text[:200]}")
            
            # Try next model for non-200 errors (except 400 which is usually bad request)
            if r.status_code != 400:
                next_model = next_gemini_model()
                if next_model != model:
                    print(f"🔄 Switching to next model: {next_model}")
                    return call_gemini(messages, tools, next_model)
            
            return None, f"Gemini {r.status_code} with {model}: {r.text[:300]}"
        
        # Success! Reset model cooldown
        if model in _gemini_model_cooldown:
            del _gemini_model_cooldown[model]
        
        return r.json(), None
        
    except Exception as e:
        print(f"❌ Gemini exception with {model}: {e}")
        # Try next model on exception
        next_model = next_gemini_model()
        if next_model != model:
            print(f"🔄 Switching to next model on exception: {next_model}")
            return call_gemini(messages, tools, next_model)
        return None, str(e)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "login",
            "description": "Login to Bluesky with handle and app password. Reuses existing session if already logged in.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Bluesky handle or email"},
                    "password": {"type": "string", "description": "App password"}
                },
                "required": ["username", "password"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "logout",
            "description": "Logout from a Bluesky session. Use 'all': true to logout all sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string", "description": "Handle to logout"},
                    "all": {"type": "boolean", "description": "Logout all sessions"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_sessions",
            "description": "List all active Bluesky sessions.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_master",
            "description": "Set the master Bluesky account used for fetching posts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string", "description": "Bluesky handle to set as master"}
                },
                "required": ["handle"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_master",
            "description": "Get the current master Bluesky account.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_posts",
            "description": "Fetch posts from a Bluesky handle using the master account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "actor": {"type": "string", "description": "Handle to fetch from"},
                    "limit": {"type": "integer", "default": 15},
                    "media_only": {"type": "boolean", "default": True},
                    "include_reposts": {"type": "boolean", "default": False}
                },
                "required": ["actor"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_vault",
            "description": "Save recently fetched posts to the vault.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_vault",
            "description": "List items in the vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                    "offset": {"type": "integer", "default": 0}
                }
            }
        }
    },
    # ===== VAULT MANAGEMENT TOOLS =====
    {
        "type": "function",
        "function": {
            "name": "list_vault_by_status",
            "description": "List vault items filtered by post status. Use 'unposted' for items not yet posted, 'posted' for already posted, 'scheduled' for scheduled, or 'all' for everything.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["unposted", "posted", "scheduled", "all"],
                        "description": "Filter by post status"
                    },
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_vault_items",
            "description": "PERMANENTLY delete vault items by status or all. Use with caution! This cannot be undone. ALWAYS confirm with the user before deleting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["unposted", "posted", "scheduled", "all"],
                        "description": "Delete items by status"
                    },
                    "ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of vault IDs to delete"
                    },
                    "all": {
                        "type": "boolean",
                        "description": "Delete ALL vault items (requires confirmation)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "post_unposted",
            "description": "Post all unposted vault items to Bluesky immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID to post with"},
                    "target_handle": {"type": "string", "description": "Target handle to post to (optional)"},
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Max number of items to post"
                    }
                }
            }
        }
    },
    # ===== END VAULT MANAGEMENT TOOLS =====
    {
        "type": "function",
        "function": {
            "name": "post_to_accounts",
            "description": "Post a vault item to multiple Bluesky accounts by handle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vault_id": {"type": "integer", "description": "Vault item ID to post"},
                    "uri": {"type": "string", "description": "Vault item URI (alternative to vault_id)"},
                    "caption": {"type": "string", "description": "Custom caption (optional)"},
                    "account_handles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of Bluesky handles to post to"
                    }
                },
                "required": ["account_handles"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "broadcast",
            "description": "Post a vault item to ALL connected Bluesky accounts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vault_id": {"type": "integer", "description": "Vault item ID to post"},
                    "uri": {"type": "string", "description": "Vault item URI (alternative to vault_id)"},
                    "caption": {"type": "string", "description": "Custom caption (optional)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "post_now",
            "description": "Post a vault item to Bluesky using the current session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vault_id": {"type": "integer", "description": "Vault item ID to post"},
                    "uri": {"type": "string", "description": "Vault item URI (alternative to vault_id)"},
                    "caption": {"type": "string", "description": "Custom caption (optional)"},
                    "target_handle": {"type": "string", "description": "Target handle (optional)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_accounts",
            "description": "List all active Bluesky accounts.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_status",
            "description": "Get overall system status including vault counts and sessions.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_scheduled",
            "description": "List pending scheduled posts.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_setup",
            "description": "Configure auto-pilot pipeline. Watch a source handle and cross-post to target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Pipeline name (unique)"},
                    "source_handle": {"type": "string", "description": "Bluesky handle to watch"},
                    "target_handle": {"type": "string", "description": "Bluesky handle to post to"},
                    "poll_interval_sec": {"type": "integer", "default": 300},
                    "max_posts_per_run": {"type": "integer", "default": 2},
                    "media_only": {"type": "boolean", "default": True},
                    "include_reposts": {"type": "boolean", "default": False}
                },
                "required": ["source_handle"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_start",
            "description": "Start the auto-pilot.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_stop",
            "description": "Stop the auto-pilot.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_status",
            "description": "Get auto-pilot status and list all pipelines.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_run_now",
            "description": "Run one auto-pilot cycle immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Pipeline name to run"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_remove",
            "description": "PERMANENTLY DELETE an auto-pilot pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Pipeline name to delete"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "help",
            "description": "Get help on available commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Optional topic to get help on"}
                }
            }
        }
    }
]


def execute_tool(name, args, session_id=None):
    args = args or {}
    try:
        if name == 'login':
            return tool_login(args.get('username'), args.get('password'))
        
        if name == 'logout':
            if args.get('all'):
                return logout_all_sessions()
            handle = args.get('handle')
            if handle:
                return logout_session(handle)
            if session_id:
                return logout_session(session_id)
            return {"success": False, "error": "No session specified"}
        
        if name == 'list_sessions':
            if not sessions:
                return {"success": True, "sessions": [], "message": "No active sessions"}
            session_list = []
            master_sid, _ = get_master_session()
            for sid, s in sessions.items():
                session_list.append({
                    "session_id": sid,
                    "handle": s.get('handle'),
                    "display_name": s.get('display_name'),
                    "created_at": s.get('created_at'),
                    "is_master": sid == master_sid
                })
            return {
                "success": True,
                "sessions": session_list,
                "count": len(session_list),
                "master_session_id": master_sid,
                "message": f"Active sessions: {len(session_list)}"
            }
        
        if name == 'set_master':
            handle = args.get('handle')
            if not handle:
                return {"success": False, "error": "No handle specified"}
            return set_master_account(handle)
        
        if name == 'get_master':
            master_sid, master_s = get_master_session()
            if master_s:
                return {
                    "success": True,
                    "handle": master_s.get('handle'),
                    "display_name": master_s.get('display_name'),
                    "session_id": master_sid
                }
            return {"success": False, "error": "No master account set"}
        
        if name == 'fetch_posts':
            if not session_id:
                return {"success": False, "error": "Login first"}
            return tool_fetch_posts(
                session_id,
                args.get('actor'),
                limit=int(args.get('limit') or 15),
                media_only=bool(args.get('media_only', True)),
                include_reposts=bool(args.get('include_reposts', False))
            )
        
        if name == 'add_to_vault':
            posts = []
            if session_id and session_id in sessions:
                posts = sessions[session_id].get('_last_fetched') or []
            return tool_add_to_vault(posts, handler_handle=sessions.get(session_id, {}).get('_last_actor'))
        
        if name == 'list_vault':
            return tool_list_vault(
                limit=int(args.get('limit') or 15),
                offset=int(args.get('offset') or 0)
            )
        
        # ===== NEW VAULT MANAGEMENT TOOLS =====
        if name == 'list_vault_by_status':
            return tool_list_vault_by_status(
                status=args.get('status', 'all'),
                limit=int(args.get('limit', 50)),
                offset=int(args.get('offset', 0))
            )
        
        if name == 'delete_vault_items':
            # Require confirmation for "delete all"
            if args.get('all'):
                confirm = args.get('confirm')
                if confirm != 'YES_DELETE_ALL':
                    return {
                        "success": False, 
                        "error": "Confirmation required",
                        "message": "⚠️ This will permanently delete ALL vault items. Reply with 'YES_DELETE_ALL' to confirm.",
                        "requires_confirmation": True,
                        "confirmation_code": "YES_DELETE_ALL"
                    }
            return tool_delete_vault_items(
                ids=args.get('ids'),
                status=args.get('status'),
                all=args.get('all', False)
            )
        
        if name == 'post_unposted':
            return tool_post_unposted(
                session_id=session_id or args.get('session_id'),
                target_handle=args.get('target_handle'),
                limit=int(args.get('limit', 10))
            )
        # ===== END NEW VAULT MANAGEMENT TOOLS =====
        
        if name == 'post_to_accounts':
            posting_handles = args.get('account_handles', [])
            if not posting_handles:
                return {"success": False, "error": "No account handles specified"}
            return tool_post_now(
                session_id=None,
                vault_id=args.get('vault_id'),
                uri=args.get('uri'),
                caption=args.get('caption'),
                posting_accounts=posting_handles
            )
        
        if name == 'broadcast':
            all_sessions = list(sessions.keys())
            if not all_sessions:
                return {"success": False, "error": "No active sessions"}
            return tool_post_now(
                session_id=None,
                vault_id=args.get('vault_id'),
                uri=args.get('uri'),
                caption=args.get('caption'),
                session_ids=all_sessions
            )
        
        if name == 'post_now':
            return tool_post_now(
                session_id=session_id,
                vault_id=args.get('vault_id'),
                uri=args.get('uri'),
                caption=args.get('caption'),
                target_handle=args.get('target_handle')
            )
        
        if name == 'list_accounts':
            return tool_list_accounts('bluesky')
        
        if name == 'get_status':
            return tool_get_status(session_id)
        
        if name == 'list_scheduled':
            return tool_list_scheduled()
        
        if name == 'auto_setup':
            return tool_auto_setup(
                name=args.get('name') or 'default',
                source_handle=args.get('source_handle'),
                target_handle=args.get('target_handle'),
                poll_interval_sec=args.get('poll_interval_sec') or 300,
                max_posts_per_run=args.get('max_posts_per_run') or 2,
                media_only=bool(args.get('media_only', True)),
                bluesky_handle=args.get('bluesky_handle'),
                bluesky_app_password=args.get('bluesky_app_password')
            )
        
        if name == 'auto_start':
            return tool_auto_start()
        
        if name == 'auto_stop':
            return tool_auto_stop()
        
        if name == 'auto_status':
            return tool_auto_status()
        
        if name == 'auto_run_now':
            return tool_auto_run_now(args.get('name') or 'default')
        
        if name == 'auto_remove':
            name = args.get('name')
            if not name:
                return {"success": False, "error": "No pipeline name specified"}
            return tool_auto_remove(name)
        
        if name == 'help':
            return {"success": True, "message": """Available commands:
            
🔐 AUTHENTICATION:
  login - Login to Bluesky
  logout - Logout from a session
  list_sessions - List all active sessions

👑 MASTER ACCOUNT:
  set_master - Set the master account for fetching
  get_master - Get the current master account

📥 FETCHING:
  fetch_posts - Fetch posts from a Bluesky handle
  add_to_vault - Save fetched posts to vault

📦 VAULT MANAGEMENT:
  list_vault - List items in the vault
  list_vault_by_status - List vault items by status (unposted/posted/scheduled/all)
  delete_vault_items - Permanently delete vault items
  post_unposted - Post all unposted vault items

📤 POSTING:
  post_now - Post a vault item
  post_to_accounts - Post to multiple accounts
  broadcast - Post to ALL accounts

🤖 AUTO PILOT:
  auto_setup - Configure auto-pilot pipeline
  auto_start - Start auto-pilot
  auto_stop - Stop auto-pilot
  auto_status - Get auto-pilot status
  auto_run_now - Run auto-pilot once
  auto_remove - Remove a pipeline

📊 STATUS:
  list_accounts - List all accounts
  get_status - Get system status
  list_scheduled - List scheduled posts
  help - Show this help message"""}
        
        return {"success": False, "error": f"Unknown tool {name}"}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}


SYSTEM_PROMPT = """You are the AI assistant for Bluesky AI Vault → Bluesky - a social media automation tool.

===========================================
CORE FUNCTIONALITY:
===========================================
- Source: Bluesky (fetch posts)
- Destination: Bluesky ONLY (via AT Protocol)
- Facebook, Instagram, Threads, TikTok are NOT supported
- Timezone: Africa/Nairobi

===========================================
LOCAL MEMORY FEATURES - I CAN REMEMBER:
===========================================
I have a local memory system that learns about you to provide a personalized experience:

1. **Preferred Account**: I remember which Bluesky account you prefer to post to
2. **Posting Patterns**: I learn from your posting history (frequency, content types)
3. **Common Topics**: I track what you're interested in
4. **Conversation History**: I remember recent conversations for context
5. **Last Used Account**: I remember which account you used most recently

You can ask me:
- "What do you know about me?" - See what I remember
- "Forget everything" - Clear my memory
- "Remember @handle" - Set a preferred account
- "What's my preferred account?" - Check your current preference

I will automatically use your preferred account when posting, so you don't have to specify it every time!

===========================================
MULTIPLE ACCOUNTS FLOW WITH MEMORY:
===========================================
When the user wants to POST something:

STEP 1: Check if the user specified an account:
- "post id 5 to @account1" → use account_handle="account1"
- "post id 5 to @account1, @account2" → use multiple accounts

STEP 2: If NO account was specified:
- Check if user has a PREFERRED ACCOUNT saved in memory
- If YES → "Using your preferred account: @[account]" (do NOT ask!)
- If NO → Call list_accounts() to see how many exist
  - If ONLY 1 account → use it automatically, mention: "Posting to @[account_name]"
  - If MULTIPLE accounts → ASK: "You have [N] Bluesky accounts: [list]. Which one?"

STEP 3: After user chooses, REMEMBER the choice for next time

STEP 4: Wait for the user's response before posting.

===========================================
VAULT MANAGEMENT COMMANDS:
===========================================
- "list unposted" or "show unposted" → list_vault_by_status(status="unposted")
- "list posted" or "show posted" → list_vault_by_status(status="posted")
- "list scheduled" or "show scheduled" → list_vault_by_status(status="scheduled")
- "list all vault" or "show all vault" → list_vault_by_status(status="all")
- "post unposted" → post_unposted() (uses preferred account if set)
- "post count 5" → post_unposted(limit=5)
- "delete unposted" → delete_vault_items(status="unposted") (needs confirmation)
- "delete posted" → delete_vault_items(status="posted") (needs confirmation)
- "delete scheduled" → delete_vault_items(status="scheduled") (needs confirmation)
- "delete all vault" → delete_vault_items(all=True) (⚠️ Requires: YES_DELETE_ALL)
- "delete vault id 1,2,3" → delete_vault_items(ids=[1,2,3])
- "post id 5" → post_now(vault_id=5) (uses preferred account if set)
- "post id 5 to @account1, @account2" → post_to_accounts(vault_id=5, account_handles=["account1", "account2"])
- "broadcast id 5" → broadcast(vault_id=5) (posts to ALL accounts)
- "post 3 from vault" → post_vault_batch(count=3) (uses preferred account if set)

When showing vault items, include status icons:
   ✅ = posted, ⏳ = scheduled, ⬜ = unposted

For posting, always mention which account(s) were used.

===========================================
CRITICAL - HANDLING TOOL RESPONSES:
===========================================
When a tool returns a response, you MUST check for these special flags:

1. **"needs_account": True** - User has multiple Bluesky accounts
   → Check if user has a preferred account saved
   → If YES: "Using your preferred account: @[account]" and post
   → If NO: "You have [N] accounts: [names]. Which one?"
   → After user chooses, REMEMBER it!

2. **"requires_confirmation": True** - Action needs user confirmation
   → You MUST re-prompt the user with the confirmation question
   → Example: "Reply with YES_DELETE_ALL to confirm"

3. **"confirmation_code": "YES_DELETE_ALL"** - User must reply with exact code
   → Tell the user: "Reply with YES_DELETE_ALL to confirm"

===========================================
MASTER ACCOUNT MANAGEMENT:
===========================================
The master account is used for fetching posts from Bluesky.

- "set master @handle" → Set the master account for fetching
- "who is master" → Show the current master account
- "list sessions" → Show all active sessions
- "logout @handle" → Logout a specific session
- "logout all" → Logout ALL sessions

===========================================
SESSION MANAGEMENT:
===========================================
- Sessions are automatically saved to the database
- They persist across server restarts
- You can have multiple accounts logged in simultaneously
- Each session is identified by a unique session_id

===========================================
REPLY STYLE (CRITICAL):
===========================================
- NEVER paste raw JSON, tool dumps, or {"success":...} into your reply
- ALWAYS summarize tool results in short plain English
- For list_accounts: say the usernames only, not the full JSON
- For confirmation: clearly tell the user what to reply
- For multiple accounts: list them clearly and ask which one
- For memory: confirm when you remember something (e.g., "✅ I'll remember @handle for future posts")
- Be friendly, concise, and helpful
- Use emojis sparingly to make responses more readable

===========================================
EXAMPLE CONVERSATIONS WITH MEMORY:
===========================================
User: "post id 5"
(First time - no preferred account, 2 accounts exist)
You: "You have 2 Bluesky accounts: @account1 and @account2. Which one do you want to post to?"

User: "account1"
You: "✅ Done — posted to Bluesky (@account1). 
I'll remember @account1 as your preferred account for future posts."

User: "post id 6"
(Now has preferred account)
You: "✅ Done — posted to Bluesky (@account1) using your preferred account."

User: "what do you know about me?"
You: "📌 Context about you:
• User's preferred account: @account1
• User has posted 3 times this session
• Last action: post"

User: "forget everything"
You: "🧹 I've cleared all memories about you. I'll start fresh!"

User: "remember @account2"
You: "✅ I'll remember @account2 as your preferred account for future posts."

===========================================
AUTONOMY (pipelines):
===========================================
- Each Bluesky source is its own pipeline with a unique name
- auto_status lists ALL pipelines
- auto_remove(name="scorpio") permanently deletes that pipeline
- "Stop auto" / "stop pipeline X" → auto_stop (disables, keeps config)
- "Remove pipeline X" / "delete pipeline scorpio" → auto_remove (deletes forever)

===========================================
ADDING A NEW PIPELINE:
===========================================
- If user says "add a pipeline" WITHOUT full details → Ask clarifying questions
- Minimum required: source_handle (Bluesky handle to watch)
- Optional: target_handle (Bluesky handle to post to, defaults to source)
- Defaults: poll_interval_sec=300, max_posts_per_run=1, media_only=true
- As soon as source_handle is known, call auto_setup once

===========================================
SCHEDULING:
===========================================
- schedule_bulk(count=N, period="week")
- Prefer count to take the latest N posts
- Always ask which account when multiple accounts exist (unless preferred account is set)

===========================================
OTHER COMMANDS:
===========================================
- "status" → get_status
- "list accounts" → list_accounts()
- "list sessions" → list_sessions()
- "login with handle and app-password" → login()
- "fetch 10 posts from @handle" → fetch_posts()
- "save them to vault" → add_to_vault()
- "list scheduled" → list_scheduled()
- "help" → Show available commands

===========================================
MEMORY MANAGEMENT COMMANDS:
===========================================
- "what do you know about me" → Shows all saved preferences
- "forget everything" → Clears all memory
- "remember @handle" → Sets preferred account
- "what's my preferred account" → Shows current preference

===========================================
REMEMBER:
===========================================
- Timezone is Africa/Nairobi
- Only Bluesky posting is supported
- Always check for preferred account before asking which account
- Always confirm destructive actions
- Be concise and helpful
- Learn from interactions - remember user preferences
- NEVER invent success - report tool results honestly
- NEVER paste raw JSON in your reply

===========================================
YOUR PERSONALITY:
===========================================
- You are helpful, friendly, and efficient
- You remember user preferences to make interactions smoother
- You proactively suggest actions based on context
- You explain what you're doing in simple terms
- You confirm important actions before executing them
- You learn from every interaction to improve future responses

===========================================
POSTING LIMITATIONS:
===========================================
- Bluesky posts have a maximum of 300 characters
- Images are supported (up to 4 per post)
- Video is not supported yet
- You can post to multiple accounts at once using post_to_accounts or broadcast
"""

def format_tool_summary(tool_results):
    parts = []
    for tr in tool_results:
        name = tr.get('name')
        r = tr.get('result') or {}
        if not r.get('success'):
            parts.append(f"❌ {name}: {r.get('error') or r.get('message') or 'failed'}")
            continue
        if r.get('message'):
            parts.append(r['message'])
            continue
        parts.append(f"{name}: OK")
    return "\n".join(parts) if parts else "Done."


def simple_fallback(msg, session_id):
    lower = msg.lower().strip()

    if lower.startswith('login ') or 'login with' in lower:
        m = re.search(r'login(?:\s+with)?\s+([^\s]+)\s+(?:and\s+)?(.+)', msg.strip(), re.IGNORECASE)
        if m:
            username = m.group(1).strip().rstrip(',')
            password = m.group(2).strip().rstrip('.,!')
            result = tool_login(username, password)
            if result.get('success'):
                return f"✅ {result.get('message')}\nSession ID: {result.get('session_id')}"
            return f"❌ Login failed: {result.get('error')}"
        return "Format: Login with <handle> and <app-password>"

    if 'restore' in lower and ('session' in lower or '@' in lower or '.bsky' in lower):
        m = re.search(r'@?([a-zA-Z0-9._-]+\.bsky\.social|[a-zA-Z0-9._-]+)', msg)
        if m:
            result = tool_restore_session(m.group(1))
            return result.get('message') or result.get('error') or str(result)

    if any(w in lower for w in ('status', 'how many', "what's in", 'counts')):
        r = tool_get_status(session_id)
        return r.get('message', str(r)) if r.get('success') else str(r)

    if 'vault' in lower and any(w in lower for w in ('list', 'show', 'what')):
        r = tool_list_vault(limit=10)
        if not r.get('success'):
            return r.get('error', str(r))
        items = r.get('vault') or []
        if not items:
            return "Vault is empty."
        lines = [f"Vault ({r.get('count')} items):"]
        for i, it in enumerate(items, 1):
            lines.append(f"{i}. id={it.get('id')} @{it.get('author')}: {(it.get('text') or '')[:80]}")
        return "\n".join(lines)

    if 'scheduled' in lower:
        r = tool_list_scheduled()
        if not r.get('success'):
            return r.get('error', str(r))
        items = r.get('scheduled') or []
        if not items:
            return "No pending scheduled posts."
        lines = [f"Scheduled ({r.get('count')}):"]
        for it in items:
            lines.append(f"• {(it.get('text') or '')[:60]}")
        return "\n".join(lines)

    if 'account' in lower or 'sessions' in lower:
        r = tool_list_accounts('bluesky')
        if not r.get('success'):
            return r.get('error', str(r))
        accs = r.get('accounts') or []
        if not accs:
            return "No active Bluesky sessions. Login first."
        return "Bluesky accounts:\n" + "\n".join(
            f"• @{a.get('label')}{' 👑 MASTER' if a.get('is_master') else ''}" for a in accs
        )

    if 'fetch' in lower:
        m = re.search(r'@?([a-zA-Z0-9._-]+\.bsky\.social|[a-zA-Z0-9._-]+)', msg)
        limit_m = re.search(r'(\d+)\s*posts?', lower)
        limit = int(limit_m.group(1)) if limit_m else 15
        if not session_id:
            return "Not logged in. Say: Login with <handle> and <app-password>"
        if not m:
            return "Say: Fetch 15 posts from @handle"
        actor = m.group(1)
        if '.' not in actor:
            actor = actor + '.bsky.social'
        r = tool_fetch_posts(session_id, actor, limit=limit)
        if not r.get('success'):
            return f"❌ {r.get('error')}"
        posts = r.get('posts') or []
        lines = [f"Fetched {len(posts)} posts from @{actor}:"]
        for i, p in enumerate(posts[:8], 1):
            media = f" [{len(p.get('images') or [])} img]" if p.get('images') else ""
            lines.append(f"{i}. {(p.get('text') or '')[:70]}{media}")
        if len(posts) > 8:
            lines.append(f"...and {len(posts)-8} more")
        lines.append("\nSay “save them to vault” to store them.")
        if session_id in sessions:
            sessions[session_id]['_last_fetched'] = posts
            sessions[session_id]['_last_actor'] = actor
        return "\n".join(lines)

    if any(w in lower for w in ('save', 'add to vault', 'vault them')):
        if not session_id or session_id not in sessions:
            return "Not logged in / no recent fetch. Fetch posts first."
        posts = sessions[session_id].get('_last_fetched') or []
        if not posts:
            return "No recent fetch to save. Fetch posts first."
        actor = sessions[session_id].get('_last_actor')
        r = tool_add_to_vault(posts, handler_handle=actor)
        return r.get('message') or r.get('error') or str(r)

    id_m = re.search(r'post\s+(?:id\s+)?(\d+)', lower)
    if id_m or re.search(r'\bid\s*(\d+)\b', lower):
        vid = int(id_m.group(1) if id_m else re.search(r'\bid\s*(\d+)\b', lower).group(1))
        if not session_id:
            return "Not logged in. Login first."
        result = tool_post_now(session_id, vault_id=vid)
        return result.get('message') or result.get('error') or str(result)

    # Multi-account posting
    multi_match = re.search(r'post\s+(?:id\s+)?(\d+)\s+to\s+([@a-zA-Z0-9._-]+(?:\s*,\s*[@a-zA-Z0-9._-]+)*)', lower)
    if multi_match:
        vid = int(multi_match.group(1))
        handles_raw = multi_match.group(2)
        handles = [h.strip().lstrip('@') for h in handles_raw.split(',') if h.strip()]
        session_ids = get_sessions_by_handles(handles)
        if not session_ids:
            return f"❌ No active sessions found for: {', '.join(handles)}"
        result = tool_post_now(
            session_id=None,
            vault_id=vid,
            session_ids=session_ids
        )
        return result.get('message') or result.get('error') or str(result)

    if re.search(r'post\s+(?:id\s+)?(\d+)\s+to\s+all', lower):
        match = re.search(r'post\s+(?:id\s+)?(\d+)\s+to\s+all', lower)
        if match:
            vid = int(match.group(1))
            session_ids = get_all_session_ids()
            if not session_ids:
                return "❌ No active sessions found. Login first."
            result = tool_post_now(
                session_id=None,
                vault_id=vid,
                session_ids=session_ids
            )
            return result.get('message') or result.get('error') or str(result)

    if re.search(r'broadcast\s+(?:id\s+)?(\d+)', lower):
        match = re.search(r'broadcast\s+(?:id\s+)?(\d+)', lower)
        if match:
            vid = int(match.group(1))
            session_ids = get_all_session_ids()
            if not session_ids:
                return "❌ No active sessions found. Login first."
            result = tool_post_now(
                session_id=None,
                vault_id=vid,
                session_ids=session_ids
            )
            return result.get('message') or result.get('error') or str(result)

    if 'set master' in lower:
        m = re.search(r'set master\s+@?([a-zA-Z0-9._-]+)', lower)
        if m:
            result = set_master_account(m.group(1))
            return result.get('message') or result.get('error') or str(result)
        return "Say: Set master @handle.bsky.social"

    if 'who is master' in lower or 'get master' in lower:
        master_sid, master_s = get_master_session()
        if master_s:
            return f"👑 Master account: @{master_s.get('handle')}"
        return "No master account set. Use: Set master @handle.bsky.social"

    if any(w in lower for w in ('remove pipeline', 'delete pipeline', 'remove auto', 'delete auto')):
        m = re.search(r'(?:remove|delete)\s+(?:pipeline|auto)\s+([a-zA-Z0-9._-]+)', msg, re.I)
        if m:
            return tool_auto_remove(m.group(1)).get('message') or str(tool_auto_remove(m.group(1)))
        return "Say: Remove pipeline <name>"




    # ===== AUTO PILOT COMMANDS =====
    # Check pipelines / list pipelines
    if any(w in lower for w in ('check pipelines', 'list pipelines', 'show pipelines', 'pipelines', 'pipeline status')):
        r = tool_auto_status()
        if r.get('success'):
            pipelines = r.get('pipelines', [])
            if not pipelines:
                return "📋 No pipelines configured. Use: Auto setup watch @source post to @target"
            msg = f"🤖 Auto pilot: {'🟢 ON' if r.get('running') else '🔴 OFF'}\n"
            msg += f"📋 Pipelines ({len(pipelines)}):\n"
            for p in pipelines:
                status = "✅ ENABLED" if p.get('enabled') else "⏸️ DISABLED"
                src = p.get('source_handle', '?')
                target = p.get('target_handle', '?')
                interval = p.get('poll_interval_sec', 300)
                last = p.get('last_result', 'Never run')
                msg += f"  • {p.get('name', 'default')}: @{src} → @{target} ({status}) every {interval}s"
                if last and last != 'Never run':
                    msg += f" - Last: {last[:50]}"
                msg += "\n"
            return msg
        return r.get('message', str(r))
    
    if any(w in lower for w in ('auto status', 'autopilot', 'auto pilot')):
        return tool_auto_status().get('message', str(tool_auto_status()))
    
    if any(w in lower for w in ('stop auto', 'auto stop', 'disable auto')):
        return tool_auto_stop().get('message')
    
    if any(w in lower for w in ('start auto', 'auto start', 'go autonomous')):
        return str(tool_auto_start())
    
    if 'auto run' in lower or 'run auto' in lower:
        return str(tool_auto_run_now())

    if any(w in lower for w in ('remove pipeline', 'delete pipeline', 'remove auto', 'delete auto')):
        m = re.search(r'(?:remove|delete)\s+(?:pipeline|auto)\s+([a-zA-Z0-9._-]+)', msg, re.I)
        if m:
            return tool_auto_remove(m.group(1)).get('message') or str(tool_auto_remove(m.group(1)))
        return "Say: Remove pipeline <name>"


    m = re.search(
        r'auto\s+setup.*?watch\s+@?([a-zA-Z0-9._-]+).*?(?:post\s+to|to)\s+@?([a-zA-Z0-9._-]+)',
        msg, re.I
    )
    if m or ('auto setup' in lower and 'watch' in lower):
        if m:
            return tool_auto_setup(
                name='default',
                source_handle=m.group(1),
                target_handle=m.group(2)
            ).get('message')
        return "Say: Auto setup watch @blueskyhandle post to @targethandle every 5 minutes"

    return (
        "Bluesky → Bluesky vault.\n"
        "I can: login, fetch, save to vault, post now (by id), auto pilot, status.\n"
        "Examples:\n"
        "  Login with handle and app-password\n"
        "  Set master @handle.bsky.social\n"
        "  Fetch 10 posts from @someone.bsky.social\n"
        "  Save them to vault\n"
        "  Post id 2\n"
        "  Post id 5 to @account1, @account2\n"
        "  Broadcast id 5\n"
        "  Auto setup watch zorrito post to myaccount every 5 minutes\n"
        "  Start auto / Stop auto / Auto status"
    )





@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json or {}
    message = (data.get('message') or '').strip()
    history = data.get('history') or []
    session_id = data.get('session_id')
    chat_key = data.get('chat_key') or str(uuid.uuid4())

    if not message:
        return jsonify({"success": False, "error": "Empty message"}), 400

    print(f"\n{'='*50}")
    print(f"📨 Message: {message[:50]}{'...' if len(message) > 50 else ''}")
    print(f"🔑 Gemini keys available: {len(GEMINI_API_KEYS)}")
    print(f"📊 History length: {len(history)}")

    if not GEMINI_API_KEYS:
        print("⚠️ No Gemini keys, using fallback")
        reply = simple_fallback(message, session_id)
        return jsonify({
            "success": True,
            "reply": reply,
            "tool_results": [],
            "chat_key": chat_key,
            "session_id": session_id
        })

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-10:]:
        if h.get('role') in ('user', 'assistant') and h.get('content'):
            messages.append({"role": h['role'], "content": h['content']})
    messages.append({"role": "user", "content": message})

    print(f"📤 Calling Gemini with {len(messages)} messages")
    
    # Try with model fallback - only retry once per model
    data_g, err = call_gemini(messages, tools=TOOLS_SCHEMA)
    tool_results = []

    if err or not data_g:
        print(f"❌ All Gemini models failed: {err}")
        reply = simple_fallback(message, session_id)
        return jsonify({
            "success": True,
            "reply": reply,
            "tool_results": [],
            "chat_key": chat_key,
            "session_id": session_id
        })

    try:
        choice = data_g['choices'][0]['message']
        tool_calls = choice.get('tool_calls') or []

        if tool_calls:
            print(f"🔧 Tool calls: {[tc.get('function', {}).get('name') for tc in tool_calls]}")
            messages.append(choice)
            for tc in tool_calls:
                fn = tc.get('function') or {}
                name = fn.get('name')
                try:
                    args = json.loads(fn.get('arguments') or '{}')
                    print(f"   📌 {name}({args})")
                except Exception:
                    args = {}
                result = execute_tool(name, args, session_id=session_id)
                if result.get('session_id'):
                    session_id = result['session_id']
                if name == 'fetch_posts' and result.get('success') and session_id in sessions:
                    sessions[session_id]['_last_fetched'] = result.get('posts') or []
                    sessions[session_id]['_last_actor'] = result.get('actor')
                tool_results.append({"name": name, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get('id'),
                    "content": json.dumps(result)
                })

            # Final call with tool results - try model fallback
            final_data, final_err = call_gemini(messages)
            if final_err or not final_data:
                print(f"❌ Final Gemini failed: {final_err}")
                reply = format_tool_summary(tool_results)
            else:
                reply = final_data['choices'][0]['message'].get('content') or format_tool_summary(tool_results)
                print(f"📤 Gemini final reply: {reply[:50]}...")
        else:
            reply = choice.get('content') or simple_fallback(message, session_id)
            print(f"📤 Gemini direct reply: {reply[:50]}...")

        print(f"{'='*50}\n")
        return jsonify({
            "success": True,
            "reply": reply,
            "tool_results": tool_results,
            "chat_key": chat_key,
            "session_id": session_id
        })
        
    except Exception as e:
        print(f"❌ Error processing Gemini response: {e}")
        reply = simple_fallback(message, session_id)
        return jsonify({
            "success": True,
            "reply": reply,
            "tool_results": tool_results,
            "chat_key": chat_key,
            "session_id": session_id
        })















# ============================================================
# IMAGE UPLOAD → POST / SCHEDULE / VAULT (UI)
# ============================================================

@app.route('/api/post-now/accounts', methods=['GET'])
def api_post_now_accounts():
    return jsonify(tool_list_accounts('bluesky'))


@app.route('/api/post-now', methods=['POST'])
def api_post_now_image():
    data = request.json or {}
    session_id = data.get('session_id')
    vault_id = data.get('vault_id')
    image_data = data.get('image_data') or data.get('image')
    caption = (data.get('caption') or '').strip()
    target_handle = data.get('target_handle')

    if not session_id:
        return jsonify({"success": False, "error": "No session. Login first."}), 400

    if session_id not in sessions:
        return jsonify({"success": False, "error": "Invalid session. Login again."}), 400

    if vault_id is not None and str(vault_id).strip() != '':
        try:
            vid = int(vault_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "vault_id must be an integer"}), 400
        result = tool_post_now(
            session_id=session_id,
            vault_id=vid,
            caption=caption or None,
            target_handle=target_handle
        )
        return jsonify(result), (200 if result.get('success') else 500)

    if not image_data:
        return jsonify({"success": False, "error": "Provide vault_id or image_data"}), 400

    jpeg, err = data_url_to_jpeg_bytes(image_data)
    if not jpeg:
        return jsonify({"success": False, "error": err or "Invalid image"}), 400

    client = sessions[session_id]['client']
    result = post_to_bluesky(
        client=client,
        image_bytes=jpeg,
        caption=caption or 'Posted via AI Vault',
        target_handle=target_handle
    )
    if result.get('success'):
        result['message'] = "Posted to Bluesky"
        result['caption'] = caption or 'Posted via AI Vault'
    return jsonify(result), (200 if result.get('success') else 500)


@app.route('/api/vault/add-image', methods=['POST'])
def api_vault_add_image():
    data = request.json or {}
    image_data = data.get('image_data') or data.get('image')
    caption = (data.get('caption') or '').strip() or 'Saved from AI Vault'

    if not image_data:
        return jsonify({"success": False, "error": "image_data is required"}), 400

    jpeg, err = data_url_to_jpeg_bytes(image_data)
    public_url = None
    if jpeg:
        image_entry = {
            "url": "data:image/jpeg;base64," + base64.b64encode(jpeg.getvalue()).decode('utf-8'),
            "thumb": "data:image/jpeg;base64," + base64.b64encode(jpeg.getvalue()).decode('utf-8'),
            "alt": caption[:120]
        }
    else:
        return jsonify({"success": False, "error": err or "Invalid image"}), 400

    uri = f"local:upload:{uuid.uuid4()}"

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database unavailable"}), 500
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO vault (uri, author, display_name, text, images, likes, reposts, replies, created_at, handler_handle, notes)
            VALUES (%s, %s, %s, %s, %s, 0, 0, 0, %s, %s, %s)
            RETURNING id
        ''', (
            uri,
            'upload',
            'Manual upload',
            caption,
            Json([image_entry]),
            datetime.now().isoformat(),
            'manual',
            "Uploaded via UI · platform=bluesky"
        ))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            "success": True,
            "vault_id": row[0] if row else None,
            "uri": uri,
            "message": "Image saved to vault",
            "caption": caption
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# BASIC REST
# ============================================================

@app.route('/api/status', methods=['GET'])
def api_status():
    # Auto-refresh sessions on status check
    if not sessions:
        refresh_sessions_from_db()
    return jsonify(tool_get_status(None))


@app.route('/api/accounts', methods=['GET'])
def api_accounts():
    return jsonify(tool_list_accounts('bluesky'))


@app.route('/api/auto/status', methods=['GET'])
def api_auto_status():
    return jsonify(tool_auto_status())


@app.route('/api/auto/start', methods=['POST'])
def api_auto_start():
    return jsonify(tool_auto_start())


@app.route('/api/auto/stop', methods=['POST'])
def api_auto_stop():
    return jsonify(tool_auto_stop())




# ============================================================
# SESSION AUTO-REFRESH MIDDLEWARE
# ============================================================

@app.before_request
def before_request():
    """Run before each request to ensure sessions are active."""
    # Skip for static files and health checks
    if request.path.startswith('/static/') or request.path == '/':
        return
    
    # Refresh sessions periodically (every 5 minutes)
    if not hasattr(app, '_last_session_refresh'):
        app._last_session_refresh = datetime.now()
    
    if (datetime.now() - app._last_session_refresh).seconds > 300:
        refresh_sessions_from_db()
        app._last_session_refresh = datetime.now()





@app.route('/api/sessions/refresh', methods=['POST'])
def api_refresh_sessions():
    """Force refresh sessions from database."""
    count = refresh_sessions_from_db()
    
    saved_master = load_master_handle()
    if saved_master:
        sid, session = ensure_session_active(handle=saved_master)
        if sid:
            global MASTER_SESSION_ID
            MASTER_SESSION_ID = sid
    
    return jsonify({
        "success": True,
        "restored": count,
        "total_sessions": len(sessions),
        "master_handle": load_master_handle(),
        "message": f"Refreshed {count} sessions from database"
    })







@app.route('/')
def index():
    return send_from_directory('static', 'index.html')














if __name__ == '__main__':
    # Only run when not on Vercel
    if not os.environ.get('VERCEL'):
        print("🚀 Bluesky AI Vault → Bluesky starting...")
        
        if GEMINI_API_KEYS:
            print(f"✅ Gemini keys loaded: {len(GEMINI_API_KEYS)} (round-robin)")
        else:
            print("⚠️  No GEMINI_API_KEYS — using keyword fallback only")

        # ===== REFRESH SESSIONS FROM DATABASE =====
        restored = refresh_sessions_from_db()
        if restored > 0:
            print(f"✅ Restored {restored} session(s)")
        else:
            print("ℹ️ No valid sessions to restore. Login required.")

        # ===== LOAD SAVED MASTER ACCOUNT =====
        saved_master = load_master_handle()
        if saved_master:
            found = False
            for sid, s in sessions.items():
                if s.get('handle', '').lower() == saved_master.lower():
                    MASTER_SESSION_ID = sid
                    print(f"👑 Master account loaded: @{saved_master}")
                    found = True
                    break
            if not found:
                print(f"⚠️ Saved master account @{saved_master} not found in sessions")
                print(f"   💡 Set master with: Set master @handle")
        else:
            print("ℹ️ No master account set. Use: Set master @handle")

        # ===== AUTO PILOT =====
        try:
            enabled = [c for c in _list_auto_configs() if c.get('enabled')]
            if enabled:
                start_result = start_auto_pilot()
                if start_result.get('success'):
                    print(f"🤖 Auto pilot resumed ({len(enabled)} pipeline(s) → Bluesky)")
                else:
                    print(f"🤖 Auto pilot NOT started: {start_result.get('message')}")
            else:
                print("🤖 Auto pilot idle (enable via chat)")
        except Exception as e:
            print(f"Auto pilot init: {e}")

        port = int(os.environ.get('PORT', 10000))
        app.run(debug=False, host='0.0.0.0', port=port)

# This is REQUIRED for Vercel - export the app
app = app