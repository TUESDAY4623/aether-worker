#!/usr/bin/env python
"""Start Aether backend with proper module path."""
import sys
import os

# Add project PARENT directory to Python path so 'aether' package is resolvable
project_root = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(project_root)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Now import and run
from aether.controller.app import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
