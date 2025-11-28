import os
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from flask_login import login_user, logout_user, login_required, current_user
from .extensions import db, login_manager
from .models import User, Video, ChatMessage
import threading

# Initialize Flask app
app = Flask(__name__, static_url_path='/static', static_folder='static')
app.secret_key = "supersecretkey" # Change this in production
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 # 100MB max upload
# Database Configuration
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///' + os.path.join(app.instance_path, 'app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize Extensions
db.init_app(app)
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
# Ensure instance directory exists
os.makedirs(app.instance_path, exist_ok=True)

# Create DB Tables
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    if current_user.is_authenticated:
        videos = Video.query.filter_by(user_id=current_user.id).order_by(Video.created_at.desc()).all()
        return render_template('index.html', videos=videos)
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for('index'))
            
    return render_template('register.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_video():
    if request.method == 'GET':
        return redirect(url_for('index'))
        
    youtube_url = request.form.get('youtube_url')
    
    if youtube_url:
        # Handle YouTube Download
        from .utils import download_youtube_video
        import uuid
        
        filename = f"youtube_{uuid.uuid4().hex}.mp4"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        if download_youtube_video(youtube_url, save_path):
            # Check if S3 is configured
            s3_bucket = os.getenv('AWS_BUCKET_NAME')
            
            if s3_bucket:
                # Upload to S3
                from .utils import upload_to_s3
                s3_key = f"uploads/{current_user.id}/{filename}"
                
                # Open the downloaded file to upload to S3
                with open(save_path, 'rb') as f:
                    if upload_to_s3(f, s3_bucket, s3_key, content_type='video/mp4'):
                        # Save to DB with S3 Key
                        video = Video(title=f"YouTube: {youtube_url}", filename=filename, s3_key=s3_key, status="pending", author=current_user)
                        db.session.add(video)
                        db.session.commit()
                        
                        # Trigger background processing
                        from .processing import process_video
                        app_ctx = app.app_context()
                        threading.Thread(target=process_video, args=(video.id, app_ctx)).start()
                        
                        # Cleanup local file after S3 upload
                        os.remove(save_path)
                        
                        flash('YouTube video processed and uploaded to S3!')
                        return redirect(url_for('index'))
                    else:
                        flash('Failed to upload YouTube video to S3')
                        return redirect(request.url)
            else:
                # Local Storage
                db_path = f"static/uploads/{filename}"
                
                # Save to DB
                video = Video(title=f"YouTube: {youtube_url}", filename=filename, file_path=db_path, status="pending", author=current_user)
                db.session.add(video)
                db.session.commit()
                
                # Trigger background processing
                from .processing import process_video
                app_ctx = app.app_context()
                threading.Thread(target=process_video, args=(video.id, app_ctx)).start()
                    
                flash('YouTube video downloaded and processing started!')
                return redirect(url_for('index'))
        else:
            flash('Failed to download YouTube video')
            return redirect(request.url)

    if 'video' not in request.files:
        flash('No file part')
        return redirect(request.url)
    
    file = request.files['video']
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    
    if file:
        filename = secure_filename(file.filename)
        
        # Check if S3 is configured
        s3_bucket = os.getenv('AWS_BUCKET_NAME')
        
        if s3_bucket:
            # Upload to S3
            from .utils import upload_to_s3
            s3_key = f"uploads/{current_user.id}/{filename}"
            if upload_to_s3(file, s3_bucket, s3_key, content_type=file.content_type):
                # Save to DB with S3 Key
                video = Video(title=filename, filename=filename, s3_key=s3_key, status="pending", author=current_user)
                db.session.add(video)
                db.session.commit()
                
                # Trigger background processing
                from .processing import process_video
                app_ctx = app.app_context()
                threading.Thread(target=process_video, args=(video.id, app_ctx)).start()
                
                flash('Video uploaded to S3 successfully!')
                return redirect(url_for('index'))
            else:
                flash('Failed to upload to S3')
                return redirect(request.url)
        else:
            # Fallback to Local Storage
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(save_path)
            
            db_path = f"static/uploads/{filename}"
            
            # Save to DB
            video = Video(title=filename, filename=filename, file_path=db_path, status="pending", author=current_user)
            db.session.add(video)
            db.session.commit()
            
            # Trigger background processing
            from .processing import process_video
            app_ctx = app.app_context()
            threading.Thread(target=process_video, args=(video.id, app_ctx)).start()
                
            flash('Video uploaded successfully!')
            return redirect(url_for('index'))

@app.route('/video/<int:video_id>')
@login_required
def view_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.author != current_user:
        return "Unauthorized", 403
        
    video_url = None
    if video.s3_key:
        from .utils import generate_presigned_url
        import mimetypes
        
        s3_bucket = os.getenv('AWS_BUCKET_NAME')
        if s3_bucket:
            # Guess mime type based on filename
            content_type, _ = mimetypes.guess_type(video.filename)
            if not content_type:
                content_type = 'video/mp4' # Default fallback
                
            video_url = generate_presigned_url(s3_bucket, video.s3_key, response_content_type=content_type)
            print(f"Generated S3 URL for video {video_id}: {video_url}")
    
    # Fallback to local path if no S3 key or generation failed
    if not video_url and video.file_path:
        video_url = "/" + video.file_path
        
    print(f"DEBUG: Rendering video page for {video_id} with URL: {video_url}")
    return render_template('video.html', video=video, video_url=video_url)

@app.route('/video/<int:video_id>/qa', methods=['POST'])
@login_required
def qa_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.author != current_user:
        return {"error": "Unauthorized"}, 403
        
    question = request.json.get('question')
    if not question:
        return {"error": "No question provided"}, 400
        
    # Save User Message
    user_msg = ChatMessage(text=question, sender='user', video=video)
    db.session.add(user_msg)
    db.session.commit()
    
    from .rag import ask_question
    answer_data = ask_question(video, question)
    
    # Save AI Message
    if 'text' in answer_data:
        ai_msg = ChatMessage(text=answer_data['text'], sender='ai', video=video)
        db.session.add(ai_msg)
        db.session.commit()
    
    return answer_data

@app.route('/video/<int:video_id>/quiz', methods=['GET'])
@login_required
def get_video_quiz(video_id):
    video = Video.query.get_or_404(video_id)
    if video.author != current_user:
        return {"error": "Unauthorized"}, 403
        
    from .rag import generate_quiz
    quiz_data = generate_quiz(video)
    return quiz_data

@app.route('/api/videos/status')
@login_required
def get_videos_status():
    videos = Video.query.filter_by(user_id=current_user.id).all()
    return {
        "videos": [
            {
                "id": v.id,
                "status": v.status
            } for v in videos
        ]
    }

if __name__ == '__main__':
    app.run(debug=True, port=5000)
