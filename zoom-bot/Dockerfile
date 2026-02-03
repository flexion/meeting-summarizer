# Force x86_64 since Zoom SDK is only available for x86_64
FROM --platform=linux/amd64 python:3.11-slim-bookworm

# Install system dependencies required by zoom-meeting-sdk
# Note: Using -o options to work around Docker clock sync issues
RUN apt-get -o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false update || true && \
    apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    libgl1 \
    libglib2.0-dev \
    libsm6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    libice6 \
    libasound2 \
    libpulse0 \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxkbcommon-x11-0 \
    libxkbcommon0 \
    libegl1 \
    libdbus-1-3 \
    libxcb-cursor0 \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the Zoom SDK files
COPY h/ /app/zoomsdk/h/
COPY libmeetingsdk.so libcml.so libmpg123.so /app/zoomsdk/
COPY qt_libs/ /app/zoomsdk/qt_libs/

# Set environment for SDK - use SDK's bundled Qt libraries and plugins
ENV ZOOM_SDK_DIR=/app/zoomsdk
ENV LD_LIBRARY_PATH=/app/zoomsdk:/app/zoomsdk/qt_libs/Qt/lib:$LD_LIBRARY_PATH
ENV QT_PLUGIN_PATH=/app/zoomsdk/qt_libs/Qt/plugins
ENV QT_QPA_PLATFORM=minimal
ENV QT_QPA_PLATFORM_PLUGIN_PATH=/app/zoomsdk/qt_libs/Qt/plugins/platforms

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY zoom_bot.py .
COPY start.sh .
RUN chmod +x start.sh
COPY .env* ./

# Expose WebSocket port for audio streaming
EXPOSE 3001

# Run the bot with Xvfb for virtual display (required for Qt)
CMD ["./start.sh"]
