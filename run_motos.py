#!/usr/bin/env python3
"""Run DealSpotter for motos only."""
import sys
sys.argv = [sys.argv[0], "--category", "motos"]
from main import main
main()
