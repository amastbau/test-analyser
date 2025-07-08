# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables to prevent Python from writing .pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project code into the container
COPY . /app/

# Expose the port the app runs on
EXPOSE 8000

# Run the application
# Using 0.0.0.0 makes the server accessible from outside the container
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

