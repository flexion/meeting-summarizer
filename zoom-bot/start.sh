#!/bin/bash
# Start Xvfb in background for Qt xcb platform
Xvfb :99 -screen 0 1024x768x24 &
sleep 2
export DISPLAY=:99

# Use SDK's Qt libraries exclusively
export LD_LIBRARY_PATH="/app/zoomsdk/qt_libs/Qt/lib:/app/zoomsdk:$LD_LIBRARY_PATH"

# Force Qt to use SDK's plugins and xcb platform (with Xvfb)
export QT_PLUGIN_PATH="/app/zoomsdk/qt_libs/Qt/plugins"
export QT_QPA_PLATFORM=xcb
export QT_QPA_PLATFORM_PLUGIN_PATH="/app/zoomsdk/qt_libs/Qt/plugins/platforms"

# Preload all critical Qt5 libs to ensure PyQt5 uses SDK's versions
export LD_PRELOAD="/app/zoomsdk/qt_libs/Qt/lib/libQt5Core.so.5:/app/zoomsdk/qt_libs/Qt/lib/libQt5Gui.so.5:/app/zoomsdk/qt_libs/Qt/lib/libQt5Widgets.so.5:/app/zoomsdk/qt_libs/Qt/lib/libQt5XcbQpa.so.5:/app/zoomsdk/qt_libs/Qt/lib/libQt5DBus.so.5"

# Debug: show which Qt libs are actually loaded
echo "[start.sh] Qt library check:"
ls -la /app/zoomsdk/qt_libs/Qt/lib/libQt5*.so.5 2>/dev/null | head -5
echo "[start.sh] Platform plugins:"
ls /app/zoomsdk/qt_libs/Qt/plugins/platforms/ 2>/dev/null

# Run the bot
exec python zoom_bot.py
