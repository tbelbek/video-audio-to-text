# Build the Docker image
docker build -t video-transcription-app .

# Tag the Docker image
docker tag video-transcription-app tbelbek/video-transcription-app:latest

# Push the Docker image to the registry
docker push tbelbek/video-transcription-app:latest

# Pull the latest images defined in the docker-compose.yml file
docker-compose pull

# Start the services defined in the docker-compose.yml file in detached mode
docker-compose up -d