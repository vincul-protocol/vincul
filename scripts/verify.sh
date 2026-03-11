#!/usr/bin/env bash
# Full verification suite for vincul
set -e
cd "$(dirname "$0")/.."

source ~/venv_dev/bin/activate

echo "=== Test Suite ==="
python -m pytest tests/ -x -q

echo ""
echo "=== CI Vectors ==="
python ci/check_vectors.py

echo ""
echo "=== Trip Planner Demo ==="
python -m apps.trip_planner.demo

echo ""
echo "=== Marketplace Demo (SDK) ==="
python -m apps.tool_marketplace.demo

echo ""
echo "=== Marketplace Demo (VinculNet) ==="
python -m apps.tool_marketplace.demo --vinculnet

echo ""
echo "=== All checks passed ==="
