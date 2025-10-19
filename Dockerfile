# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Switch to root user temporarily to install system packages
USER root

# Update package lists and install FFmpeg and other dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git curl && \
    # Clean up to reduce image size
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /usr/src/app
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Create a non-root user and give it necessary permissions
RUN useradd -m worker && chown -R worker:worker /usr/src/app

# Switch to the non-root user
USER worker

# Expose the port the app runs on
EXPOSE 8080

# Run the application
CMD ["python3", "-m", "FileStream"]
