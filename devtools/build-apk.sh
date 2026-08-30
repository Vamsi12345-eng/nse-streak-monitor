#!/usr/bin/env bash
# Builds the Android APK on this machine.
#
# Exists because a bare `gradle assembleDebug` fails here with
# "Unable to establish loopback connection". Java NIO builds its selector on an
# AF_UNIX socket pair created inside the directory named by the TEMP
# environment variable, and this profile's Temp directory cannot host one:
# the bind succeeds, connect returns "Invalid argument", and the leftover
# .sock file cannot even be deleted afterwards. Every other directory tried
# works, including ones with spaces and ones of similar depth, so it is that
# directory specifically rather than path length, spaces, or the 8.3 short
# name.
#
# The JVM's -Djava.io.tmpdir does NOT fix it - Windows resolves the AF_UNIX
# path natively from the environment - so TEMP/TMP must be overridden in the
# environment before Gradle starts.
set -euo pipefail

JDK="${JDK:-C:\\Program Files\\Eclipse Adoptium\\jdk-21.0.12.101-hotspot}"
SDK="${SDK:-D:\\Android\\Sdk}"
GRADLE_BIN="${GRADLE_BIN:-/d/Android/gradle/gradle-8.11.1/bin/gradle}"
BUILD_TMP="${BUILD_TMP:-C:\\gtmp}"

TMP_UNIX="/$(echo "$BUILD_TMP" | sed -e 's|\\|/|g' -e 's|^\([A-Za-z]\):|\L\1|')"
mkdir -p "$TMP_UNIX"

export JAVA_HOME="$JDK"
export ANDROID_HOME="$SDK"
export TEMP="$BUILD_TMP"
export TMP="$BUILD_TMP"

cd "$(dirname "$0")/../app"

TASK="${1:-assembleDebug}"
shift || true

echo "JAVA_HOME = $JAVA_HOME"
echo "TEMP      = $TEMP   (override; the default profile Temp breaks AF_UNIX)"
echo "task      = $TASK"
echo

"$GRADLE_BIN" "$TASK" --console=plain "$@"

APK=$(find . -name "*.apk" -newermt "-5 minutes" 2>/dev/null | head -1)
if [ -n "$APK" ]; then
  echo
  echo "APK: $(cd "$(dirname "$APK")" && pwd)/$(basename "$APK")"
  # du, not `ls -lh | awk`: the owner column contains spaces on this machine,
  # which shifts awk's field numbering and prints part of the username.
  echo "     $(du -h "$APK" | cut -f1)"
fi
