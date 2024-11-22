# build-image.ps1

# Build and push Frontend image
docker build -t video-transcription-frontend ./frontend
docker tag video-transcription-frontend tbelbek/video-transcription-frontend:latest
docker push tbelbek/video-transcription-frontend:latest

# Build and push Backend image
docker build -t video-transcription-backend ./backend
docker tag video-transcription-backend tbelbek/video-transcription-backend:latest
docker push tbelbek/video-transcription-backend:latest

# Deploy using Docker Compose
docker-compose pull
docker-compose up -d