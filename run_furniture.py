#!/usr/bin/env python3
"""Run DealSpotter for furniture only."""
import sys
sys.argv = [sys.argv[0], "--category", "furniture"]
from main import main
main()
