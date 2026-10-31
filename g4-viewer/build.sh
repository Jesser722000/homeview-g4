#!/bin/sh
# Build HomeView.jar. Run this ON THE iMac G4 (Mac OS X 10.4 ships javac with Java 1.4/1.5), in this folder:
#   sh build.sh
# The jar then runs with:  java -jar HomeView.jar   (or double-click it, or make it a login item)
set -e
cd "$(dirname "$0")"
rm -rf classes && mkdir classes
javac -source 1.4 -target 1.4 -d classes HVViewer.java 2>/dev/null || javac -d classes HVViewer.java
jar cfm HomeView.jar manifest.txt -C classes .
rm -rf classes
echo "Built $(pwd)/HomeView.jar"
