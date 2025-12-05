@echo off
start cmd /k ".v\Scripts\activate && python broker.py"
start cmd /k ".v\Scripts\activate && python publisher.py --only-taps"