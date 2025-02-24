FROM python:3.9-slim

# Set the working directory in the container.
WORKDIR /app

# Copy local files to the container.
COPY . .

# Install the dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Expose ports if needed.
EXPOSE 8000

# Run the agent.
CMD ["python", "agent.py"]
