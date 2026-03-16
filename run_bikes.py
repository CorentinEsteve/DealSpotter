#!/usr/bin/env python3
"""Run DealSpotter for bikes only."""
import sys
sys.argv = [sys.argv[0], "--category", "bikes"]
from main import main
main()
