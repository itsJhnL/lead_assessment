#!/usr/bin/env bash
# The sequence used in the video demo. Run from the repo folder: bash demo.sh
set -e
cd "$(dirname "$0")"

echo "################ Part 2: weekly report ################"
python3 lead_report.py
echo
echo "################ Part 4: client-a (mock) ################"
python3 weekly_update.py --client client-a --mock || true
echo
echo "################ Part 4: client-b (mock) ################"
python3 weekly_update.py --client client-b --mock || true
echo
echo "################ Part 4: a bad AI response is rejected ################"
python3 weekly_update.py --client client-a --mock-file mock_responses/bad_cross_client.json --out drafts/rejected_examples || true
echo
echo "################ Tests ################"
python3 -m unittest -v
