# Replit Worker: Slack → Transcription → Zoho Desk
from flask import Flask, request, jsonify
import requests
import json
import os
import tempfile
import logging
from datetime import datetime
import base64
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration from environment variables
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ASSEMBLYAI_API_KEY = os.getenv('ASSEMBLYAI_API_KEY')
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY', '3e43c56e7bda92b003f12bcb46ae94dcd2c1b8f4')
ZOHO_DESK_API_KEY = os.getenv('ZOHO_DESK_API_KEY')
ZOHO_DESK_ORG_ID = os.getenv('ZOHO_DESK_ORG_ID')
ZOHO_DESK_DEPARTMENT_ID = os.getenv('ZOHO_DESK_DEPARTMENT_ID')

class SlackTranscriptionWorker:
    def __init__(self):
        self.supported_audio_formats = ['.mp3', '.wav', '.m4a', '.ogg', '.flac']
        logger.info("🚀 Slack Transcription Worker initialized")
    
    def download_audio_from_slack(self, file_url, slack_token):
        """Download audio file from Slack using the file URL and token"""
        try:
            logger.info(f"📥 Downloading audio from Slack: {file_url}")
            
            headers = {
                'Authorization': f'Bearer {slack_token}'
            }
            
            response = requests.get(file_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                # Get file extension from URL or content type
                content_type = response.headers.get('content-type', '')
                if 'audio/mpeg' in content_type:
                    ext = '.mp3'
                elif 'audio/wav' in content_type:
                    ext = '.wav'
                else:
                    ext = '.mp3'  # Default
                
                # Save to temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name
                
                logger.info(f"✅ Audio downloaded successfully: {temp_file_path}")
                return temp_file_path
            else:
                logger.error(f"❌ Failed to download audio: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error downloading audio: {str(e)}")
            return None
    
    def transcribe_with_deepgram(self, audio_file_path):
        """Transcribe audio using Deepgram API"""
        try:
            logger.info("🎤 Transcribing with Deepgram...")
            
            if not DEEPGRAM_API_KEY:
                logger.error("❌ Deepgram API key not configured")
                return None
            
            with open(audio_file_path, 'rb') as audio_file:
                headers = {
                    'Authorization': f'Token {DEEPGRAM_API_KEY}',
                    'Content-Type': 'audio/mp3'
                }
                
                response = requests.post(
                    'https://api.deepgram.com/v1/listen',
                    headers=headers,
                    data=audio_file,
                    params={
                        'model': 'nova-2',
                        'language': 'en-US',
                        'punctuate': True,
                        'smart_format': True
                    },
                    timeout=60
                )
                
                if response.status_code == 200:
                    result = response.json()
                    transcript = result['results']['channels'][0]['alternatives'][0]['transcript']
                    logger.info("✅ Deepgram transcription successful")
                    return transcript.strip()
                else:
                    logger.error(f"❌ Deepgram transcription failed: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Deepgram transcription error: {str(e)}")
            return None
    
    def create_zoho_desk_ticket(self, transcript, metadata=None):
        """Create a ticket in Zoho Desk with the transcription"""
        try:
            logger.info("🎫 Creating Zoho Desk ticket...")
            
            if not all([ZOHO_DESK_API_KEY, ZOHO_DESK_ORG_ID]):
                logger.error("❌ Zoho Desk credentials not configured")
                return None
            
            # Prepare ticket data
            ticket_data = {
                'subject': f'Voice Message Transcription - {datetime.now().strftime("%Y-%m-%d %H:%M")}',
                'description': f"""
**Voice Message Transcription**

{transcript}

---
*Generated automatically from Slack voice message*
*Timestamp: {datetime.now().isoformat()}*
                """.strip(),
                'departmentId': ZOHO_DESK_DEPARTMENT_ID or 'default',
                'priority': 'Medium',
                'status': 'Open',
                'channel': 'Voice Message'
            }
            
            # Add metadata if provided
            if metadata:
                if 'user_name' in metadata:
                    ticket_data['contact'] = {
                        'firstName': metadata['user_name'],
                        'email': metadata.get('user_email', 'unknown@example.com')
                    }
                if 'channel_name' in metadata:
                    ticket_data['description'] += f"\n\n**Source Channel:** {metadata['channel_name']}"
            
            # Create ticket
            url = f"https://desk.zoho.com/desk/v1/tickets"
            headers = {
                'Authorization': f'Bearer {ZOHO_DESK_API_KEY}',
                'orgId': ZOHO_DESK_ORG_ID,
                'Content-Type': 'application/json'
            }
            
            response = requests.post(url, headers=headers, json=ticket_data, timeout=30)
            
            if response.status_code in [200, 201]:
                ticket_info = response.json()
                ticket_id = ticket_info.get('id')
                logger.info(f"✅ Zoho Desk ticket created successfully: {ticket_id}")
                return {
                    'success': True,
                    'ticket_id': ticket_id,
                    'ticket_url': f"https://desk.zoho.com/desk/v1/tickets/{ticket_id}"
                }
            else:
                logger.error(f"❌ Zoho Desk ticket creation failed: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': f"HTTP {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            logger.error(f"❌ Zoho Desk ticket creation error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def process_slack_voice_message(self, file_url, slack_token, metadata=None):
        """Complete workflow: Download → Transcribe → Create Zoho Desk ticket"""
        try:
            logger.info("🔄 Starting Slack voice message processing...")
            
            # Step 1: Download audio from Slack
            audio_file_path = self.download_audio_from_slack(file_url, slack_token)
            if not audio_file_path:
                return {
                    'success': False,
                    'error': 'Failed to download audio from Slack'
                }
            
            # Step 2: Transcribe audio
            transcript = self.transcribe_with_deepgram(audio_file_path)
            if not transcript:
                return {
                    'success': False,
                    'error': 'Transcription failed'
                }
            
            # Step 3: Create Zoho Desk ticket
            ticket_result = self.create_zoho_desk_ticket(transcript, metadata)
            
            # Clean up temporary file
            try:
                os.unlink(audio_file_path)
            except:
                pass
            
            if ticket_result.get('success'):
                return {
                    'success': True,
                    'transcript': transcript,
                    'ticket_id': ticket_result.get('ticket_id'),
                    'ticket_url': ticket_result.get('ticket_url'),
                    'message': 'Voice message processed successfully'
                }
            else:
                return {
                    'success': False,
                    'transcript': transcript,
                    'error': ticket_result.get('error', 'Failed to create Zoho Desk ticket')
                }
                
        except Exception as e:
            logger.error(f"❌ Processing error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

# Initialize worker
worker = SlackTranscriptionWorker()

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'service': 'Slack → Transcription → Zoho Desk Worker',
        'version': '1.0.0',
        'endpoints': {
            'webhook': '/webhook',
            'process': '/process',
            'health': '/',
            'status': '/status'
        },
        'configured_services': {
            'openai': bool(OPENAI_API_KEY),
            'assemblyai': bool(ASSEMBLYAI_API_KEY),
            'deepgram': bool(DEEPGRAM_API_KEY),
            'zoho_desk': bool(ZOHO_DESK_API_KEY and ZOHO_DESK_ORG_ID)
        }
    })

@app.route('/webhook', methods=['POST'])
def slack_webhook():
    """Webhook endpoint for Zapier to send Slack voice messages"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No JSON data received'
            }), 400
        
        # Extract required fields
        file_url = data.get('file_url')
        slack_token = data.get('slack_token')
        metadata = data.get('metadata', {})
        
        if not file_url or not slack_token:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: file_url and slack_token'
            }), 400
        
        logger.info(f"📨 Received webhook: {file_url}")
        
        # Process the voice message
        result = worker.process_slack_voice_message(file_url, slack_token, metadata)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/process', methods=['POST'])
def process_voice_message():
    """Direct processing endpoint for manual testing"""
    try:
        data = request.get_json()
        
        file_url = data.get('file_url')
        slack_token = data.get('slack_token')
        metadata = data.get('metadata', {})
        
        if not file_url or not slack_token:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: file_url and slack_token'
            }), 400
        
        result = worker.process_slack_voice_message(file_url, slack_token, metadata)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Process error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/status')
def status():
    """Detailed status endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'services': {
            'openai_whisper': bool(OPENAI_API_KEY),
            'assemblyai': bool(ASSEMBLYAI_API_KEY),
            'deepgram': bool(DEEPGRAM_API_KEY),
            'zoho_desk': bool(ZOHO_DESK_API_KEY and ZOHO_DESK_ORG_ID)
        },
        'configuration': {
            'zoho_org_id': ZOHO_DESK_ORG_ID,
            'zoho_department_id': ZOHO_DESK_DEPARTMENT_ID
        }
    })

@app.route('/test', methods=['POST'])
def test_endpoint():
    """Test endpoint for debugging"""
    return jsonify({
        'message': 'Test endpoint working',
        'received_data': request.get_json(),
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Slack Transcription Worker on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
